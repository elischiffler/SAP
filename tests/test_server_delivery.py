import asyncio
import sqlite3
import wave
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from contracts.models import ClassificationResult
from contracts.settings import Settings
from server.app import create_app


class Classifier:
    def __init__(self):
        self.calls = []

    async def classify(self, notification):
        self.calls.append(notification)
        priority = int(notification.title)
        return ClassificationResult(
            priority=priority,
            reason=f"reason-{notification.body}",
            spoken_text=notification.body if priority >= 3 else None,
            evidence="sufficient",
            deadline_at=None,
        )


class Speech:
    def __init__(self, *, wait=False):
        self.calls = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        if not wait:
            self.release.set()

    async def synthesize(self, text, destination: Path):
        self.calls.append(text)
        self.started.set()
        await self.release.wait()
        with wave.open(str(destination), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x00\x00" * 800)
        return destination


@asynccontextmanager
async def client_for(settings, classifier, speech, summarizer=None):
    app = create_app(
        settings,
        allow_test_ingestion=True,
        classifier=classifier,
        speech=speech,
        summarizer=summarizer,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        yield client


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        classifier_provider="demo",
        tts_provider="macos",
        max_provider_calls=30,
        max_delivery_attempts=2,
        grouping_window_seconds=0,
    )


async def submit(client, tier, *, body="Play this synthetic message.", event_id=None, **other):
    payload = {
        "event_id": str(event_id or uuid4()),
        "app": "Test",
        "sender": "Fictional Sender",
        "title": str(tier),
        "body": body,
        **other,
    }
    return await client.post("/api/notifications", json=payload)


async def snapshot(client):
    response = await client.get("/api/state")
    assert response.status_code == 200
    return response.json()


async def when_count(client, status, count):
    async with asyncio.timeout(3):
        while True:
            state = await snapshot(client)
            if state["counts"][status] == count:
                return state
            await asyncio.sleep(0.01)


async def claim(client, device):
    response = await client.post("/api/delivery/claim", json={"device_id": device})
    assert response.status_code == 200
    return response.json()["delivery"]


async def ack(client, lease, outcome="played", *, device=None):
    return await client.post(
        f"/api/delivery/{lease['lease_id']}/ack",
        json={"device_id": device or lease["device_id"], "outcome": outcome},
    )


def force_expiry(settings, lease):
    with sqlite3.connect(settings.data_dir / "pager.sqlite3") as connection:
        connection.execute(
            "UPDATE delivery_leases SET expires_at = 0 WHERE id = ?", (lease["lease_id"],)
        )


@pytest.mark.asyncio
async def test_all_priorities_discard_retention_and_alert_before_audio(settings):
    classifier, speech = Classifier(), Speech(wait=True)
    discarded_ids = [uuid4(), uuid4()]
    secret = "retention-check-81f0818c-62a7"
    async with client_for(settings, classifier, speech) as client:
        for priority, event_id in enumerate(discarded_ids, start=1):
            assert (
                await submit(
                    client, priority, event_id=event_id, body=secret, sender=secret, app=secret
                )
            ).status_code == 202
        assert (await submit(client, 5)).status_code == 202
        await asyncio.wait_for(speech.started.wait(), timeout=3)
        before_ready = await snapshot(client)
        assert before_ready["alerts"] == [
            {
                "id": before_ready["items"][0]["id"],
                "priority": 5,
                "created_at": before_ready["items"][0]["created_at"],
            }
        ]
        assert before_ready["counts"]["discarded"] == 2
        assert before_ready["counts"]["ready"] == 0
        assert len(before_ready["items"]) == 1
        assert await claim(client, "laptop") is None
        assert secret not in str(before_ready)

        duplicate = await submit(client, 4, event_id=discarded_ids[0], body="replacement")
        assert duplicate.status_code == 202
        assert duplicate.json()["status"] == "discarded"
        assert (await submit(client, 3, body="Third-level speech")).status_code == 202
        assert (await submit(client, 4, body="Fourth-level speech")).status_code == 202
        speech.release.set()
        state = await when_count(client, "ready", 3)

        assert [item["priority"] for item in state["items"]] == [5, 4, 3]
        assert len(classifier.calls) == 5
        assert speech.calls == [
            "Urgent notification from Fictional Sender on Test: 'Play this synthetic message.'",
            "New notification on Test from Fictional Sender: 'Fourth-level speech'",
            "New notification on Test from Fictional Sender: 'Third-level speech'",
        ]
        assert state["limits"]["provider_calls"] == 8
        assert len(list((settings.data_dir / "audio").glob("*.wav"))) == 3

    with sqlite3.connect(settings.data_dir / "pager.sqlite3") as connection:
        results = connection.execute(
            "SELECT id, status FROM completed_events WHERE status = 'discarded'"
        ).fetchall()
    assert set(results) == {(str(event_id), "discarded") for event_id in discarded_ids}
    with sqlite3.connect(settings.data_dir / "pager.sqlite3") as connection:
        assert secret not in str(connection.execute("SELECT * FROM messages").fetchall())
        assert secret not in str(connection.execute("SELECT * FROM group_members").fetchall())
        assert secret in str(
            connection.execute("SELECT record_json FROM ingress_history").fetchall()
        )
    assert not list(settings.data_dir.glob("*.sqlite3-*"))


@pytest.mark.asyncio
async def test_concurrent_claim_and_lost_ack_never_advance_another_message(settings):
    async with client_for(settings, Classifier(), Speech()) as client:
        high = await submit(client, 5)
        low = await submit(client, 4)
        await when_count(client, "ready", 2)

        first, again = await asyncio.gather(claim(client, "laptop"), claim(client, "laptop"))
        assert first == again
        assert first["message_id"] == high.json()["event_id"]
        other, blocked = await asyncio.gather(claim(client, "tablet"), claim(client, "phone"))
        winning = other or blocked
        assert (other is None) != (blocked is None)
        assert winning["message_id"] == low.json()["event_id"]

        assert (await client.get(first["audio_url"].replace("laptop", "phone"))).status_code == 403
        assert (await ack(client, first, device="tablet")).status_code == 403
        audio = await client.get(first["audio_url"])
        assert audio.status_code == 200
        assert audio.headers["content-type"] == "audio/wav"
        assert audio.headers["cache-control"] == "no-store"
        assert audio.content.startswith(b"RIFF")

        played, duplicate = await asyncio.gather(ack(client, first), ack(client, first))
        assert played.json() == duplicate.json() == {"status": "played"}
        assert (await ack(client, first, "retry")).status_code == 409
        assert (await client.get(first["audio_url"])).status_code == 409
        assert not (settings.data_dir / "audio" / f"{first['message_id']}.wav").exists()
        assert await claim(client, "laptop") is None
        assert await claim(client, winning["device_id"]) == winning
        assert (await snapshot(client))["counts"]["played"] == 1


@pytest.mark.asyncio
async def test_expiry_restart_heartbeat_and_retry(settings):
    classifier, speech = Classifier(), Speech()
    async with client_for(settings, classifier, speech) as client:
        await submit(client, 4)
        await when_count(client, "ready", 1)
        first = await claim(client, "first")
        heartbeat_url = f"/api/delivery/{first['lease_id']}/heartbeat"
        assert (await client.post(heartbeat_url, json={"device_id": "other"})).status_code == 403
        heartbeat = await client.post(heartbeat_url, json={"device_id": "first"})
        assert datetime.fromisoformat(
            heartbeat.json()["delivery"]["expires_at"]
        ) > datetime.fromisoformat(first["expires_at"])

    async with client_for(settings, classifier, speech) as client:
        active = await claim(client, "first")
        assert active == heartbeat.json()["delivery"]
        force_expiry(settings, active)
        assert (await client.post(heartbeat_url, json={"device_id": "first"})).status_code == 409

    async with client_for(settings, classifier, speech) as client:
        new = await claim(client, "second")
        assert new["message_id"] == first["message_id"]
        assert new["lease_id"] != first["lease_id"]
        assert new["attempt"] == 2
        assert (await ack(client, first)).status_code == 409
        assert (await client.get(first["audio_url"])).status_code == 409
        assert (await ack(client, new, "retry")).json() == {"status": "failed"}
        assert (await ack(client, new, "retry")).json() == {"status": "failed"}
        assert await claim(client, "second") is None
        assert (await client.post(f"/api/messages/{new['message_id']}/retry")).json() == {
            "status": "ready"
        }
        final = await claim(client, "first")
        assert final["attempt"] == 1
        assert (await ack(client, new, "retry")).json() == {"status": "failed"}
        assert await claim(client, "first") == final
        assert (await ack(client, final)).json() == {"status": "played"}
        assert len(classifier.calls) == len(speech.calls) == 1


@pytest.mark.asyncio
async def test_restart_recovers_interrupted_work_and_accounts_for_both_attempts(settings):
    settings = settings.model_copy(update={"max_provider_calls": 3})
    interrupted = Speech(wait=True)
    async with client_for(settings, Classifier(), interrupted) as client:
        event = await submit(client, 5)
        await asyncio.wait_for(interrupted.started.wait(), timeout=3)
        state = await snapshot(client)
        assert state["limits"]["provider_calls"] == 2
        assert state["counts"]["pending"] == 1

    classifier, speech = Classifier(), Speech()
    async with client_for(settings, classifier, speech) as client:
        state = await when_count(client, "ready", 1)
        assert state["items"][0]["id"] == event.json()["event_id"]
        assert len(speech.calls) == 1 and not classifier.calls
        assert state["limits"] == {"provider_calls": 3, "max_provider_calls": 3}
        assert (await submit(client, 3)).status_code == 202
        exhausted = await when_count(client, "failed", 1)
        failed_item = next(item for item in exhausted["items"] if item["status"] == "failed")
        assert (await client.post(f"/api/messages/{failed_item['id']}/retry")).status_code == 409
        assert await claim(client, "laptop")
        assert len(speech.calls) == 1 and not classifier.calls


class BrokenSpeech:
    async def synthesize(self, _text, destination):
        destination.write_bytes(b"raw-provider-error-content")
        return destination


@pytest.mark.asyncio
async def test_invalid_wav_sanitized_and_manual_retry_preserves_classification(settings):
    classifier = Classifier()
    async with client_for(settings, classifier, BrokenSpeech()) as client:
        accepted = await submit(client, 4)
        failed = await when_count(client, "failed", 1)
        item = failed["items"][0]
        assert item["error"] == "Speech generation returned invalid audio."
        assert await claim(client, "laptop") is None
        assert not list((settings.data_dir / "audio").glob("*.wav"))

    speech = Speech()
    async with client_for(settings, classifier, speech) as client:
        response = await client.post(f"/api/messages/{accepted.json()['event_id']}/retry")
        assert response.json() == {"status": "pending"}
        state = await when_count(client, "ready", 1)
        assert state["limits"]["provider_calls"] == 3
        assert len(classifier.calls) == len(speech.calls) == 1


@pytest.mark.asyncio
async def test_outstanding_capacity_and_same_id_reuse(settings):
    settings = settings.model_copy(update={"max_pending_notifications": 1})
    async with client_for(settings, Classifier(), Speech()) as client:
        request_id = uuid4()
        assert (await submit(client, 3, event_id=request_id)).status_code == 202
        await when_count(client, "ready", 1)
        assert (await submit(client, 3)).status_code == 429
        assert (await submit(client, 5, event_id=request_id)).json()["status"] == "ready"
        lease = await claim(client, "laptop")
        assert (await submit(client, 3)).status_code == 429
        assert (await ack(client, lease)).json()["status"] == "played"
        assert (await submit(client, 5, event_id=request_id)).json()["status"] == "played"
        assert (await submit(client, 1)).status_code == 202
        await when_count(client, "discarded", 1)


@pytest.mark.asyncio
async def test_validation_body_bound_and_local_origin(settings):
    async with client_for(settings, Classifier(), Speech()) as client:
        wrong_host = await client.get("/api/state", headers={"Host": "attacker.invalid"})
        assert wrong_host.status_code == 403
        wrong_origin = await client.post(
            "/api/delivery/claim",
            headers={"Origin": "https://attacker.invalid"},
            json={"device_id": "device"},
        )
        assert wrong_origin.status_code == 403
        invalid_device = await client.post("/api/delivery/claim", json={"device_id": "../laptop"})
        assert invalid_device.status_code == 422
        invalid = await submit(client, 3, received_at="unparseable-sensitive-body")
        assert invalid.status_code == 422
        assert "unparseable-sensitive-body" not in invalid.text
        smuggled_priority = await submit(client, 3, priority=5)
        assert smuggled_priority.status_code == 422

        over_limit_declared = await client.post(
            "/api/notifications",
            headers={"Content-Type": "application/json"},
            content=b"x" * 32769,
        )
        assert over_limit_declared.status_code == 413

        async def chunks():
            for _ in range(3):
                yield b"x" * 16384

        over_limit_stream = await client.post(
            "/api/notifications",
            headers={"Content-Type": "application/json"},
            content=chunks(),
        )
        assert over_limit_stream.status_code == 413
        assert (await snapshot(client))["limits"]["provider_calls"] == 0


@pytest.mark.asyncio
async def test_missing_leased_audio_unblocks_device_and_can_be_regenerated(settings):
    classifier, speech = Classifier(), Speech()
    async with client_for(settings, classifier, speech) as client:
        await submit(client, 5)
        await submit(client, 4)
        await when_count(client, "ready", 2)
        first = await claim(client, "laptop")
        (settings.data_dir / "audio" / f"{first['message_id']}.wav").unlink()

        assert (await client.get(first["audio_url"])).status_code == 409
        state = await when_count(client, "failed", 1)
        assert state["items"][0]["error"] == "The queued audio file is missing."
        second = await claim(client, "laptop")
        assert second["message_id"] != first["message_id"]
        assert (await ack(client, first)).status_code == 409

        assert (await client.post(f"/api/messages/{first['message_id']}/retry")).json() == {
            "status": "pending",
        }
        assert (await ack(client, second)).json() == {"status": "played"}
        await when_count(client, "ready", 1)
        assert (await claim(client, "laptop"))["message_id"] == first["message_id"]
        assert len(classifier.calls) == 2
        assert len(speech.calls) == 3


@pytest.mark.asyncio
async def test_played_ack_cleanup_survives_restart_and_can_retry(settings, monkeypatch):
    classifier, speech = Classifier(), Speech()
    remove_file = Path.unlink
    settings = settings.model_copy(update={"max_pending_notifications": 1})

    async with client_for(settings, classifier, speech) as client:
        await submit(client, 5)
        await when_count(client, "ready", 1)
        first = await claim(client, "laptop")
        first_audio = settings.data_dir / "audio" / f"{first['message_id']}.wav"

        def deny_played_cleanup(path, *args, **kwargs):
            if path == first_audio:
                raise PermissionError("synthetic filesystem error")
            return remove_file(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", deny_played_cleanup)
        assert (await ack(client, first)).status_code == 503
        assert first_audio.exists()
        assert (await client.get(first["audio_url"])).status_code == 409
        assert (await submit(client, 5)).status_code == 429
        state = await when_count(client, "played", 1)
        assert not state["items"]

    async with client_for(settings, classifier, speech) as client:
        assert (await ack(client, first)).status_code == 503
        monkeypatch.setattr(Path, "unlink", remove_file)
        assert (await ack(client, first)).json() == {"status": "played"}
        assert not first_audio.exists()
        assert (await snapshot(client))["counts"]["played"] == 1
        assert (await submit(client, 5)).status_code == 202


@pytest.mark.asyncio
async def test_startup_removes_interrupted_speech_artifacts(settings):
    temp_speech = settings.data_dir / "audio" / ".speech-interrupted"
    temp_speech.mkdir(parents=True)
    audio = temp_speech / "audio.wav"
    audio.write_bytes(b"private partial audio")
    staging = temp_speech.parent / f"{uuid4()}.pending.wav"
    staging.write_bytes(b"private staging audio")
    unrelated = temp_speech.parent / "unmanaged.txt"
    unrelated.write_bytes(b"outside the queue")

    async with client_for(settings, Classifier(), Speech()):
        assert not temp_speech.exists()
        assert not staging.exists()
        assert unrelated.exists()


@pytest.mark.asyncio
async def test_delivery_quotes_source_message_instead_of_model_paraphrase(settings):
    class ParaphrasingClassifier:
        async def classify(self, notification):
            return ClassificationResult(
                priority=3,
                reason="A personal question.",
                spoken_text="Sam demands you arrive at a location that was never mentioned.",
                evidence="sufficient",
                deadline_at=None,
            )

    speech = Speech()
    async with client_for(settings, ParaphrasingClassifier(), speech) as client:
        await submit(client, 3, app="iMessage", sender="Sam", body="Want dinner tonight?")
        await when_count(client, "ready", 1)
        lease = await claim(client, "laptop")
        expected = "New message on iMessage from Sam: 'Want dinner tonight?'"
        assert lease["spoken_text"] == expected
        assert speech.calls == [expected]
        assert (await ack(client, lease)).json() == {"status": "played"}


@pytest.mark.asyncio
async def test_voice_override_is_rejected_without_spending_budget(settings):
    settings = settings.model_copy(update={"tts_provider": "openai"})
    async with client_for(settings, Classifier(), Speech()) as client:
        assert (await submit(client, 3, tts_voice="sage")).status_code == 422
        assert (await snapshot(client))["limits"]["provider_calls"] == 0


class Summarizer:
    def __init__(self, *, fail=False, hold=False):
        self.groups = []
        self.fail = fail
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        if not hold:
            self.release.set()

    async def summarize(self, group):
        self.groups.append(group)
        self.started.set()
        await self.release.wait()
        if self.fail:
            raise RuntimeError("uncensored provider details")
        return f"{len(group.members)} new notifications in this conversation."


@pytest.fixture
def grouping_settings(settings):
    return settings.model_copy(update={"grouping_delay_seconds": 0, "grouping_window_seconds": 60})


@pytest.mark.asyncio
async def test_group_replaces_ready_wav_promotes_priority_and_acks_all_members(grouping_settings):
    classifier, speech, summarizer = Classifier(), Speech(), Summarizer(hold=True)
    async with client_for(grouping_settings, classifier, speech, summarizer) as client:
        first = await submit(client, 3, app="iMessage", sender="Sam", body="Dinner tonight?")
        root_id = first.json()["event_id"]
        await when_count(client, "ready", 1)
        old_audio = grouping_settings.data_dir / "audio" / f"{root_id}.wav"
        assert old_audio.exists()

        secret = "discarded-group-content-3766"
        discarded = await submit(client, 2, app="iMessage", sender="Sam", body=secret)
        urgent = await submit(client, 5, app=" imessage ", sender=" SAM ", body="Call immediately")
        urgent_id = urgent.json()["event_id"]
        await asyncio.wait_for(summarizer.started.wait(), timeout=3)

        state = await snapshot(client)
        assert state["counts"]["pending"] == state["counts"]["discarded"] == 1
        assert state["items"][0]["id"] == root_id
        assert state["items"][0]["notification_count"] == 2
        assert state["items"][0]["spoken_text"] is None
        assert state["alerts"][0]["id"] == root_id
        assert not old_audio.exists()
        assert await claim(client, "laptop") is None
        assert (await submit(client, 3, event_id=urgent_id)).json()["status"] == "pending"
        assert (await submit(client, 3, event_id=discarded.json()["event_id"])).json()[
            "status"
        ] == "discarded"
        group = summarizer.groups[0]
        assert [str(member.event_id) for member in group.members] == [root_id, urgent_id]
        assert [member.priority for member in group.members] == [3, 5]
        with sqlite3.connect(grouping_settings.data_dir / "pager.sqlite3") as connection:
            assert secret not in str(connection.execute("SELECT * FROM messages").fetchall())
            assert secret not in str(connection.execute("SELECT * FROM group_members").fetchall())

        summarizer.release.set()
        await when_count(client, "ready", 1)
        lease = await claim(client, "laptop")
        assert lease["priority"] == 5 and lease["notification_count"] == 2
        assert lease["spoken_text"] == "2 new notifications in this conversation."
        assert (await ack(client, lease)).json() == {"status": "played"}
        assert (await ack(client, lease)).json() == {"status": "played"}
        assert (await snapshot(client))["counts"]["played"] == 2
        assert not old_audio.exists()
        assert len(classifier.calls) == 3
        assert len(speech.calls) == 2
        for event_id in (root_id, urgent_id):
            assert (await submit(client, 3, event_id=event_id)).json()["status"] == "played"


@pytest.mark.asyncio
async def test_group_identity_uses_application_conversation_and_sender_namespaces(
    grouping_settings,
):
    summarizer = Summarizer()
    async with client_for(grouping_settings, Classifier(), Speech(), summarizer) as client:
        await submit(
            client,
            3,
            app="Chat",
            sender="Alice",
            conversation_id="thread",
            conversation_name="Family",
        )
        await when_count(client, "ready", 1)
        await submit(
            client,
            3,
            app="Chat",
            sender="Bob",
            conversation_id="thread",
            conversation_name="Family",
        )
        async with asyncio.timeout(3):
            while (await snapshot(client))["items"][0]["notification_count"] != 2:
                await asyncio.sleep(0.01)
        await submit(client, 3, app="Other Chat", sender="Alice", conversation_id="thread")
        await submit(client, 3, app="Chat", sender="Alice", sender_id="thread")
        await submit(client, 3, app="Chat", sender="Alice", conversation_id="unrelated")
        await submit(client, 3, app="Chat", sender=None)
        await submit(client, 3, app="Chat", sender=" ")
        state = await when_count(client, "ready", 6)

        assert len(summarizer.groups) == 1
        assert [member.sender for member in summarizer.groups[0].members] == ["Alice", "Bob"]
        grouped = next(item for item in state["items"] if item["notification_count"] == 2)
        assert grouped["conversation_name"] == "Family"
        assert (await claim(client, "laptop"))["conversation_name"] == "Family"


@pytest.mark.asyncio
async def test_claim_seals_group_even_when_retried_after_restart(grouping_settings):
    async with client_for(grouping_settings, Classifier(), Speech()) as client:
        await submit(client, 3)
        await when_count(client, "ready", 1)
        original = await claim(client, "laptop")
        assert (await ack(client, original, "retry")).json() == {"status": "ready"}

    async with client_for(grouping_settings, Classifier(), Speech()) as client:
        urgent = await submit(client, 5)
        await when_count(client, "ready", 2)
        first = await claim(client, "laptop")
        assert first["message_id"] == urgent.json()["event_id"]
        assert first["notification_count"] == original["notification_count"] == 1
        second = await claim(client, "tablet")
        assert second["message_id"] == original["message_id"]
        assert second["spoken_text"] == original["spoken_text"]


@pytest.mark.asyncio
async def test_failed_summary_retries_without_reclassification_and_capacity_counts_members(
    grouping_settings,
):
    grouping_settings = grouping_settings.model_copy(update={"max_pending_notifications": 2})
    classifier, broken, speech = Classifier(), Summarizer(fail=True), Speech()
    async with client_for(grouping_settings, classifier, speech, broken) as client:
        root_id = (await submit(client, 3)).json()["event_id"]
        await when_count(client, "ready", 1)
        member_id = (await submit(client, 4)).json()["event_id"]
        failed = await when_count(client, "failed", 1)
        assert failed["items"][0]["notification_count"] == 2
        assert "uncensored" not in str(failed)
        assert failed["items"][0]["error"] == "Conversation summarization was unavailable."
        assert await claim(client, "laptop") is None
        assert (await submit(client, 5)).status_code == 429
        assert (await submit(client, 5, event_id=member_id)).json()["status"] == "failed"

    summarizer = Summarizer()
    async with client_for(grouping_settings, classifier, speech, summarizer) as client:
        assert (await client.post(f"/api/messages/{root_id}/retry")).json() == {"status": "pending"}
        state = await when_count(client, "ready", 1)
        assert state["limits"]["provider_calls"] == 6
        assert len(classifier.calls) == 2 and len(summarizer.groups) == len(broken.groups) == 1
        assert (await ack(client, await claim(client, "laptop"))).json() == {"status": "played"}
        assert (await submit(client, 3)).status_code == 202


def test_group_migration_preserves_legacy_ready_audio_and_pending_input(grouping_settings):
    import json

    from server.store import QueueStore

    store = QueueStore(grouping_settings)
    store.audio_dir.mkdir(parents=True)
    ready_id, pending_id = str(uuid4()), str(uuid4())
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """CREATE TABLE messages (
                 id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at REAL NOT NULL, app TEXT NOT NULL,
                 sender TEXT, input_json TEXT, priority INTEGER, spoken_text TEXT, tts_voice TEXT,
                 error TEXT, attempt INTEGER NOT NULL DEFAULT 0)"""
        )
        connection.execute(
            """INSERT INTO messages (id, status, created_at, app, sender, priority, spoken_text, tts_voice)
               VALUES (?, 'ready', 1, 'Messages', 'Sam', 3, 'Legacy preview', 'sage')""",
            (ready_id,),
        )
        payload = {
            "event_id": pending_id,
            "app": "Test",
            "title": "3",
            "tts_voice": "nova",
            "received_at": "2026-11-14T12:56:41-08:00",
        }
        connection.execute(
            """INSERT INTO messages (id, status, created_at, app, input_json)
               VALUES (?, 'pending', 2, 'Test', ?)""",
            (pending_id, json.dumps(payload)),
        )
    store.audio_path(ready_id).write_bytes(b"existing legacy audio")
    store.initialize()
    store.initialize()
    assert store.audio_path(ready_id).read_bytes() == b"existing legacy audio"
    queued = store.reserve_job()
    assert queued["job_type"] == "classification" and queued["id"] == pending_id
    assert "tts_voice" not in json.loads(queued["input_json"])
    assert queued["received_at"] == datetime.fromisoformat("2026-11-14T20:56:41Z").timestamp()
    lease = store.claim("laptop")
    assert lease["notification_count"] == 1
    assert lease["spoken_text"] == "Legacy preview"
    assert lease["received_at"] == "1970-01-01T00:00:01+00:00"
    assert store.acknowledge(lease["lease_id"], "laptop", "played") == "played"
    assert store.snapshot()["counts"]["played"] == 1


def test_group_quiet_window_cap_and_urgent_bypass(grouping_settings, monkeypatch):
    from types import SimpleNamespace

    from contracts.models import NotificationInput
    from server import store as store_module

    grouping_settings = grouping_settings.model_copy(
        update={
            "grouping_delay_seconds": 2,
            "grouping_window_seconds": 60,
            "max_group_notifications": 2,
        }
    )
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(store_module, "time", SimpleNamespace(time=lambda: clock.now))
    store = store_module.QueueStore(grouping_settings)
    store.initialize()

    def classify(priority, *, sender="Sam"):
        item = NotificationInput(app="Messages", sender=sender, body="Test notification")
        store.enqueue(item)
        job = store.reserve_job()
        assert job["id"] == str(item.event_id) and job["job_type"] == "classification"
        store.finish_classification(
            job["id"],
            ClassificationResult(
                priority=priority,
                reason="Test",
                spoken_text=item.body,
                evidence="sufficient",
                deadline_at=None,
            ),
        )
        return str(item.event_id)

    first_id = classify(3)
    assert store.reserve_job() is None
    clock.now += 1
    classify(4)
    assert store.reserve_job() is None
    third_id = classify(5)
    urgent = store.reserve_job()
    assert urgent["id"] == third_id and urgent["job_type"] == "speech"
    store.finish_speech(third_id)
    clock.now += 1
    assert store.reserve_job() is None
    clock.now += 1
    summary = store.reserve_job()
    assert summary["id"] == first_id and summary["job_type"] == "summary"
    store.finish_summary(first_id, "Two notifications.")
    assert store.reserve_job()["id"] == first_id
    store.finish_speech(first_id)

    clock.now += 60
    classify(3)
    # Age no longer closes a group: fill the other group's free slot.
    assert sorted(item["notification_count"] for item in store.snapshot()["items"]) == [2, 2]


@pytest.mark.asyncio
async def test_interrupted_summary_restarts_from_persisted_members(grouping_settings):
    classifier, stopped_summary, speech = Classifier(), Summarizer(hold=True), Speech()
    async with client_for(grouping_settings, classifier, speech, stopped_summary) as client:
        original = await submit(client, 3)
        await when_count(client, "ready", 1)
        await submit(client, 4)
        await asyncio.wait_for(stopped_summary.started.wait(), timeout=3)
        assert (await snapshot(client))["limits"]["provider_calls"] == 4

    summarizer = Summarizer()
    async with client_for(grouping_settings, classifier, speech, summarizer) as client:
        state = await when_count(client, "ready", 1)
        assert state["items"][0]["id"] == original.json()["event_id"]
        assert state["items"][0]["notification_count"] == 2
        assert state["limits"]["provider_calls"] == 6
        assert len(classifier.calls) == 2
        assert summarizer.groups == stopped_summary.groups
        assert len(speech.calls) == 2


def store_classify_next(store, priority):
    job = store.reserve_job()
    assert job["job_type"] == "classification"
    store.finish_classification(
        job["id"],
        ClassificationResult(
            priority=priority,
            reason="Test tier.",
            spoken_text="Test speech." if priority >= 3 else None,
            evidence="sufficient",
            deadline_at=None,
        ),
    )
    return job["id"]


def test_known_urgent_audio_precedes_backlog_and_ordinary_audio_gets_a_turn(settings):
    from contracts.models import NotificationInput
    from server.store import CLASSIFICATION_BURST, QueueStore

    store = QueueStore(settings)
    store.initialize()
    store.enqueue(NotificationInput(app="Urgent"))
    urgent_id = store_classify_next(store, 5)
    for _ in range(CLASSIFICATION_BURST + 2):
        store.enqueue(NotificationInput(app="Backlog"))

    job = store.reserve_job()
    assert job["id"] == urgent_id and job["job_type"] == "speech"
    store.finish_speech(urgent_id)

    materialized_id = store_classify_next(store, 3)
    for _ in range(CLASSIFICATION_BURST - 1):
        store_classify_next(store, 1)
    job = store.reserve_job()
    assert job["id"] == materialized_id and job["job_type"] == "speech"
    assert len(store.snapshot()["items"]) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_budget", [3, 4])
async def test_insufficient_replacement_budget_preserves_ready_wav(
    grouping_settings, provider_budget
):
    grouping_settings = grouping_settings.model_copy(update={"max_provider_calls": provider_budget})
    classifier, speech, summarizer = Classifier(), Speech(), Summarizer()
    async with client_for(grouping_settings, classifier, speech, summarizer) as client:
        ready_id = (await submit(client, 3)).json()["event_id"]
        await when_count(client, "ready", 1)
        separate_id = (await submit(client, 5)).json()["event_id"]
        state = await when_count(
            client, "failed" if provider_budget == 3 else "ready", 1 if provider_budget == 3 else 2
        )
        assert {item["id"]: item["notification_count"] for item in state["items"]} == {
            ready_id: 1,
            separate_id: 1,
        }
        lease = await claim(client, "laptop")
        if provider_budget == 4:
            assert lease["message_id"] == separate_id
            assert (await ack(client, lease)).json() == {"status": "played"}
            lease = await claim(client, "laptop")
        assert lease["message_id"] == ready_id
        assert (await client.get(lease["audio_url"])).status_code == 200
        assert not summarizer.groups


def test_reserved_replacement_survives_restart_and_ordinary_backlog(grouping_settings):
    from contracts.models import NotificationInput
    from server.store import QueueStore

    settings = grouping_settings.model_copy(update={"max_provider_calls": 5})
    store = QueueStore(settings)
    store.initialize()
    original = NotificationInput(app="Text", sender="Sam")
    store.enqueue(original)
    root_id = store_classify_next(store, 3)
    assert store.reserve_job()["job_type"] == "speech"
    store.audio_path(root_id).write_bytes(b"original audio")
    store.finish_speech(root_id)

    store.enqueue(NotificationInput(app="Text", sender="Sam"))
    store_classify_next(store, 4)
    store.enqueue(NotificationInput(app="Unrelated"))
    resumed = QueueStore(settings)
    resumed.initialize()
    assert not resumed.audio_path(root_id).exists()
    job = resumed.reserve_job()
    assert job["id"] == root_id and job["job_type"] == "summary"
    resumed.finish_summary(root_id, "Two notifications.")
    job = resumed.reserve_job()
    assert job["id"] == root_id and job["job_type"] == "speech"
    resumed.finish_speech(root_id)
    assert resumed.reserve_job() is None
    state = resumed.snapshot()
    assert state["counts"]["ready"] == state["counts"]["failed"] == 1
    assert state["limits"]["provider_calls"] == 5


def test_retention_prunes_oldest_but_totals_and_recent_receipts_survive(settings, monkeypatch):
    from contracts.models import NotificationInput
    from server import store as store_module

    monkeypatch.setattr(store_module, "HISTORY_LIMIT", 3)
    store = store_module.QueueStore(settings)
    with sqlite3.connect(store.path) as connection:
        connection.executescript(store_module.SCHEMA)
        connection.executemany(
            "INSERT INTO completed_events VALUES (?, ?)",
            [(str(index), "discarded" if index % 2 else "played") for index in range(5)],
        )
        connection.executemany(
            "INSERT INTO delivery_receipts VALUES (?, 'laptop', 'played', 'played')",
            [(str(index),) for index in range(5)],
        )

    store.initialize()
    counts = store.snapshot()["counts"]
    assert counts["played"] == 3 and counts["discarded"] == 2
    item = NotificationInput(app="News")
    store.enqueue(item)
    store_classify_next(store, 1)
    assert store.enqueue(item) == "discarded"

    other = NotificationInput(app="Text")
    store.enqueue(other)
    item_id = store_classify_next(store, 3)
    store.reserve_job()
    store.audio_path(item_id).write_bytes(b"existing speech")
    store.finish_speech(item_id)
    lease = store.claim("laptop")
    assert store.acknowledge(lease["lease_id"], "laptop", "played") == "played"

    store.initialize()
    with store.transaction() as connection:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 250
        assert [
            row[0] for row in connection.execute("SELECT id FROM completed_events ORDER BY rowid")
        ] == ["4", str(item.event_id), item_id]
        assert [
            row[0] for row in connection.execute("SELECT id FROM delivery_receipts ORDER BY rowid")
        ] == ["3", "4", lease["lease_id"]]
    assert store.acknowledge(lease["lease_id"], "laptop", "played") == "played"
    counts = store.snapshot()["counts"]
    assert counts["played"] == 4 and counts["discarded"] == 3


def test_classification_batch_reserves_only_matching_pending_rows_and_recovers(
    grouping_settings, monkeypatch
):
    from types import SimpleNamespace

    from contracts.models import NotificationInput
    from server import store as store_module

    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(store_module, "time", SimpleNamespace(time=lambda: clock.now))
    store = store_module.QueueStore(grouping_settings)
    store.initialize()
    first = NotificationInput(app="Text", sender="Sam", conversation_id="family")
    matching = NotificationInput(app=" text ", sender="Jo", conversation_id="family")
    fallback = NotificationInput(app="Text", sender="family")
    other_app = NotificationInput(app="Chat", sender="Sam", conversation_id="family")
    for item in (first, matching, fallback, other_app):
        store.enqueue(item)
    first_job = store.reserve_job()
    assert first_job["id"] == str(first.event_id)
    clock.now += 61
    too_late = NotificationInput(app="Text", conversation_id="family")
    store.enqueue(too_late)

    batch = store.reserve_classification_batch(first_job["id"])
    assert [row["id"] for row in batch] == [str(first.event_id), str(matching.event_id)]
    assert store.snapshot()["limits"]["provider_calls"] == 1
    assert store.enqueue(matching) == "pending"
    with store.transaction() as connection:
        processing = {
            row["id"]
            for row in connection.execute("SELECT id FROM messages WHERE status = 'processing'")
        }
    assert processing == {str(first.event_id), str(matching.event_id)}

    store.initialize()
    with store.transaction() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM messages WHERE status = 'pending'").fetchone()[
                0
            ]
            == 5
        )
    assert store.snapshot()["limits"]["provider_calls"] == 1


def test_classification_batch_cap_and_unidentified_notification_isolation(grouping_settings):
    from contracts.models import NotificationInput
    from server.store import CLASSIFICATION_BATCH_LIMIT, QueueStore

    store = QueueStore(grouping_settings)
    store.initialize()
    for _ in range(CLASSIFICATION_BATCH_LIMIT + 2):
        store.enqueue(NotificationInput(app="Chat", sender_id="known"))
    for _ in range(2):
        store.enqueue(NotificationInput(app="Chat"))

    first = store.reserve_job()
    batch = store.reserve_classification_batch(first["id"], limit=100)
    assert len(batch) == CLASSIFICATION_BATCH_LIMIT
    next_job = store.reserve_job()
    assert len(store.reserve_classification_batch(next_job["id"])) == 2
    unidentified = store.reserve_job()
    assert store.reserve_classification_batch(unidentified["id"]) == [
        {
            "id": unidentified["id"],
            "input_json": unidentified["input_json"],
        }
    ]
    assert store.snapshot()["limits"]["provider_calls"] == 3


@pytest.mark.asyncio
async def test_fifty_notifications_use_five_classifications_one_summary_and_one_wav(
    grouping_settings,
):
    class BatchClassifier(Classifier):
        def __init__(self):
            super().__init__()
            self.batch_sizes = []

        async def classify_batch(self, notifications):
            self.batch_sizes.append(len(notifications))
            return [await self.classify(notification) for notification in notifications]

    grouping_settings = grouping_settings.model_copy(
        update={"classification_batch_wait_seconds": 0.05, "max_group_notifications": 50}
    )
    classifier, speech, summarizer = BatchClassifier(), Speech(), Summarizer()
    async with client_for(grouping_settings, classifier, speech, summarizer) as client:
        requests = await asyncio.gather(
            *[
                submit(
                    client, 3, app="Chat", sender=f"Contact {index % 3}", conversation_id="group"
                )
                for index in range(50)
            ]
        )
        assert all(response.status_code == 202 for response in requests)
        state = await when_count(client, "ready", 1)
        assert state["counts"]["pending"] == 0
        assert state["items"][0]["notification_count"] == 50
        assert classifier.batch_sizes == [10] * 5
        assert len(summarizer.groups) == len(speech.calls) == 1
        assert state["limits"]["provider_calls"] == 7
        lease = await claim(client, "laptop")
        assert lease["notification_count"] == 50
        assert (await ack(client, lease)).json() == {"status": "played"}
        assert (await snapshot(client))["counts"]["played"] == 50


def test_group_summary_uses_factual_digest_separate_from_solo_preview(grouping_settings):
    from contracts.models import NotificationInput
    from server.store import QueueStore

    store = QueueStore(grouping_settings)
    store.initialize()
    critical_tail = "The building evacuation starts at noon."
    first = NotificationInput(
        app="Chat", sender="Sam", body="Earlier context. " * 100 + critical_tail
    )
    second = NotificationInput(app="Chat", sender="Sam", body="I am waiting in the lobby.")
    for item in (first, second):
        store.enqueue(item)

    first_job = store.reserve_job()
    preview = first.body[:350]
    assert critical_tail not in preview
    store.finish_classification(
        first_job["id"],
        ClassificationResult(
            priority=5,
            reason="Time-sensitive evacuation.",
            spoken_text=preview,
            evidence="sufficient",
            deadline_at=None,
        ),
        summary_text=critical_tail,
    )
    assert store.snapshot()["items"][0]["spoken_text"] == preview
    first_audio = store.reserve_job()
    assert first_audio["job_type"] == "speech"
    assert first_audio["spoken_text"] == preview
    store.finish_speech(first_job["id"])

    second_job = store.reserve_job()
    assert second_job["id"] == str(second.event_id)
    store.finish_classification(
        second_job["id"],
        ClassificationResult(
            priority=3,
            reason="An update.",
            spoken_text=second.body,
            evidence="sufficient",
            deadline_at=None,
        ),
    )
    grouped = store.group_for_summary(first_job["id"])
    assert [member.spoken_text for member in grouped.members] == [critical_tail, second.body]
