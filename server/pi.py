"""Pi MVP adapter: one advertised item, one lease, explicit acknowledgment."""

import hashlib
import sqlite3
import time
from contextlib import closing

from .store import QueueError, QueueStore, utc_iso

PI_DEVICE = "pi-pager"
PI_SCHEMA = """
CREATE TABLE IF NOT EXISTS pi_device (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_seen REAL,
    last_poll REAL
);
INSERT OR IGNORE INTO pi_device(id) VALUES (1);
CREATE TABLE IF NOT EXISTS pi_transfers (
    message_id TEXT PRIMARY KEY,
    lease_id TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at REAL NOT NULL,
    downloaded_at REAL,
    acknowledged_at REAL,
    error TEXT
);
"""


class PiDelivery:
    def __init__(self, store: QueueStore):
        self.store = store

    def initialize(self):
        with closing(sqlite3.connect(self.store.path)) as connection:
            connection.executescript(PI_SCHEMA)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(pi_transfers)")}
            if "download_confirmed_at" not in columns:
                connection.execute("ALTER TABLE pi_transfers ADD COLUMN download_confirmed_at REAL")
            connection.commit()

    @staticmethod
    def touch(connection, *, poll=False):
        now = time.time()
        if poll:
            connection.execute(
                "UPDATE pi_device SET last_seen = ?, last_poll = ? WHERE id = 1", (now, now)
            )
        else:
            connection.execute("UPDATE pi_device SET last_seen = ? WHERE id = 1", (now,))

    def status(self) -> dict:
        with self.store.transaction() as connection:
            self.touch(connection, poll=True)
            self.store.expire_leases(connection, time.time())
            active = connection.execute(
                """SELECT m.id, m.priority FROM delivery_leases l
                   JOIN messages m ON m.id = l.message_id WHERE l.device_id = ?""",
                (PI_DEVICE,),
            ).fetchone()
            if active is None:
                active = connection.execute(
                    """SELECT id, priority FROM messages WHERE priority >= 3
                       AND status IN ('pending', 'processing', 'ready')
                       ORDER BY priority DESC, received_at, created_at, rowid LIMIT 1"""
                ).fetchone()
            # The next transferable item may be a lower-priority active lease.
            # Signal emergencies independently without interrupting its audio.
            urgent = connection.execute(
                """SELECT 1 FROM messages WHERE priority = 5
                   AND status IN ('pending', 'processing', 'ready', 'leased') LIMIT 1"""
            ).fetchone()
            return {"items": [dict(active)] if active else [], "led_on": urgent is not None}

    def begin_audio(self, message_id: str):
        delivery = self.store.claim(PI_DEVICE, expected_message_id=message_id)
        if delivery is None:
            raise QueueError(409, "Audio is not ready. Refresh status and try again.")
        path = self.store.authorize_audio(delivery["lease_id"], PI_DEVICE)
        with self.store.transaction() as connection:
            self.touch(connection)
            connection.execute(
                """INSERT INTO pi_transfers(message_id, lease_id, status, updated_at)
                   VALUES (?, ?, 'downloading', ?)
                   ON CONFLICT(message_id) DO UPDATE SET lease_id=excluded.lease_id,
                     status='downloading', updated_at=excluded.updated_at,
                     downloaded_at=NULL, acknowledged_at=NULL, download_confirmed_at=NULL,
                     error=NULL""",
                (message_id, delivery["lease_id"], time.time()),
            )
            connection.execute(
                """DELETE FROM pi_transfers WHERE message_id NOT IN
                   (SELECT message_id FROM pi_transfers ORDER BY updated_at DESC LIMIT 1000)"""
            )
        return path, delivery["lease_id"]

    def finish_audio(self, message_id: str, lease_id: str, success: bool):
        now = time.time()
        with self.store.transaction() as connection:
            connection.execute(
                """UPDATE pi_transfers SET status=?, updated_at=?, downloaded_at=?, error=?
                   WHERE message_id=? AND lease_id=? AND status != 'acknowledged'""",
                (
                    "awaiting_ack" if success else "failed",
                    now,
                    now if success else None,
                    None if success else "Audio transfer interrupted",
                    message_id,
                    lease_id,
                ),
            )

    def confirm_download(self, message_id: str, transfer_id: str, size: int, sha256: str) -> dict:
        """A receipt for a validated local file; never completes or extends playback."""
        with self.store.transaction() as connection:
            transfer = connection.execute(
                "SELECT * FROM pi_transfers WHERE message_id=?", (message_id,)
            ).fetchone()
            if (transfer is None or transfer["lease_id"] != transfer_id
                    or transfer["status"] != "awaiting_ack"):
                raise QueueError(409, "No matching completed Pi transfer.")
            lease = self.store.require_active(connection, transfer_id, PI_DEVICE, time.time())
            if lease["message_id"] != message_id:
                raise QueueError(409, "The download receipt does not match the active item.")
            path = self.store.audio_path(message_id)
            try:
                if path.stat().st_size != size:
                    raise QueueError(409, "Downloaded audio size does not match.")
                with path.open("rb") as file:
                    digest = hashlib.file_digest(file, "sha256").hexdigest()
            except OSError:
                raise QueueError(409, "The audio is no longer available.") from None
            if digest != sha256:
                raise QueueError(409, "Downloaded audio checksum does not match.")
            now = time.time()
            self.touch(connection)
            connection.execute(
                """UPDATE pi_transfers SET download_confirmed_at=COALESCE(download_confirmed_at, ?),
                   updated_at=? WHERE message_id=?""", (now, now, message_id)
            )
        return {"status": "download_confirmed", "id": message_id}

    def acknowledge(self, message_id: str) -> dict:
        with self.store.transaction() as connection:
            self.touch(connection)
            transfer = connection.execute(
                "SELECT * FROM pi_transfers WHERE message_id=?", (message_id,)
            ).fetchone()
            if transfer is None:
                raise QueueError(409, "The Pi has not downloaded this notification.")
            if transfer["status"] == "acknowledged":
                return {"status": "acknowledged", "ids": [message_id]}
            if transfer["status"] != "awaiting_ack":
                raise QueueError(409, "The audio transfer has not completed.")
            lease = self.store.require_active(
                connection, transfer["lease_id"], PI_DEVICE, time.time()
            )
            if lease["message_id"] != message_id:
                raise QueueError(409, "The acknowledgment does not match the active notification.")
            self.store.release_lease(connection, lease, "played")
            connection.execute(
                """UPDATE pi_transfers SET status='acknowledged', acknowledged_at=?, updated_at=?, error=NULL
                   WHERE message_id=?""",
                (time.time(), time.time(), message_id),
            )
        self.store.cleanup_played_audio(transfer["lease_id"])
        return {"status": "acknowledged", "ids": [message_id]}

    def dashboard(self) -> dict:
        now = time.time()
        with self.store.transaction() as connection:
            device = connection.execute("SELECT * FROM pi_device WHERE id=1").fetchone()
            rows = connection.execute(
                """SELECT t.*, l.expires_at, m.spoken_text, m.app, m.sender, m.priority
                   FROM pi_transfers t LEFT JOIN delivery_leases l ON l.id=t.lease_id
                   LEFT JOIN messages m ON m.id=t.message_id
                   ORDER BY t.updated_at DESC LIMIT 10"""
            ).fetchall()
        transfers = []
        for row in rows:
            status = row["status"]
            if status in {"downloading", "awaiting_ack"} and (
                row["expires_at"] is None or row["expires_at"] <= now
            ):
                status = "expired"
            transfers.append(
                {
                    "message_id": row["message_id"],
                    "status": status,
                    "spoken_text": row["spoken_text"],
                    "app": row["app"],
                    "sender": row["sender"],
                    "priority": row["priority"],
                    "download_confirmed_at": utc_iso(row["download_confirmed_at"])
                    if row["download_confirmed_at"] else None,
                    "updated_at": utc_iso(row["updated_at"]),
                    "downloaded_at": utc_iso(row["downloaded_at"])
                    if row["downloaded_at"]
                    else None,
                    "acknowledged_at": utc_iso(row["acknowledged_at"])
                    if row["acknowledged_at"]
                    else None,
                    "error": row["error"],
                }
            )
        return {
            "connected": bool(device["last_seen"] and now - device["last_seen"] <= 15),
            "last_seen": utc_iso(device["last_seen"]) if device["last_seen"] else None,
            "transfers": transfers,
        }
