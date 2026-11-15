"""User preference: routine device separation is passive, not urgent playback."""

import json
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from contracts import ClassificationResult, Settings
from contracts.esp import parse_esp_json
from intelligence.notification_rules import device_rule
from server.store import QueueStore

PACKET = {
    "app": "com.apple.findmy",
    "title": "2 devices were left behind",
    "subtitle": "",
    "message": "These devices are no longer detected near you. They were last seen near Campus.",
    "date": "20261114T190645",
}


def incoming(packet=None):
    return parse_esp_json(json.dumps(packet or PACKET), timezone_name="America/Los_Angeles")


def test_findmy_separation_is_p2_without_classification_or_tts(tmp_path):
    store = QueueStore(Settings(_env_file=None, data_dir=tmp_path))
    store.initialize()
    rule = device_rule(incoming())
    assert rule.priority == 2 and rule.kind == "findmy_separation"
    assert store.enqueue(incoming()) == "discarded"
    assert store.enqueue(incoming()) == "discarded"
    assert store.reserve_job() is None
    assert store.snapshot()["items"] == []
    assert store.snapshot()["limits"]["provider_calls"] == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "title": "AirTag Found Moving With You",
            "message": "An unknown AirTag has been detected moving with you.",
        },
        {"title": "Lost device found", "message": "Your lost device was found."},
        {"message": PACKET["message"] + " Someone is following me!"},
        {"subtitle": "Unknown accessory detected"},
        {"app": "com.apple.MobileSMS"},
    ],
)
def test_other_alerts_remain_eligible_for_normal_classification(overrides):
    assert device_rule(incoming(PACKET | overrides)) is None


def test_hidden_findmy_alert_is_not_assumed_routine():
    hidden = incoming().model_copy(update={"content_hidden": True})
    assert device_rule(hidden) is None


@pytest.mark.parametrize("sealed", [False, True])
def test_restart_reconciles_existing_ready_alert_but_not_frozen_playback(tmp_path, sealed):
    store = QueueStore(Settings(_env_file=None, data_dir=tmp_path))
    store.initialize()
    event = incoming()
    event_id = str(event.event_id)
    store.record_ingress(
        {
            "id": str(uuid4()),
            "received_at": datetime.now(timezone.utc),
            "method": "POST",
            "path": "/api/esp/notifications",
            "status_code": 202,
            "duration_ms": 1,
            "event_id": event_id,
            "app": event.app,
            "payload": PACKET,
        }
    )
    with patch("server.store.device_rule", return_value=None):
        store.enqueue(event)
    with store.transaction() as db:
        db.execute("UPDATE messages SET status='processing' WHERE id=?", (event_id,))
    store.finish_classification(
        event_id,
        ClassificationResult(
            priority=4,
            reason="Old classification",
            spoken_text="Old separation alert",
            evidence="sufficient",
            deadline_at=None,
        ),
    )
    audio = store.audio_path(event_id)
    audio.write_bytes(b"old-audio")
    store.finish_speech(event_id)
    if sealed:
        with store.transaction() as db:
            db.execute("UPDATE messages SET sealed=1 WHERE id=?", (event_id,))
    store.initialize()
    history = store.ingress_history()["entries"][0]
    if sealed:
        assert store.snapshot()["items"][0]["id"] == event_id
        assert audio.exists()
        assert history["priority"] == 4
    else:
        assert store.snapshot()["items"] == []
        assert not audio.exists()
        assert history["priority"] == 2 and history["queue_status"] == "discarded"
    assert history["payload"] == PACKET
    store.initialize()  # Idempotent on subsequent restarts.
