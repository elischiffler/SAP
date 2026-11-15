import asyncio
import sqlite3
import wave
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest

from contracts import ClassificationResult, NotificationInput, Settings
from intelligence.notification_rules import device_rule
from server.app import create_app
from server.store import QueueStore

PHONE = "com.apple.mobilephone"
SNAPCHAT = "com.toyopagroup.picaboo"


def call(kind, caller="Riley", when=None):
    return NotificationInput(app=PHONE, title=caller, body=kind,
                             received_at=when or datetime.now(timezone.utc))


def store_at(tmp_path):
    store = QueueStore(Settings(_env_file=None, data_dir=tmp_path))
    store.initialize()
    return store


def rows(store):
    with store.transaction() as db:
        return db.execute("SELECT * FROM messages ORDER BY created_at").fetchall()


@pytest.mark.parametrize("body", ["\u200eBen Paglia is typing...", "Riley is typing…", "Riley is typing", "is typing..."])
def test_snapchat_typing_is_discarded_without_provider_work(tmp_path, body):
    store = store_at(tmp_path)
    notification = NotificationInput(app=SNAPCHAT, title="\u200eSome contact", body=body)
    assert store.enqueue(notification) == "discarded"
    assert store.enqueue(notification) == "discarded"
    assert store.reserve_job() is None
    state = store.snapshot()
    assert state["counts"]["discarded"] == 1
    assert state["limits"]["provider_calls"] == 0


@pytest.mark.parametrize("app,body", [
    (SNAPCHAT, "Riley sent you a Snap"),
    (SNAPCHAT, "Riley is typing... but has not finished the report"),
    (SNAPCHAT, 'Riley said "Ben is typing..."'),
    ("Messages", "Riley is typing..."),
    (PHONE, "Voicemail"),
])
def test_other_content_is_not_mistaken_for_typing(app, body):
    rule = device_rule(NotificationInput(app=app, body=body))
    if app == SNAPCHAT:
        assert rule.kind == "snapchat_other" and rule.priority == 2
    else:
        assert rule is None


def test_phone_speech_uses_title_and_unknown_caller_fallback(tmp_path):
    store = store_at(tmp_path)
    store.enqueue(call("Incoming Call", "\u200eRiley"))
    assert rows(store)[0]["spoken_text"] == "Incoming call from Riley."
    assert rows(store)[0]["sender"] == "Riley"
    assert rows(store)[0]["priority"] == 3
    assert device_rule(call("Missed Call", "")).spoken_text == "Missed call from an unknown caller."


@pytest.mark.parametrize("reverse", [False, True])
def test_incoming_and_missed_become_one_playable_message(tmp_path, reverse):
    store = store_at(tmp_path)
    now = datetime.now(timezone.utc)
    first = call("Incoming Call", when=now)
    last = call("Missed Call", when=now + timedelta(seconds=20))
    for notification in ([last, first] if reverse else [first, last]):
        store.enqueue(notification)
    queued = rows(store)
    assert len(queued) == 1
    assert queued[0]["id"] == str(first.event_id)
    assert queued[0]["spoken_text"] == "Missed call from Riley."
    assert store.event_statuses([str(first.event_id), str(last.event_id)]) == {
        str(first.event_id): "pending", str(last.event_id): "pending",
    }
    job = store.reserve_job()
    assert job["job_type"] == "speech"  # No classifier or group summarizer.
    assert job["spoken_text"] == "Missed call from Riley."
    with wave.open(str(store.audio_path(job["id"])), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 80)
    store.finish_speech(job["id"])
    lease = store.claim("pi-pager")
    assert lease["notification_count"] == 2
    with store.transaction() as db:
        row = store.require_active(db, lease["lease_id"], "pi-pager", datetime.now().timestamp())
        store.release_lease(db, row, "played")
    assert store.enqueue(first) == "played"
    assert store.enqueue(last) == "played"


@pytest.mark.parametrize("scenario", ["other_caller", "old", "unknown", "sealed", "ambiguous"])
def test_unrelated_or_frozen_calls_do_not_merge(tmp_path, scenario):
    store = store_at(tmp_path)
    now = datetime.now(timezone.utc)
    caller = "" if scenario == "unknown" else "Riley"
    first = call("Incoming Call", caller, now)
    store.enqueue(first)
    if scenario == "sealed":
        with store.transaction() as db:
            db.execute("UPDATE messages SET sealed=1")
    if scenario == "ambiguous":
        store.enqueue(call("Incoming Call", caller, now + timedelta(seconds=1)))
    last = call("Missed Call", "Alex" if scenario == "other_caller" else caller,
                now + timedelta(seconds=121 if scenario == "old" else 20))
    store.enqueue(last)
    assert len(rows(store)) == (3 if scenario == "ambiguous" else 2)


def test_call_update_waits_until_speech_finishes_before_replacing_audio(tmp_path):
    store = store_at(tmp_path)
    first = call("Incoming Call")
    store.enqueue(first)
    job = store.reserve_job()
    store.enqueue(call("Missed Call", when=first.received_at + timedelta(seconds=20)))
    assert len(rows(store)) == 2  # Do not mutate in-progress synthesis.
    path = store.audio_path(str(first.event_id))
    path.write_bytes(b"old audio")
    store.finish_speech(job["id"])
    next_job = store.reserve_job()
    assert len(rows(store)) == 1
    assert not path.exists()
    assert next_job["spoken_text"] == "Missed call from Riley."


async def test_esp_rules_record_history_priority_and_skip_classifier(tmp_path):
    class Classifier:
        async def classify(self, notification):
            raise AssertionError("Exact device rules must skip the classifier")

    class Speech:
        async def synthesize(self, text, destination):
            with wave.open(str(destination), "wb") as audio:
                audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\0\0" * 80)
            return destination

    app = create_app(Settings(_env_file=None, data_dir=tmp_path, esp_ingest_token="test" * 8),
                     classifier=Classifier(), speech=Speech())
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost",
    ) as c:
        for application, body, title in [(SNAPCHAT, "\u200eBen is typing...", "Friend"),
                                         (PHONE, "Missed Call", "Riley")]:
            response = await c.post('/api/esp/notifications', headers={"Authorization": "Bearer " + "test" * 8},
                                    json={"app": application, "title": title, "subtitle": "",
                                          "message": body, "date": "20261114T182428"})
            assert response.status_code == 202
        async with asyncio.timeout(3):
            while True:
                state = (await c.get('/api/state')).json()
                if state['counts']['ready'] == 1:
                    break
                await asyncio.sleep(0.01)
        assert state['counts']['discarded'] == 1
        assert state['items'][0]['spoken_text'] == "Missed call from Riley."
        history = (await c.get('/api/ingress-log')).json()['entries']
        assert {e['app']: e['priority'] for e in history} == {SNAPCHAT: 1, PHONE: 3}
        assert state['limits']['provider_calls'] == 1  # TTS only.
    with sqlite3.connect(tmp_path / 'pager.sqlite3') as db:
        assert db.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 1


def test_individual_snapchat_chat_has_exact_speech_and_survives_restart(tmp_path):
    store = store_at(tmp_path)
    notification = NotificationInput(app=SNAPCHAT, title="\u200eEli", body="sent you a chat")
    assert store.enqueue(notification) == "pending"
    assert rows(store)[0]["spoken_text"] == "On Snapchat, Eli sent you a message."
    assert rows(store)[0]["priority"] == 3
    store.initialize()
    assert rows(store)[0]["spoken_text"] == "On Snapchat, Eli sent you a message."
    assert store.reserve_job()["job_type"] == "speech"
    alias = NotificationInput(app="Snapchat", title="Eli", body="sent you a Snap")
    assert device_rule(alias).priority == 2


@pytest.mark.parametrize("fields", [
    {"title": "Eli", "body": "sent you a Snap"},
    {"title": "Eli", "body": "posted a Story"},
    {"title": "Eli", "body": "reacted to a chat"},
    {"title": "Eli", "body": "New Chat from Eli", "subtitle": "Group name"},
    {"title": "Eli", "body": "sent you a chat", "subtitle": "Group name"},
    {"title": "Eli", "body": "sent you a chat", "conversation_name": "Group name"},
    {"title": "Eli", "body": "sent you a chat", "content_hidden": True},
    {"title": "", "body": "sent you a chat"},
    {"title": "Snapchat", "body": "sent you a chat"},
    {"title": "Eli", "body": "Unknown notification: emergency!!!"},
])
def test_non_individual_snapchat_alerts_never_reach_priority_three(tmp_path, fields):
    store = store_at(tmp_path)
    event = NotificationInput(app=SNAPCHAT, **fields)
    assert device_rule(event).priority == 2
    assert store.enqueue(event) == "discarded"
    assert store.reserve_job() is None
    assert not rows(store)


def test_startup_corrects_old_snapchat_queue_without_touching_claimed_audio(tmp_path):
    store = store_at(tmp_path)
    events = []
    for title, body, subtitle, sealed in [
        ("Eli", "sent you a chat", "", False),
        ("Alex", "New Chat from Alex", "Group name", False),
        ("Eli", "is typing...", "", False),
        ("Riley", "New Chat from Riley", "Group name", True),
    ]:
        event = NotificationInput(app=SNAPCHAT, title=title, body=body, subtitle=subtitle)
        event_id = str(event.event_id)
        store.record_ingress({"id": str(uuid4()), "event_id": event_id, "app": SNAPCHAT,
                              "payload": {"app": SNAPCHAT, "title": title, "message": body,
                                          "subtitle": subtitle, "date": "20261114T183313"}})
        with patch('server.store.device_rule', return_value=None):
            store.enqueue(event)
        store.finish_classification(event_id, ClassificationResult(
            priority=3, reason="Legacy", spoken_text="Content unavailable. Check your phone.",
            evidence="sufficient", deadline_at=None,
        ))
        store.audio_path(event_id).write_bytes(b"old audio")
        store.finish_speech(event_id)
        if sealed:
            with store.transaction() as db:
                db.execute("UPDATE messages SET sealed=1 WHERE id=?", (event_id,))
        events.append(event_id)
    store.initialize()
    retained = {row["id"]: row for row in rows(store)}
    assert set(retained) == {events[0], events[3]}
    assert retained[events[0]]["status"] == "pending"
    assert retained[events[0]]["spoken_text"] == "On Snapchat, Eli sent you a message."
    assert retained[events[3]]["spoken_text"] == "Content unavailable. Check your phone."
    assert not store.audio_path(events[0]).exists()
    assert store.audio_path(events[3]).exists()
    assert store.enqueue(NotificationInput(event_id=events[1], app=SNAPCHAT)) == "discarded"
    with store.transaction() as db:
        priorities = dict(db.execute('SELECT event_id, priority FROM ingress_history'))
        assert priorities[events[1]] == 2 and priorities[events[2]] == 1
        db.execute('DELETE FROM ingress_history')
    store.initialize()
    assert len(rows(store)) == 2  # A recognized direct chat does not need retained raw history.
