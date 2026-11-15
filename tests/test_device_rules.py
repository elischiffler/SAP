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


@pytest.mark.parametrize("caller", ["Riley", "+1 (805) 555-0100", "", "No Caller ID"])
def test_incoming_calls_are_discarded_without_speech(tmp_path, caller):
    store = store_at(tmp_path)
    event = call("Incoming Call", caller)
    assert device_rule(event).priority == 2
    assert device_rule(event).spoken_text is None
    assert store.enqueue(event) == "discarded"
    assert store.enqueue(event) == "discarded"
    assert not rows(store)
    assert store.reserve_job() is None
    assert store.snapshot()["limits"]["provider_calls"] == 0


@pytest.mark.parametrize("caller,priority", [
    ("Riley", 4), ("\u200eAidan Freeland", 4), ("妈妈", 4),
    ("+1 (805) 555-0100", 3), ("8055550100", 3),
    ("+44 20 7946 0958 ext. 123", 3), ("", 3),
    ("Unknown Caller", 3), ("No Caller ID", 3), ("Private Number", 3),
    ("Maybe: Riley", 3),
])
def test_missed_call_priority_uses_caller_label(tmp_path, caller, priority):
    store = store_at(tmp_path)
    event = call("Missed Call", caller)
    assert device_rule(event).priority == priority
    assert store.enqueue(event) == "pending"
    assert rows(store)[0]["priority"] == priority
    assert store.reserve_job()["job_type"] == "speech"
    with store.transaction() as db:
        assert db.execute("SELECT priority FROM group_members").fetchone()[0] == priority
    assert device_rule(call("Missed Call", "")).spoken_text == "Missed call from an unknown caller."


@pytest.mark.parametrize("reverse", [False, True])
def test_only_missed_event_survives_incoming_pair(tmp_path, reverse):
    store = store_at(tmp_path)
    now = datetime.now(timezone.utc)
    incoming = call("Incoming Call", when=now)
    missed = call("Missed Call", when=now + timedelta(seconds=20))
    for event in ([missed, incoming] if reverse else [incoming, missed]):
        store.enqueue(event)
    assert len(rows(store)) == 1
    assert rows(store)[0]["id"] == str(missed.event_id)
    assert rows(store)[0]["priority"] == 4
    assert rows(store)[0]["spoken_text"] == "Missed call from Riley."
    assert store.event_statuses([str(incoming.event_id), str(missed.event_id)]) == {
        str(incoming.event_id): "discarded", str(missed.event_id): "pending",
    }


def test_separate_missed_calls_stay_separate(tmp_path):
    store = store_at(tmp_path)
    store.enqueue(call("Missed Call"))
    store.enqueue(call("Missed Call"))
    assert len(rows(store)) == 2


def test_startup_removes_legacy_incoming_and_reprioritizes_missed(tmp_path):
    from intelligence.notification_rules import DeviceRule
    store = store_at(tmp_path)
    events = []
    for kind, caller, sealed in [
        ("Incoming Call", "Riley", False),
        ("Missed Call", "Alex", False),
        ("Missed Call", "+18055550100", False),
        ("Incoming Call", "Sam", True),
    ]:
        event = call(kind, caller)
        legacy = DeviceRule(3, kind.split()[0].lower(), f"{kind} from {caller}.", caller, caller.casefold())
        with patch('server.store.device_rule', return_value=legacy):
            store.enqueue(event)
        path = store.audio_path(str(event.event_id))
        path.write_bytes(b"legacy audio")
        with store.transaction() as db:
            db.execute("UPDATE messages SET status='ready', sealed=? WHERE id=?", (sealed, str(event.event_id)))
        events.append(str(event.event_id))
    store.initialize()
    retained = {row["id"]: row for row in rows(store)}
    assert events[0] not in retained
    assert not store.audio_path(events[0]).exists()
    assert retained[events[1]]["priority"] == 4
    assert retained[events[2]]["priority"] == 3
    assert retained[events[3]]["priority"] == 3
    assert store.audio_path(events[1]).read_bytes() == b"legacy audio"
    assert store.audio_path(events[3]).exists()
    store.initialize()
    assert len(rows(store)) == 3


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
        assert {e['app']: e['priority'] for e in history} == {SNAPCHAT: 1, PHONE: 4}
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
