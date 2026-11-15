import json
import re
import shutil
import sqlite3
import threading
import time
from contextlib import closing, contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from contracts.app_names import request_app_label
from contracts.esp import parse_esp_json
from contracts.models import ClassificationResult, NotificationGroup, NotificationInput
from contracts.settings import Settings
from intelligence.notification_rules import device_rule

STATE_LIMIT = 100
HISTORY_LIMIT = 10_000
REQUEST_HISTORY_LIMIT = 1_000
REQUEST_PAYLOAD_SECONDS = 2 * 60 * 60
CLASSIFICATION_BURST = 10
CLASSIFICATION_BATCH_LIMIT = 10
SQLITE_TIMEOUT_SECONDS = 0.25
MANAGED_AUDIO = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}(?:\.pending)?\.wav")
ERROR_MESSAGES = {
    "content_unavailable": "Content unavailable or insufficient to interpret; not queued for playback.",
    "missing_api_key": "OpenAI API key is missing.",
    "classification_timeout": "Classification timed out.",
    "classification_unavailable": "Classification service was unavailable.",
    "classification_invalid": "The classifier returned an invalid result.",
    "classification_incomplete": "The classifier returned an incomplete result.",
    "classification_refused": "The classifier declined to classify this notification.",
    "summary_timeout": "Conversation summarization timed out.",
    "summary_unavailable": "Conversation summarization was unavailable.",
    "summary_invalid": "The conversation summarizer returned an invalid result.",
    "summary_incomplete": "The conversation summarizer returned an incomplete result.",
    "summary_refused": "The summarizer declined to summarize this conversation.",
    "speech_timeout": "Speech generation timed out.",
    "speech_unavailable": "Speech generation was unavailable.",
    "speech_invalid": "Speech generation returned invalid audio.",
    "delivery_exhausted": "Playback exceeded the delivery attempt limit.",
    "audio_missing": "The queued audio file is missing.",
    "provider_budget": "The provider operation limit has been reached.",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    received_at REAL NOT NULL,
    app TEXT NOT NULL,
    sender TEXT,
    input_json TEXT,
    priority INTEGER,
    spoken_text TEXT,
    error TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    group_key TEXT,
    conversation_name TEXT,
    needs_summary INTEGER NOT NULL DEFAULT 0,
    sealed INTEGER NOT NULL DEFAULT 0,
    not_before REAL NOT NULL DEFAULT 0,
    reserved_operations INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS messages_status ON messages(status, priority, created_at);

CREATE TABLE IF NOT EXISTS group_members (
    event_id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    sender TEXT,
    priority INTEGER NOT NULL,
    spoken_text TEXT NOT NULL,
    received_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS members_group ON group_members(group_id, received_at);

CREATE TABLE IF NOT EXISTS delivery_leases (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE REFERENCES messages(id),
    device_id TEXT NOT NULL UNIQUE,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS delivery_expiry ON delivery_leases(expires_at);

CREATE TABLE IF NOT EXISTS delivery_receipts (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS completed_events (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS completed_status ON completed_events(status);
CREATE TABLE IF NOT EXISTS audio_cleanup (
    message_id TEXT PRIMARY KEY,
    lease_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS ingress_history (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    event_id TEXT,
    record_json TEXT NOT NULL,
    priority INTEGER,
    queue_status TEXT,
    finished INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ingress_event ON ingress_history(event_id);
CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
INSERT OR IGNORE INTO counters VALUES ('provider_calls', 0);
INSERT OR IGNORE INTO counters VALUES ('classification_streak', 0);
"""


class QueueError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def utc_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def grouping_key(notification: NotificationInput) -> str | None:
    app = " ".join(notification.app.split()).casefold()
    for kind, value in (
        ("conversation", notification.conversation_id),
        ("sender_id", notification.sender_id),
        ("sender", notification.sender),
    ):
        if value and value.strip():
            normalized = " ".join(value.split()).casefold() if kind == "sender" else value.strip()
            return json.dumps((app, kind, normalized))
    return None


class QueueStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.data_dir / "pager.sqlite3"
        self.audio_dir = settings.data_dir / "audio"
        self._last_payload_prune = 0.0
        self._write_lock = threading.RLock()

    @contextmanager
    def transaction(self):
        with (
            self._write_lock,
            closing(sqlite3.connect(self.path, timeout=SQLITE_TIMEOUT_SECONDS)) as connection,
            connection,
        ):
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA secure_delete = ON")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            yield connection

    def initialize(self):
        self.settings.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.audio_dir.mkdir(mode=0o700, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=SQLITE_TIMEOUT_SECONDS)) as connection:
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.executescript(SCHEMA)
        with self.transaction() as connection:
            self.migrate(connection)
            connection.execute(
                """CREATE INDEX IF NOT EXISTS messages_group_window
                   ON messages(group_key, status, created_at)"""
            )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS messages_delivery_order
                   ON messages(priority DESC, received_at, created_at)"""
            )
            self.backfill_pending_keys(connection)
            self.initialize_history(connection)
            connection.execute("UPDATE messages SET status = 'pending' WHERE status = 'processing'")
            self.reconcile_snapchat(connection)
            self.reconcile_findmy_separation(connection)
            # Remove only recognizable, unclaimed legacy unavailable cues.
            unavailable = connection.execute(
                """SELECT id FROM messages WHERE sealed=0 AND status != 'leased'
                   AND spoken_text LIKE '%. Content unavailable. Check your phone.'
                   AND (SELECT COUNT(*) FROM group_members WHERE group_id=messages.id) <= 1"""
            ).fetchall()
            for row in unavailable:
                self.complete(connection, row["id"], "failed")
            self.coalesce_unclaimed_groups(connection)
            self.expire_leases(connection, time.time())
            saved_audio = {
                self.audio_path(row["id"]).name
                for row in connection.execute(
                    """SELECT id FROM messages WHERE status IN ('ready', 'leased')
                       OR (status = 'failed' AND error = 'delivery_exhausted')
                       UNION ALL SELECT message_id FROM audio_cleanup"""
                )
            }
        for file in self.audio_dir.iterdir():
            if file.is_dir() and not file.is_symlink() and file.name.startswith(".speech-"):
                shutil.rmtree(file)
            elif (
                file.name not in saved_audio
                and MANAGED_AUDIO.fullmatch(file.name)
                and (file.is_file() or file.is_symlink())
            ):
                file.unlink()
        self.cleanup_played_audio()

    @staticmethod
    def migrate(connection: sqlite3.Connection):
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(messages)")}
        if "reserved_operations" not in columns:
            connection.execute(
                "ALTER TABLE messages ADD COLUMN reserved_operations INTEGER NOT NULL DEFAULT 0"
            )
        if "received_at" not in columns:
            QueueStore.migrate_received_at(connection)
        if "group_key" in columns:
            return
        connection.execute("ALTER TABLE messages ADD COLUMN group_key TEXT")
        connection.execute("ALTER TABLE messages ADD COLUMN conversation_name TEXT")
        connection.execute(
            "ALTER TABLE messages ADD COLUMN needs_summary INTEGER NOT NULL DEFAULT 0"
        )
        connection.execute("ALTER TABLE messages ADD COLUMN sealed INTEGER NOT NULL DEFAULT 0")
        connection.execute("ALTER TABLE messages ADD COLUMN not_before REAL NOT NULL DEFAULT 0")
        connection.execute(
            """INSERT INTO group_members (event_id, group_id, sender, priority, spoken_text, received_at)
               SELECT id, id, sender, priority, spoken_text, received_at
               FROM messages WHERE priority IS NOT NULL"""
        )
        connection.execute(
            """UPDATE messages SET input_json = json_remove(input_json, '$.tts_voice')
               WHERE input_json IS NOT NULL AND json_valid(input_json)"""
        )
        connection.execute("UPDATE messages SET sealed = 1 WHERE attempt > 0 OR status = 'leased'")

    @staticmethod
    def migrate_received_at(connection: sqlite3.Connection):
        connection.execute("ALTER TABLE messages ADD COLUMN received_at REAL NOT NULL DEFAULT 0")
        rows = connection.execute(
            """SELECT messages.id, messages.created_at, messages.input_json,
                      group_members.received_at AS member_received_at
               FROM messages LEFT JOIN group_members ON group_members.event_id = messages.id"""
        ).fetchall()
        for row in rows:
            received_at = row["member_received_at"]
            if row["input_json"] is not None:
                source = connection.execute(
                    """SELECT json_extract(?, '$.received_at') WHERE json_valid(?)""",
                    (row["input_json"], row["input_json"]),
                ).fetchone()
                if source and isinstance(source[0], str):
                    try:
                        parsed = datetime.fromisoformat(source[0])
                        if parsed.utcoffset() is not None:
                            received_at = parsed.timestamp()
                    except ValueError:
                        pass
            connection.execute(
                "UPDATE messages SET received_at = ? WHERE id = ?",
                (row["created_at"] if received_at is None else received_at, row["id"]),
            )

    @staticmethod
    def backfill_pending_keys(connection: sqlite3.Connection):
        rows = connection.execute(
            "SELECT id, input_json FROM messages WHERE priority IS NULL AND group_key IS NULL"
        ).fetchall()
        for row in rows:
            # Leave invalid legacy records for the worker to mark failed with a sanitized error.
            try:
                notification = NotificationInput.model_validate_json(row["input_json"])
            except ValueError:
                continue
            key = grouping_key(notification)
            if key is not None:
                connection.execute(
                    "UPDATE messages SET group_key = ? WHERE id = ?", (key, row["id"])
                )

    def initialize_history(self, connection: sqlite3.Connection):
        if connection.execute("SELECT 1 FROM counters WHERE name = 'completed_events'").fetchone():
            return
        for status in ("played", "discarded"):
            total = connection.execute(
                "SELECT COUNT(*) FROM completed_events WHERE status = ?", (status,)
            ).fetchone()[0]
            connection.execute("INSERT INTO counters VALUES (?, ?)", (status, total))
        self.record_history(connection, "completed_events")
        self.record_history(connection, "delivery_receipts")

    @staticmethod
    def record_history(connection: sqlite3.Connection, table: str, inserted: int | None = None):
        # Only callers using our two fixed table names may use this method.
        if inserted is None:
            retained = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            connection.execute("INSERT INTO counters VALUES (?, ?)", (table, retained))
        else:
            retained = connection.execute(
                "UPDATE counters SET value = value + ? WHERE name = ? RETURNING value",
                (inserted, table),
            ).fetchone()[0]
        excess = retained - HISTORY_LIMIT
        if excess > 0:
            connection.execute(
                f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} ORDER BY rowid LIMIT ?)",
                (excess,),
            )
            connection.execute(
                "UPDATE counters SET value = ? WHERE name = ?", (HISTORY_LIMIT, table)
            )

    def audio_path(self, message_id: str) -> Path:
        return self.audio_dir / f"{message_id}.wav"

    def available_audio(self, message_id: str) -> Path | None:
        path = self.audio_path(message_id)
        return path if path.is_file() and not path.is_symlink() else None

    def enqueue(self, notification: NotificationInput) -> str:
        event_id = str(notification.event_id)
        with self.transaction() as connection:
            existing = connection.execute(
                """SELECT status FROM messages WHERE id = ?
                   UNION ALL SELECT messages.status FROM group_members
                   JOIN messages ON messages.id = group_members.group_id WHERE event_id = ?
                   UNION ALL SELECT status FROM completed_events WHERE id = ?""",
                (event_id, event_id, event_id),
            ).fetchone()
            if existing:
                return "pending" if existing["status"] == "processing" else existing["status"]
            rule = device_rule(notification)
            if rule is not None and rule.priority <= 2:
                connection.execute(
                    "UPDATE ingress_history SET priority=? WHERE event_id=?", (rule.priority, event_id)
                )
                self.complete(connection, event_id, "discarded")
                return "discarded"
            total = connection.execute(
                """SELECT (SELECT COUNT(*) FROM messages WHERE priority IS NULL)
                        + (SELECT COUNT(*) FROM group_members)
                        + (SELECT COUNT(*) FROM audio_cleanup)"""
            ).fetchone()[0]
            if total >= self.settings.max_pending_notifications:
                raise QueueError(429, "The notification queue is full.")
            connection.execute(
                """INSERT INTO messages
                   (id, status, created_at, received_at, app, sender, input_json, group_key)
                   VALUES (?, 'pending', ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    time.time(),
                    notification.received_at.timestamp(),
                    notification.app,
                    notification.sender,
                    notification.model_dump_json(),
                    grouping_key(notification),
                ),
            )
            if rule is not None:
                key = json.dumps(("phone-call", rule.kind, rule.caller_key)) if rule.caller_key else None
                if rule.kind == "snapchat_chat":
                    key = '["snapchat-direct-v1"]'
                connection.execute(
                    """UPDATE messages SET priority=3, spoken_text=?, sender=?, input_json=NULL,
                       group_key=? WHERE id=?""", (rule.spoken_text, rule.caller, key, event_id)
                )
                connection.execute(
                    "INSERT INTO group_members VALUES (?, ?, ?, 3, ?, ?)",
                    (event_id, event_id, rule.caller, rule.spoken_text,
                     notification.received_at.timestamp()),
                )
                connection.execute(
                    "UPDATE ingress_history SET priority=3 WHERE event_id=?", (event_id,)
                )
                if rule.kind in {"incoming", "missed"}:
                    self.coalesce_calls(connection)
        return "pending"

    def reconcile_snapchat(self, connection):
        """Apply the allowlist to old unclaimed standalone items during startup.

        Never resurrect completed events or rewrite a sealed delivery. Original
        accepted payloads remain unchanged. Missing/expired evidence is ineligible.
        """
        rows = connection.execute(
            """SELECT * FROM messages WHERE lower(app) IN ('com.toyopagroup.picaboo', 'snapchat')
               AND NOT sealed AND status IN ('pending', 'ready', 'failed')
               AND (SELECT COUNT(*) FROM group_members WHERE group_id=messages.id) <= 1"""
        ).fetchall()
        for row in rows:
            if row["group_key"] == '["snapchat-direct-v1"]':
                continue
            notification = None
            try:
                if row["input_json"]:
                    notification = NotificationInput.model_validate_json(row["input_json"])
                else:
                    history = connection.execute(
                        "SELECT record_json FROM ingress_history WHERE event_id=? ORDER BY sequence DESC LIMIT 1",
                        (row["id"],),
                    ).fetchone()
                    if history:
                        payload = json.loads(history[0]).get("payload")
                        if isinstance(payload, dict):
                            notification = parse_esp_json(
                                json.dumps(payload), timezone_name=self.settings.esp_timezone,
                            )
            except ValueError:
                pass
            rule = device_rule(notification) if notification else None
            priority = rule.priority if rule else 2
            connection.execute("UPDATE ingress_history SET priority=? WHERE event_id=?",
                               (priority, row["id"]))
            if priority <= 2:
                self.complete(connection, row["id"], "discarded")
                continue
            if row["priority"] == 3 and row["spoken_text"] == rule.spoken_text:
                connection.execute("UPDATE messages SET group_key=? WHERE id=?",
                                   ('["snapchat-direct-v1"]', row["id"]))
                continue
            connection.execute(
                """UPDATE messages SET status='pending', priority=3, spoken_text=?, sender=?,
                   input_json=NULL, group_key='["snapchat-direct-v1"]', needs_summary=0, reserved_operations=0,
                   not_before=0, error=NULL WHERE id=?""",
                (rule.spoken_text, rule.caller, row["id"]),
            )
            connection.execute(
                """INSERT INTO group_members VALUES (?, ?, ?, 3, ?, ?)
                   ON CONFLICT(event_id) DO UPDATE SET priority=3, spoken_text=excluded.spoken_text,
                   sender=excluded.sender""",
                (row["id"], row["id"], rule.caller, rule.spoken_text, row["received_at"]),
            )

    def reconcile_findmy_separation(self, connection):
        """Apply the user's low-priority preference to evidenced, unclaimed alerts."""
        rows = connection.execute(
            """SELECT id, input_json FROM messages WHERE lower(app)='com.apple.findmy'
               AND NOT sealed AND status IN ('pending', 'ready', 'failed')
               AND (SELECT COUNT(*) FROM group_members WHERE group_id=messages.id) <= 1"""
        ).fetchall()
        for row in rows:
            notification = None
            try:
                if row["input_json"]:
                    notification = NotificationInput.model_validate_json(row["input_json"])
                else:
                    history = connection.execute(
                        "SELECT record_json FROM ingress_history WHERE event_id=? ORDER BY sequence DESC LIMIT 1",
                        (row["id"],),
                    ).fetchone()
                    payload = json.loads(history[0]).get("payload") if history else None
                    if isinstance(payload, dict):
                        notification = parse_esp_json(
                            json.dumps(payload), timezone_name=self.settings.esp_timezone,
                        )
            except ValueError:
                pass
            rule = device_rule(notification) if notification else None
            if rule is not None and rule.kind == "findmy_separation":
                connection.execute("UPDATE ingress_history SET priority=2 WHERE event_id=?", (row["id"],))
                self.complete(connection, row["id"], "discarded")

    def coalesce_calls(self, connection):
        """Replace an unclaimed incoming call with its unambiguous missed update.

        The five-field ESP contract has no call ID. Require the same known caller,
        ordered source timestamps within two minutes, and nearby arrival times.
        Never merge two different calls, already sealed audio, or ambiguous pairs.
        """
        rows = connection.execute(
            """SELECT * FROM messages WHERE NOT sealed AND status IN ('pending', 'ready')
               AND group_key LIKE '["phone-call", %'
               AND (SELECT COUNT(*) FROM group_members WHERE group_id=messages.id)=1"""
        ).fetchall()
        incoming = [row for row in rows if json.loads(row["group_key"])[1] == "incoming"]
        missed = [row for row in rows if json.loads(row["group_key"])[1] == "missed"]

        def matches(first, last):
            return (json.loads(first["group_key"])[2] == json.loads(last["group_key"])[2]
                    and 0 <= last["received_at"] - first["received_at"] <= 120
                    and abs(last["created_at"] - first["created_at"]) <= 120)

        for last in missed:
            candidates = [first for first in incoming if matches(first, last)]
            if len(candidates) != 1:
                continue
            first = candidates[0]
            if sum(matches(first, candidate) for candidate in missed) != 1:
                continue
            connection.execute(
                """UPDATE messages SET status='pending', spoken_text=?, group_key=?,
                   needs_summary=0, reserved_operations=0, not_before=0, error=NULL WHERE id=?""",
                (last["spoken_text"], last["group_key"], first["id"]),
            )
            connection.execute("UPDATE group_members SET group_id=? WHERE group_id=?",
                               (first["id"], last["id"]))
            connection.execute("DELETE FROM messages WHERE id=?", (last["id"],))
            # Both old WAVs are now unclaimable; only fresh missed-call speech is served.
            for message_id in (first["id"], last["id"]):
                with suppress(OSError):
                    self.audio_path(message_id).unlink(missing_ok=True)

    def event_statuses(self, event_ids: list[str]) -> dict[str, str]:
        if not event_ids:
            return {}
        values = ", ".join("(?)" for _ in event_ids)
        with closing(sqlite3.connect(self.path, timeout=SQLITE_TIMEOUT_SECONDS)) as connection:
            return dict(
                connection.execute(
                    f"""WITH requested(id) AS (VALUES {values})
                    SELECT requested.id,
                           COALESCE(standalone.status, grouped.status, completed.status, 'unavailable')
                    FROM requested
                    LEFT JOIN messages AS standalone ON standalone.id = requested.id
                    LEFT JOIN group_members AS member ON member.event_id = requested.id
                    LEFT JOIN messages AS grouped ON grouped.id = member.group_id
                    LEFT JOIN completed_events AS completed ON completed.id = requested.id""",
                    event_ids,
                )
            )

    def record_ingress(self, entry: dict):
        """Persist sanitized wire data independently from the delivery queue."""
        event_id = entry.get("event_id")
        with self.transaction() as connection:
            priority = connection.execute(
                """SELECT priority FROM group_members WHERE event_id = ?
                   UNION ALL SELECT priority FROM messages WHERE id = ?
                   UNION ALL SELECT priority FROM ingress_history
                       WHERE event_id = ? AND priority IS NOT NULL LIMIT 1""",
                (event_id, event_id, event_id),
            ).fetchone()
            connection.execute(
                """INSERT INTO ingress_history
                   (id, event_id, record_json, priority, queue_status, finished)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET event_id = excluded.event_id,
                       record_json = excluded.record_json, finished = excluded.finished,
                       priority = COALESCE(ingress_history.priority, excluded.priority),
                       queue_status = COALESCE(ingress_history.queue_status, excluded.queue_status)""",
                (
                    str(entry["id"]),
                    event_id,
                    json.dumps(entry, default=str),
                    priority[0] if priority else None,
                    entry.get("queue_status"),
                    int("status_code" in entry),
                ),
            )
            connection.execute(
                """DELETE FROM ingress_history WHERE sequence NOT IN
                   (SELECT sequence FROM ingress_history ORDER BY sequence DESC LIMIT ?)""",
                (REQUEST_HISTORY_LIMIT,),
            )

    def prune_ingress_payloads(self, force: bool = False):
        now = time.time()
        if not force and now - self._last_payload_prune < 30:
            return
        with self.transaction() as connection:
            connection.execute(
                """UPDATE ingress_history SET record_json = json_set(
                    record_json, '$.payload', NULL, '$.payload_expired', json('true'))
                   WHERE json_extract(record_json, '$.payload') IS NOT NULL
                     AND julianday(json_extract(record_json, '$.received_at'))
                         <= julianday(?, 'unixepoch')""",
                (now - REQUEST_PAYLOAD_SECONDS,),
            )
        self._last_payload_prune = now

    def ingress_history(self, limit: int = 100, before: int | None = None) -> dict:
        self.prune_ingress_payloads(force=True)
        with closing(sqlite3.connect(self.path, timeout=SQLITE_TIMEOUT_SECONDS)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT h.*, COALESCE(m.status, grouped.status, c.status, h.queue_status) AS current_status,
                          COALESCE(m.error, grouped.error,
                                   CASE WHEN c.status = 'failed' OR h.queue_status = 'failed'
                                        THEN 'content_unavailable' END) AS processing_error
                   FROM ingress_history h
                   LEFT JOIN messages m ON m.id = h.event_id
                   LEFT JOIN group_members member ON member.event_id = h.event_id
                   LEFT JOIN messages grouped ON grouped.id = member.group_id
                   LEFT JOIN completed_events c ON c.id = h.event_id
                   WHERE h.finished = 1 AND (? IS NULL OR h.sequence < ?)
                   ORDER BY h.sequence DESC LIMIT ?""",
                (before, before, limit + 1),
            ).fetchall()
            total = connection.execute(
                "SELECT COUNT(*) FROM ingress_history WHERE finished = 1"
            ).fetchone()[0]
        entries = []
        for row in rows[:limit]:
            entry = json.loads(row["record_json"])
            entry["app_label"] = request_app_label(entry["app"]) if entry.get("app") else None
            entry["sequence"] = row["sequence"]
            entry["priority"] = row["priority"]
            entry["error"] = ERROR_MESSAGES.get(row["processing_error"])
            status = row["current_status"]
            entry["queue_status"] = "pending" if status == "processing" else status
            entries.append(entry)
        return {
            "entries": entries,
            "total": total,
            "next_cursor": rows[limit - 1]["sequence"] if len(rows) > limit else None,
        }

    def reserve_job(self) -> sqlite3.Row | None:
        self.prune_ingress_payloads()
        self.cleanup_played_audio()
        with self.transaction() as connection:
            now = time.time()
            self.expire_leases(connection, now)
            self.coalesce_calls(connection)
            self.coalesce_unclaimed_groups(connection)
            remaining = self.settings.max_provider_calls - self.provider_calls(connection)
            if remaining <= 0:
                connection.execute(
                    """UPDATE messages SET status = 'failed', error = 'provider_budget',
                       reserved_operations = 0 WHERE status = 'pending'"""
                )
                return None
            unreserved = remaining - self.reserved_operations(connection)
            streak = connection.execute(
                "SELECT value FROM counters WHERE name = 'classification_streak'"
            ).fetchone()[0]
            row = connection.execute(
                """SELECT *, CASE
                     WHEN priority IS NULL THEN 'classification'
                     WHEN needs_summary THEN 'summary'
                     ELSE 'speech'
                   END AS job_type
                   FROM messages AS job WHERE status = 'pending' AND not_before <= ?
                     AND (reserved_operations > 0 OR ? > 0)
                     AND (priority IS NULL OR NOT (
                         priority BETWEEN 3 AND 4 AND NOT sealed AND group_key IS NOT NULL
                         AND ? > 0 AND created_at + ? > ?
                         AND (SELECT COUNT(*) FROM group_members WHERE group_id = job.id) < ?
                         AND EXISTS (
                             SELECT 1 FROM messages AS candidate
                             WHERE candidate.group_key = job.group_key AND candidate.priority IS NULL
                               AND candidate.status IN ('pending', 'processing')
                               AND candidate.created_at BETWEEN job.created_at AND job.created_at + ?
                         )
                     ))
                   ORDER BY CASE
                     WHEN priority = 5 THEN 0
                     WHEN priority IS NOT NULL AND ? THEN 1
                     WHEN priority IS NULL THEN 2
                     ELSE 3
                   END, priority DESC, created_at, rowid LIMIT 1""",
                (
                    now,
                    unreserved,
                    unreserved,
                    self.settings.grouping_window_seconds,
                    now,
                    self.settings.max_group_notifications,
                    self.settings.grouping_window_seconds,
                    streak >= CLASSIFICATION_BURST,
                ),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE counters SET value = value + 1 WHERE name = 'provider_calls'"
            )
            connection.execute(
                "UPDATE counters SET value = ? WHERE name = 'classification_streak'",
                (min(streak + 1, CLASSIFICATION_BURST) if row["priority"] is None else 0,),
            )
            connection.execute(
                """UPDATE messages SET status = 'processing',
                   reserved_operations = MAX(0, reserved_operations - 1) WHERE id = ?""",
                (row["id"],),
            )
            return row

    def reserve_classification_batch(self, message_id: str, limit: int = 10) -> list[dict]:
        """Extend an already charged classification reservation with matching pending rows."""
        with self.transaction() as connection:
            first = connection.execute(
                """SELECT id, input_json, group_key, created_at FROM messages
                   WHERE id = ? AND status = 'processing' AND priority IS NULL""",
                (message_id,),
            ).fetchone()
            if first is None:
                return []
            batch = [{"id": first["id"], "input_json": first["input_json"]}]
            window = self.settings.grouping_window_seconds
            additional = min(limit, CLASSIFICATION_BATCH_LIMIT) - 1
            if first["group_key"] is None or not window or additional < 1:
                return batch
            peers = connection.execute(
                """SELECT id, input_json FROM messages
                   WHERE group_key = ? AND status = 'pending' AND priority IS NULL
                     AND created_at BETWEEN ? AND ?
                   ORDER BY created_at, rowid LIMIT ?""",
                (
                    first["group_key"],
                    first["created_at"] - window,
                    first["created_at"] + window,
                    additional,
                ),
            ).fetchall()
            connection.executemany(
                "UPDATE messages SET status = 'processing' WHERE id = ?",
                [(row["id"],) for row in peers],
            )
            batch.extend(dict(row) for row in peers)
            return batch

    def finish_classification(
        self, message_id: str, result: ClassificationResult, summary_text: str | None = None
    ):
        replaced_audio = None
        with self.transaction() as connection:
            connection.execute(
                "UPDATE ingress_history SET priority = ? WHERE event_id = ?",
                (result.priority, message_id),
            )
            if result.evidence == "insufficient":
                self.complete(connection, message_id, "failed")
                return
            if result.priority <= 2:
                self.complete(connection, message_id, "discarded")
                return
            raw = connection.execute(
                "SELECT input_json, created_at, group_key FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
            notification = NotificationInput.model_validate_json(raw["input_json"])
            key = raw["group_key"]
            target = self.find_open_group(connection, key)
            conversation_name = (notification.conversation_name or "").strip() or None
            if target:
                group_id = target["id"]
                priority = max(target["priority"], result.priority)
                delay_until = self.group_delay_until(key, priority)
                connection.execute(
                    """UPDATE messages SET status = 'pending', priority = ?, spoken_text = NULL,
                       conversation_name = COALESCE(?, conversation_name), needs_summary = 1,
                       reserved_operations = CASE
                           WHEN status = 'ready' OR reserved_operations > 0 THEN 2 ELSE 0 END,
                       not_before = ?, error = NULL WHERE id = ?""",
                    (priority, conversation_name, delay_until, group_id),
                )
                connection.execute("DELETE FROM messages WHERE id = ?", (message_id,))
                replaced_audio = self.audio_path(group_id)
            else:
                group_id = message_id
                connection.execute(
                    """UPDATE messages SET status = 'pending', input_json = NULL, priority = ?,
                       spoken_text = ?, group_key = ?, conversation_name = ?,
                       not_before = ?, error = NULL WHERE id = ?""",
                    (
                        result.priority,
                        result.spoken_text,
                        key,
                        conversation_name,
                        self.group_delay_until(key, result.priority),
                        group_id,
                    ),
                )
            connection.execute(
                "INSERT INTO group_members VALUES (?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    group_id,
                    notification.sender,
                    result.priority,
                    summary_text if summary_text is not None else result.spoken_text,
                    notification.received_at.timestamp(),
                ),
            )
        if replaced_audio is not None:
            # The transaction makes the previous audio unclaimable before touching the filesystem.
            with suppress(OSError):
                replaced_audio.unlink(missing_ok=True)

    def group_delay_until(self, key: str | None, priority: int) -> float:
        if key is None or priority == 5 or not self.settings.grouping_window_seconds:
            return 0
        return time.time() + self.settings.grouping_delay_seconds

    def find_open_group(
        self, connection: sqlite3.Connection, key: str | None
    ) -> sqlite3.Row | None:
        if key is None or not self.settings.grouping_window_seconds:
            return None
        unreserved = (
            self.settings.max_provider_calls
            - self.provider_calls(connection)
            - self.reserved_operations(connection)
        )
        return connection.execute(
            """SELECT id, priority FROM messages
               WHERE group_key = ? AND priority >= 3 AND NOT sealed AND status IN ('pending', 'ready')
                 AND ((status = 'pending' AND reserved_operations = 0)
                      OR reserved_operations + ? >= 2)
                 AND (SELECT COUNT(*) FROM group_members WHERE group_id = messages.id) < ?
               ORDER BY created_at, rowid LIMIT 1""",
            (
                key,
                unreserved,
                self.settings.max_group_notifications,
            ),
        ).fetchone()

    def coalesce_unclaimed_groups(self, connection):
        """Consolidate old queue fragments and arrivals during summary/TTS work.

        Processing and sealed groups are immutable. Finish callbacks retry this
        once provider work completes, before the old WAV becomes claimable.
        Phone-event correlation and the Snapchat allowlist use separate rules.
        """
        if not self.settings.grouping_window_seconds:
            return
        while True:
            rows = connection.execute(
                """SELECT *, (SELECT COUNT(*) FROM group_members WHERE group_id=messages.id) AS members
                   FROM messages WHERE priority >= 3 AND NOT sealed
                   AND status IN ('pending', 'ready') AND group_key IS NOT NULL
                   ORDER BY created_at, rowid"""
            ).fetchall()
            candidates = []
            for row in rows:
                key = json.loads(row["group_key"])
                if len(key) == 3 and key[1] in {"conversation", "sender_id", "sender"}:
                    candidates.append(row)
            unreserved = (self.settings.max_provider_calls - self.provider_calls(connection)
                          - self.reserved_operations(connection))
            pair = next((
                (first, last)
                for index, last in enumerate(candidates)
                for first in candidates[:index]
                if first["group_key"] == last["group_key"]
                and first["members"] > 0 and last["members"] > 0
                and first["members"] + last["members"] <= self.settings.max_group_notifications
                and unreserved + first["reserved_operations"] + last["reserved_operations"] >= 2
            ), None)
            if pair is None:
                return
            first, last = pair
            priority = max(first["priority"], last["priority"])
            connection.execute(
                """UPDATE messages SET status='pending', priority=?, spoken_text=NULL,
                   needs_summary=1, reserved_operations=2, not_before=?, error=NULL,
                   conversation_name=COALESCE(conversation_name, ?) WHERE id=?""",
                (priority, self.group_delay_until(first["group_key"], priority),
                 last["conversation_name"], first["id"]),
            )
            connection.execute("UPDATE group_members SET group_id=? WHERE group_id=?",
                               (first["id"], last["id"]))
            connection.execute("DELETE FROM messages WHERE id=?", (last["id"],))
            # The transaction blocks claims until both obsolete WAVs are invalidated.
            for message_id in (first["id"], last["id"]):
                with suppress(OSError):
                    self.audio_path(message_id).unlink(missing_ok=True)

    def finish_summary(self, message_id: str, spoken_text: str):
        with self.transaction() as connection:
            connection.execute(
                """UPDATE messages SET status = 'pending', spoken_text = ?, needs_summary = 0,
                   error = NULL WHERE id = ?""",
                (spoken_text, message_id),
            )
            self.coalesce_unclaimed_groups(connection)

    def group_for_summary(self, message_id: str) -> NotificationGroup:
        with self.transaction() as connection:
            group = connection.execute(
                "SELECT app, sender, conversation_name FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
            members = connection.execute(
                """SELECT event_id, sender, priority, spoken_text, received_at FROM group_members
                   WHERE group_id = ? ORDER BY received_at, rowid""",
                (message_id,),
            ).fetchall()
            return NotificationGroup(
                app=group["app"],
                sender=group["conversation_name"] or group["sender"],
                conversation_name=group["conversation_name"],
                members=[
                    {**dict(member), "received_at": utc_iso(member["received_at"])}
                    for member in members
                ],
            )

    def finish_speech(self, message_id: str):
        with self.transaction() as connection:
            connection.execute(
                "UPDATE messages SET status = 'ready', error = NULL WHERE id = ?", (message_id,)
            )
            self.coalesce_unclaimed_groups(connection)

    def fail_job(self, message_id: str, error: str):
        with self.transaction() as connection:
            connection.execute(
                """UPDATE messages SET status = 'failed', error = ?, reserved_operations = 0
                   WHERE id = ?""",
                (error, message_id),
            )

    def complete(self, connection: sqlite3.Connection, message_id: str, status: str):
        connection.execute(
            """UPDATE ingress_history SET queue_status = ? WHERE event_id = ? OR event_id IN
               (SELECT event_id FROM group_members WHERE group_id = ?)""",
            (status, message_id, message_id),
        )
        if status == "played":
            inserted = connection.execute(
                """INSERT INTO completed_events
                   SELECT event_id, 'played' FROM group_members WHERE group_id = ?""",
                (message_id,),
            ).rowcount
        else:
            connection.execute("INSERT INTO completed_events VALUES (?, ?)", (message_id, status))
            inserted = 1
        connection.execute(
            "UPDATE counters SET value = value + ? WHERE name = ?", (inserted, status)
        )
        self.record_history(connection, "completed_events", inserted)
        connection.execute("DELETE FROM messages WHERE id = ?", (message_id,))

    def release_lease(
        self, connection: sqlite3.Connection, lease: sqlite3.Row, outcome: str
    ) -> str:
        connection.execute("DELETE FROM delivery_leases WHERE id = ?", (lease["id"],))
        message_id = lease["message_id"]
        if outcome == "played":
            self.complete(connection, message_id, "played")
            connection.execute("INSERT INTO audio_cleanup VALUES (?, ?)", (message_id, lease["id"]))
            status = "played"
        elif outcome == "audio_missing":
            status = "failed"
            connection.execute(
                "UPDATE messages SET status = 'failed', error = 'audio_missing' WHERE id = ?",
                (message_id,),
            )
        else:
            exhausted = lease["attempt"] >= self.settings.max_delivery_attempts
            status = "failed" if exhausted else "ready"
            connection.execute(
                "UPDATE messages SET status = ?, error = ? WHERE id = ?",
                (status, "delivery_exhausted" if exhausted else None, message_id),
            )
        connection.execute(
            "INSERT INTO delivery_receipts VALUES (?, ?, ?, ?)",
            (lease["id"], lease["device_id"], outcome, status),
        )
        self.record_history(connection, "delivery_receipts", 1)
        return status

    def expire_leases(self, connection: sqlite3.Connection, now: float):
        expired = connection.execute(
            """SELECT delivery_leases.*, messages.attempt FROM delivery_leases
               JOIN messages ON messages.id = delivery_leases.message_id
               WHERE expires_at <= ?""",
            (now,),
        ).fetchall()
        for lease in expired:
            self.release_lease(connection, lease, "expired")

    @staticmethod
    def active_lease(connection: sqlite3.Connection, lease_id: str) -> sqlite3.Row | None:
        return connection.execute(
            """SELECT delivery_leases.*, messages.priority, messages.app, messages.sender,
                      messages.spoken_text, messages.attempt, messages.conversation_name,
                      messages.received_at,
                      (SELECT COUNT(*) FROM group_members
                       WHERE group_id = messages.id) AS notification_count
               FROM delivery_leases JOIN messages ON messages.id = delivery_leases.message_id
               WHERE delivery_leases.id = ?""",
            (lease_id,),
        ).fetchone()

    @staticmethod
    def receipt(connection: sqlite3.Connection, lease_id: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM delivery_receipts WHERE id = ?", (lease_id,)
        ).fetchone()

    @staticmethod
    def check_owner(lease: sqlite3.Row | None, device_id: str):
        if lease is not None and lease["device_id"] != device_id:
            raise QueueError(403, "This delivery lease belongs to another device.")

    def require_active(
        self, connection: sqlite3.Connection, lease_id: str, device_id: str, now: float
    ) -> sqlite3.Row:
        lease = self.active_lease(connection, lease_id)
        self.check_owner(lease or self.receipt(connection, lease_id), device_id)
        if lease is None or lease["expires_at"] <= now:
            raise QueueError(409, "This delivery lease is no longer active.")
        return lease

    @staticmethod
    def delivery_view(row: sqlite3.Row) -> dict:
        return {
            "lease_id": row["id"],
            "message_id": row["message_id"],
            "device_id": row["device_id"],
            "priority": row["priority"],
            "app": row["app"],
            "sender": row["sender"],
            "conversation_name": row["conversation_name"],
            "notification_count": row["notification_count"],
            "spoken_text": row["spoken_text"],
            "audio_url": f"/api/delivery/{row['id']}/audio?device_id={row['device_id']}",
            "expires_at": utc_iso(row["expires_at"]),
            "received_at": utc_iso(row["received_at"]),
            "attempt": row["attempt"],
        }

    def claim(self, device_id: str, expected_message_id: str | None = None) -> dict | None:
        with self.transaction() as connection:
            now = time.time()
            self.expire_leases(connection, now)
            existing = connection.execute(
                "SELECT id FROM delivery_leases WHERE device_id = ?", (device_id,)
            ).fetchone()
            if existing:
                active = self.active_lease(connection, existing["id"])
                if expected_message_id is not None and active["message_id"] != expected_message_id:
                    raise QueueError(409, "Another notification is already in flight.")
                return self.delivery_view(active)
            waiting = connection.execute(
                """SELECT id, status FROM messages
                   WHERE status IN ('pending', 'processing', 'ready')
                   ORDER BY priority DESC, received_at, created_at, rowid"""
            ).fetchall()
            for row in waiting:
                # Preserve priority-first ordering and FIFO within each tier even if
                # another WAV finishes first. Unclassified items have no tier yet.
                if row["status"] != "ready":
                    return None
                message_id = row["id"]
                if expected_message_id is not None and message_id != expected_message_id:
                    raise QueueError(409, "The queue changed. Refresh status before downloading.")
                if self.available_audio(message_id) is None:
                    connection.execute(
                        "UPDATE messages SET status = 'failed', error = 'audio_missing' WHERE id = ?",
                        (message_id,),
                    )
                    if expected_message_id is not None:
                        return None
                    continue
                lease_id = str(uuid4())
                connection.execute(
                    "INSERT INTO delivery_leases VALUES (?, ?, ?, ?)",
                    (lease_id, message_id, device_id, now + self.settings.lease_seconds),
                )
                connection.execute(
                    """UPDATE messages SET status = 'leased', sealed = 1, attempt = attempt + 1
                       WHERE id = ?""",
                    (message_id,),
                )
                return self.delivery_view(self.active_lease(connection, lease_id))
            return None

    def heartbeat(self, lease_id: str, device_id: str) -> dict:
        with self.transaction() as connection:
            now = time.time()
            self.require_active(connection, lease_id, device_id, now)
            connection.execute(
                "UPDATE delivery_leases SET expires_at = ? WHERE id = ?",
                (now + self.settings.lease_seconds, lease_id),
            )
            return self.delivery_view(self.active_lease(connection, lease_id))

    def authorize_audio(self, lease_id: str, device_id: str) -> Path:
        with self.transaction() as connection:
            lease = self.require_active(connection, lease_id, device_id, time.time())
            path = self.available_audio(lease["message_id"])
            if path is not None:
                return path
            self.release_lease(connection, lease, "audio_missing")
        raise QueueError(409, ERROR_MESSAGES["audio_missing"])

    def acknowledge(self, lease_id: str, device_id: str, outcome: str) -> str:
        with self.transaction() as connection:
            receipt = self.receipt(connection, lease_id)
            if receipt:
                self.check_owner(receipt, device_id)
                if receipt["outcome"] != outcome:
                    raise QueueError(409, "This lease already ended with a different outcome.")
                status = receipt["status"]
            else:
                lease = self.require_active(connection, lease_id, device_id, time.time())
                status = self.release_lease(connection, lease, outcome)
        if status == "played":
            self.cleanup_played_audio(lease_id)
        return status

    def cleanup_played_audio(self, lease_id: str | None = None):
        failed = False
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT message_id FROM audio_cleanup WHERE ? IS NULL OR lease_id = ?",
                (lease_id, lease_id),
            ).fetchall()
            for row in rows:
                message_id = row["message_id"]
                try:
                    self.audio_path(message_id).unlink(missing_ok=True)
                except OSError:
                    failed = True
                    continue
                connection.execute("DELETE FROM audio_cleanup WHERE message_id = ?", (message_id,))
        if failed and lease_id is not None:
            raise QueueError(503, "The played audio file could not be removed yet.")

    def retry(self, message_id: str) -> str:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT status, error FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
            if row is None:
                raise QueueError(404, "This message is unavailable.")
            if row["status"] != "failed":
                raise QueueError(409, "Only failed messages can be retried.")
            keep_audio = row["error"] == "delivery_exhausted" and (
                self.available_audio(message_id) is not None
            )
            if (
                not keep_audio
                and self.provider_calls(connection) >= self.settings.max_provider_calls
            ):
                raise QueueError(409, ERROR_MESSAGES["provider_budget"])
            status = "ready" if keep_audio else "pending"
            connection.execute(
                "UPDATE messages SET status = ?, error = NULL, attempt = 0 WHERE id = ?",
                (status, message_id),
            )
            return status

    @staticmethod
    def provider_calls(connection: sqlite3.Connection) -> int:
        return connection.execute(
            "SELECT value FROM counters WHERE name = 'provider_calls'"
        ).fetchone()[0]

    @staticmethod
    def reserved_operations(connection: sqlite3.Connection) -> int:
        return connection.execute(
            "SELECT COALESCE(SUM(reserved_operations), 0) FROM messages"
        ).fetchone()[0]

    def snapshot(self) -> dict:
        with self.transaction() as connection:
            self.expire_leases(connection, time.time())
            counts = dict.fromkeys(
                ("pending", "ready", "leased", "played", "discarded", "failed"), 0
            )
            for row in connection.execute(
                """SELECT status, COUNT(*) FROM messages GROUP BY status
                   UNION ALL SELECT name, value FROM counters WHERE name IN ('played', 'discarded')"""
            ):
                counts["pending" if row["status"] == "processing" else row["status"]] += row[1]
            items = [
                {
                    "id": row["id"],
                    "app": row["app"],
                    "sender": row["sender"],
                    "conversation_name": row["conversation_name"],
                    "notification_count": row["notification_count"],
                    "priority": row["priority"],
                    "status": "pending" if row["status"] == "processing" else row["status"],
                    "spoken_text": row["spoken_text"],
                    "error": ERROR_MESSAGES.get(row["error"]),
                    "created_at": utc_iso(row["created_at"]),
                    "received_at": utc_iso(row["received_at"]),
                }
                for row in connection.execute(
                    """SELECT *, MAX(1, (SELECT COUNT(*) FROM group_members
                                         WHERE group_id = messages.id)) AS notification_count
                       FROM messages
                       ORDER BY priority DESC, received_at, created_at, rowid LIMIT ?""",
                    (STATE_LIMIT,),
                )
            ]
            alerts = [
                {"id": row["id"], "priority": 5, "created_at": utc_iso(row["created_at"])}
                for row in connection.execute(
                    """SELECT id, created_at FROM messages WHERE priority = 5
                       ORDER BY created_at DESC, rowid DESC LIMIT ?""",
                    (STATE_LIMIT,),
                )
            ]
            return {
                "counts": counts,
                "items": items,
                "alerts": alerts,
                "limits": {
                    "provider_calls": self.provider_calls(connection),
                    "max_provider_calls": self.settings.max_provider_calls,
                },
                "active_delivery": None,
            }
