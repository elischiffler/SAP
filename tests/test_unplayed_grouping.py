import sqlite3
import wave
from datetime import datetime, timedelta, timezone

from contracts import ClassificationResult, NotificationInput, Settings
from server.pi import PiDelivery
from server.store import QueueStore


def make_store(tmp_path, **settings):
    store = QueueStore(Settings(_env_file=None, data_dir=tmp_path, grouping_delay_seconds=0, **settings))
    store.initialize()
    return store


def add(store, index, *, conversation="chat", priority=3, app="Messages"):
    item = NotificationInput(app=app, sender=f"Person {index % 2}",
                             conversation_id=conversation, conversation_name="Shared chat",
                             body=f"Message {index}",
                             received_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=index))
    store.enqueue(item)
    with store.transaction() as db:
        db.execute("UPDATE messages SET status='processing', created_at=? WHERE id=?",
                   (1000 + index * 3600, str(item.event_id)))
    store.finish_classification(str(item.event_id), ClassificationResult(
        priority=priority, reason="Offline test", spoken_text=item.body,
        evidence="sufficient", deadline_at=None,
    ))
    return str(item.event_id)


def ready(store, message_id):
    with wave.open(str(store.audio_path(message_id)), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 80)
    store.finish_speech(message_id)


def test_hours_apart_join_same_conversation_until_fifty(tmp_path):
    store = make_store(tmp_path)
    ids = [add(store, i, priority=5 if i == 49 else 3) for i in range(51)]
    items = store.snapshot()["items"]
    assert sorted(item["notification_count"] for item in items) == [1, 50]
    group = next(item for item in items if item["notification_count"] == 50)
    assert group["id"] == ids[0] and group["priority"] == 5
    assert group["received_at"] == "2026-01-01T00:00:00+00:00"
    assert len(store.group_for_summary(ids[0]).members) == 50
    assert store.event_statuses(ids) == dict.fromkeys(ids, "pending")


def test_restart_combines_existing_fragments_preserving_members_and_identity(tmp_path):
    old = make_store(tmp_path, grouping_window_seconds=0)
    first, second, third = [add(old, i) for i in range(3)]
    other_chat = add(old, 3, conversation="other")
    other_app = add(old, 4, app="Other app")
    for item in (first, second, third, other_chat, other_app):
        ready(old, item)
    current = make_store(tmp_path)
    items = current.snapshot()["items"]
    assert len(items) == 3
    merged = next(item for item in items if item["id"] == first)
    assert merged["notification_count"] == 3 and merged["spoken_text"] is None
    assert merged["status"] == "pending"
    assert not any(current.audio_path(i).exists() for i in (first, second, third))
    assert current.audio_path(other_chat).exists() and current.audio_path(other_app).exists()
    assert {str(member.event_id) for member in current.group_for_summary(first).members} == {first, second, third}
    current.initialize()
    assert len(current.snapshot()["items"]) == 3
    assert current.reserve_job()["job_type"] == "summary"


def test_pi_poll_does_not_seal_but_audio_claim_does_even_after_expiry(tmp_path):
    store = make_store(tmp_path)
    pi = PiDelivery(store)
    pi.initialize()
    first = add(store, 0)
    ready(store, first)
    assert pi.status()["items"][0]["id"] == first
    second = add(store, 1)
    assert store.snapshot()["items"][0]["notification_count"] == 2
    store.finish_summary(first, "Two notifications in this chat.")
    ready(store, first)
    path, lease = pi.begin_audio(first)
    frozen = path.read_bytes()
    third = add(store, 2)
    assert len(store.snapshot()["items"]) == 2
    assert path.read_bytes() == frozen
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE delivery_leases SET expires_at=0 WHERE id=?", (lease,))
    store.initialize()
    fourth = add(store, 3)
    groups = {item["id"]: item["notification_count"] for item in store.snapshot()["items"]}
    assert groups == {first: 2, third: 2}
    assert store.event_statuses([second, fourth]) == {second: "ready", fourth: "pending"}


def test_arrival_during_tts_merges_before_old_audio_can_be_claimed(tmp_path):
    store = make_store(tmp_path)
    first = add(store, 0)
    assert store.reserve_job()["job_type"] == "speech"
    add(store, 1)
    assert len(store.snapshot()["items"]) == 2
    ready(store, first)
    assert len(store.snapshot()["items"]) == 1
    assert not store.audio_path(first).exists()
    assert store.claim("pi-pager") is None
    assert store.reserve_job()["job_type"] == "summary"


def test_legacy_groups_over_fifty_are_not_combined_into_oversized_audio(tmp_path):
    old = make_store(tmp_path, grouping_window_seconds=0)
    for index in range(51):
        add(old, index)
    current = make_store(tmp_path)
    assert sorted(item["notification_count"] for item in current.snapshot()["items"]) == [1, 50]
