import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from contracts import ClassificationResult, NotificationInput, Settings
from contracts.app_names import APP_NAMES, display_app_name
from intelligence.formatting import format_notification_for_speech
from server.store import QueueStore


def test_history_payload_expires_but_priority_and_metadata_remain(tmp_path):
    store = QueueStore(Settings(_env_file=None, data_dir=tmp_path, max_provider_calls=0))
    store.initialize()
    now = datetime.now(timezone.utc)
    for age, body in (
        (timedelta(hours=2, seconds=1), "expired-private-text"),
        (timedelta(minutes=119), "recent-text"),
    ):
        store.record_ingress(
            {
                "id": str(uuid4()),
                "received_at": now - age,
                "method": "POST",
                "path": "/api/esp/notifications",
                "status_code": 202,
                "duration_ms": 1,
                "event_id": str(uuid4()),
                "queue_status": "played",
                "payload": {"message": body},
            }
        )
    with store.transaction() as db:
        db.execute("UPDATE ingress_history SET priority=4")
    history = store.ingress_history()
    assert len(history["entries"]) == 2
    newer, older = history["entries"]
    assert older["payload"] is None and older["payload_expired"]
    assert older["priority"] == 4 and older["queue_status"] == "played"
    assert newer["payload"] == {"message": "recent-text"}
    with sqlite3.connect(store.path) as db:
        assert "expired-private-text" not in str(
            db.execute("SELECT record_json FROM ingress_history").fetchall()
        )
    assert b"expired-private-text" not in store.path.read_bytes()
    restarted = QueueStore(store.settings)
    restarted.initialize()
    assert restarted.ingress_history()["entries"][1]["payload"] is None


def test_verified_app_names_change_speech_not_wire_data():
    assert len(APP_NAMES) >= 90
    assert display_app_name("com.apple.mobilephone") == "Phone"
    assert display_app_name("COM.APPLE.MOBILEPHONE") == "Phone"
    assert display_app_name("net.whatsapp.WhatsApp") == "WhatsApp"
    assert display_app_name("com.microsoft.skype.teams") == "Microsoft Teams"
    assert display_app_name("com.unknown.example") == "com.unknown.example"
    notification = NotificationInput(app="com.apple.mobilephone", body="Missed call from Sam")
    result = ClassificationResult(
        priority=4, reason="Call", spoken_text="Call", evidence="sufficient", deadline_at=None
    )
    speech = format_notification_for_speech(notification, result).spoken_text
    assert "on Phone" in speech and "com.apple.mobilephone" not in speech
    assert notification.app == "com.apple.mobilephone"


def test_usage_cap_defaults_to_5000():
    assert Settings(_env_file=None).max_provider_calls == 5000
