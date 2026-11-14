import asyncio
import json
import sqlite3
import wave
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
import pytest

from contracts import ClassificationResult, Settings
from server.app import create_app
from server.store import QueueStore

TOKEN = "private-test-esp-token-0123456789"
KEY = "private-test-openai-secret-key"
ESP = "/api/esp/notifications"
STANDARD = "/api/notifications"
LOG = "/api/ingress-log"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@asynccontextmanager
async def connect(tmp_path, classifier=None, speech=None, **overrides):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        classifier_provider="demo",
        tts_provider="macos",
        esp_ingest_token=TOKEN,
        openai_api_key=KEY,
        max_provider_calls=0,
    )
    app = create_app(
        settings.model_copy(update=overrides),
        allow_test_ingestion=True,
        classifier=classifier,
        speech=speech,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client,
    ):
        yield client


@pytest.fixture
async def client(tmp_path):
    async with connect(tmp_path) as client:
        yield client


async def test_logs_standard_esp_json_and_esp_text_as_accepted_transactions(client):
    date = "20261114T130105"
    result = await client.post(
        STANDARD,
        json={
            "app": "Messages",
            "title": "private-standard-title",
            "sender": "private-standard-sender",
            "body": "private-standard-body",
        },
    )
    esp_json = await client.post(
        ESP,
        headers=AUTH,
        json={
            "app": "com.apple.MobileSMS",
            "title": "private-json-title",
            "message": "private-json-body",
            "date": date,
        },
    )
    esp_text = await client.post(
        f"{ESP}?sentinel=private-query-value",
        content=f"com.example.chat | private-text-sender | private-text-body | {date}",
        headers=AUTH | {"Content-Type": "text/plain"},
    )
    assert result.status_code == esp_json.status_code == esp_text.status_code == 202

    response = await client.get(LOG)
    assert response.headers["cache-control"] == "no-store"
    assert "private-query-value" not in response.text
    entries = response.json()["entries"]
    assert [entry["path"] for entry in entries] == [ESP, ESP, STANDARD]
    assert [entry["app"] for entry in entries] == [
        "com.example.chat",
        "com.apple.MobileSMS",
        "Messages",
    ]
    assert [entry["event_id"] for entry in entries] == [
        item.json()["event_id"] for item in [esp_text, esp_json, result]
    ]
    arrival_times = [datetime.fromisoformat(entry["received_at"]) for entry in entries]
    assert all(value.tzinfo == timezone.utc for value in arrival_times)
    assert arrival_times == sorted(arrival_times, reverse=True)
    assert len({UUID(entry["id"]) for entry in entries}) == 3
    assert all(entry["status_code"] == 202 and entry["method"] == "POST" for entry in entries)
    assert all(entry["duration_ms"] >= 0 for entry in entries)
    assert all(entry["preview"] is None and entry["sender"] is None for entry in entries)
    assert entries[0]["payload"] == (
        f"com.example.chat | private-text-sender | private-text-body | {date}"
    )
    assert entries[1]["payload"] == {
        "app": "com.apple.MobileSMS",
        "title": "private-json-title",
        "message": "private-json-body",
        "date": date,
    }
    assert entries[2]["payload"] == {
        "app": "Messages",
        "title": "private-standard-title",
        "sender": "private-standard-sender",
        "body": "private-standard-body",
    }
    assert not any(entry["payload_redacted"] for entry in entries)
    assert [entry["id"] for entry in (await client.get(LOG)).json()["entries"]] == [
        entry["id"] for entry in entries
    ]


async def test_rejected_and_failed_ingress_never_record_metadata(client, monkeypatch):
    denied = await client.post(
        ESP, json={"app": "private-denied-app"}, headers={"Authorization": "Bearer private-wrong"}
    )
    invalid = await client.post(
        ESP, json={"app": "private-invalid-app", "date": "private-bad-date"}, headers=AUTH
    )
    cross_origin = await client.post(
        STANDARD, json={"app": "private-origin-app"}, headers={"Origin": "https://example.invalid"}
    )

    def fail_enqueue(self, notification):
        raise RuntimeError("private-storage-error")

    monkeypatch.setattr(QueueStore, "enqueue", fail_enqueue)
    failed = await client.post(STANDARD, json={"app": "private-failed-app"})
    assert [item.status_code for item in (denied, invalid, cross_origin, failed)] == [
        401,
        422,
        403,
        500,
    ]
    assert "private-" not in failed.text

    response = await client.get(LOG)
    assert "private-" not in response.text
    entries = response.json()["entries"]
    assert [item["status_code"] for item in entries] == [500, 403, 422, 401]
    assert all(
        all(
            entry[field] is None
            for field in ("event_id", "app", "sender", "preview", "payload", "queue_status")
        )
        for entry in entries
    )


async def test_log_retains_at_most_100_post_requests_and_ignores_polling(client):
    first = await client.post(STANDARD, json={"app": "First"})
    for _ in range(99):
        assert (await client.post(ESP, json={"app": "Rejected"})).status_code == 401
    latest_id = str(uuid4())
    assert (
        await client.post(STANDARD, json={"app": TOKEN, "event_id": latest_id})
    ).status_code == 202
    await client.get("/api/state")
    await client.post("/api/delivery/claim", json={"device_id": "test"})
    entries = (await client.get(LOG)).json()["entries"]
    assert len(entries) == 100
    assert entries[0]["event_id"] == latest_id and entries[0]["app"] == "redacted"
    assert first.json()["event_id"] not in {entry["event_id"] for entry in entries}
    assert (await client.get(LOG)).json()["entries"] == entries


async def test_accepted_payload_redacts_credentials_and_hides_private_fields(client, monkeypatch):
    raw = {
        "app": f"Messages {TOKEN}",
        "sender": KEY,
        "title": f"Title {TOKEN}",
        "body": f"Text {KEY} verification code 123456",
        "sender_id": TOKEN,
        "conversation_id": KEY,
        "conversation_name": TOKEN,
    }
    response = await client.post(STANDARD, json=raw)
    hidden = await client.post(
        STANDARD, json={**raw, "content_hidden": True, "body": "hidden body"}
    )
    assert response.status_code == hidden.status_code == 202
    result = await client.get(LOG)
    assert TOKEN not in result.text and KEY not in result.text and "123456" not in result.text
    assert "hidden body" not in result.text
    hidden_entry, entry = result.json()["entries"]
    assert entry["payload_redacted"] and hidden_entry["payload_redacted"]
    assert entry["payload"]["body"] == "Text redacted verification code redacted"
    assert entry["payload"]["title"] == "Title redacted"
    assert entry["payload"]["sender"] == entry["payload"]["sender_id"] == "redacted"
    assert (
        entry["payload"]["conversation_id"] == entry["payload"]["conversation_name"] == "redacted"
    )
    private = hidden_entry["payload"]
    assert private["content_hidden"] and private["title"] == private["body"] == ""
    assert all(
        private[field] is None
        for field in ("sender", "sender_id", "conversation_id", "conversation_name")
    )

    def unavailable(self, limit=100, before=None):
        raise sqlite3.OperationalError("synthetic read failure")

    monkeypatch.setattr(QueueStore, "ingress_history", unavailable)
    response = await client.get(LOG)
    assert response.status_code == 503
    assert TOKEN not in response.text and KEY not in response.text


class Classifier:
    async def classify(self, notification):
        priority = int(notification.title)
        return ClassificationResult(
            priority=priority,
            reason="Test",
            spoken_text=notification.body if priority >= 3 else None,
            evidence="sufficient",
            deadline_at=None,
        )


class Speech:
    async def synthesize(self, text, destination):
        with wave.open(str(destination), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * 80)
        return destination


async def test_history_retains_payload_and_individual_priority_after_group_playback(tmp_path):
    async with connect(
        tmp_path,
        Classifier(),
        Speech(),
        max_provider_calls=20,
        grouping_delay_seconds=0,
    ) as client:

        async def submit(priority, text, **extra):
            response = await client.post(
                STANDARD,
                json={
                    "app": "Messages",
                    "sender": "Sam",
                    "title": str(priority),
                    "body": text,
                    **extra,
                },
            )
            assert response.status_code == 202
            return response.json()["event_id"]

        async def wait_ready(member_count):
            async with asyncio.timeout(3):
                while True:
                    state = (await client.get("/api/state")).json()
                    if any(
                        item["status"] == "ready" and item["notification_count"] == member_count
                        for item in state["items"]
                    ):
                        return
                    await asyncio.sleep(0.01)

        discarded = [await submit(priority, f"discard-content-{priority}") for priority in (1, 2)]
        first = await submit(3, "group-body-first")
        await wait_ready(1)
        second = await submit(4, "group-body-second")
        await wait_ready(2)
        response = await client.get(LOG)
        assert "discard-content-" in response.text
        entries = {item["event_id"]: item for item in response.json()["entries"]}
        assert all(
            entries[event_id]["queue_status"] == "discarded"
            and entries[event_id]["payload"] is not None
            for event_id in discarded
        )
        assert entries[first]["payload"]["body"] == "group-body-first"
        assert entries[second]["payload"]["body"] == "group-body-second"
        assert entries[first]["queue_status"] == entries[second]["queue_status"] == "ready"
        assert entries[first]["priority"] == 3 and entries[second]["priority"] == 4
        assert [entries[event_id]["priority"] for event_id in discarded] == [1, 2]

        delivery = (await client.post("/api/delivery/claim", json={"device_id": "test"})).json()[
            "delivery"
        ]
        assert delivery["notification_count"] == 2
        ack = await client.post(
            f"/api/delivery/{delivery['lease_id']}/ack",
            json={"device_id": "test", "outcome": "played"},
        )
        assert ack.json()["status"] == "played"
        for event_id in [*discarded, first, second]:
            await submit(3, "replay-never-reappears", event_id=event_id)

        response = await client.get(LOG)
        assert "group-body-" in response.text and "replay-never-reappears" in response.text
        assert response.json()["entries"]
        for entry in response.json()["entries"]:
            assert entry["payload"] is not None
            assert entry["queue_status"] == (
                "discarded" if entry["event_id"] in discarded else "played"
            )


@pytest.mark.parametrize("include_subtitle", [True, False])
@pytest.mark.parametrize("escaped_json", [True, False])
async def test_esp_log_preserves_received_keys_text_and_local_date(
    client, include_subtitle, escaped_json
):
    packet = {
        "app": "com.apple.MobileSMS",
        "title": "Eli Schiffler",
        "message": 'Come over for dinner at 5 pm 🙂\n  Bring "snacks" | please <img src=x>',
        "date": "20261114T140830",
    }
    if include_subtitle:
        packet["subtitle"] = ""
    event_id = str(uuid4())
    response = await client.post(
        ESP,
        content=json.dumps(packet, ensure_ascii=escaped_json).encode("utf-8"),
        headers=AUTH | {"Content-Type": "application/json", "X-Event-ID": event_id},
    )
    assert response.status_code == 202
    entry = (await client.get(LOG)).json()["entries"][0]
    assert entry["payload"] == packet
    assert entry["event_id"] == event_id
    assert not entry["payload_redacted"]
    assert (
        not {"event_id", "sender", "body", "received_at", "content_hidden"}
        & entry["payload"].keys()
    )
    item = (await client.get("/api/state")).json()["items"][0]
    assert item["received_at"] == "2026-11-14T22:08:30Z"


async def test_esp_received_payload_redacts_secrets_without_expanding_emoji(client):
    packet = {
        "app": "com.apple.MobileSMS",
        "title": "Sam 🙂",
        "subtitle": "Private code",
        "message": f'  🙂 Password: "secret words". {TOKEN}',
        "date": "20261114T140830",
    }
    response = await client.post(ESP, json=packet, headers=AUTH)
    assert response.status_code == 202
    entry = (await client.get(LOG)).json()["entries"][0]
    assert entry["payload_redacted"]
    assert entry["payload"] == packet | {"message": "  🙂 Password: redacted. redacted"}


@pytest.mark.parametrize("wire_format", ["json", "text"])
async def test_original_esp_payload_stays_in_history_after_discard_playback_and_retry(
    tmp_path, wire_format
):
    async with connect(
        tmp_path, Classifier(), Speech(), max_provider_calls=10, grouping_window_seconds=0
    ) as client:
        requests = []
        for priority in (2, 3):
            packet = {
                "app": "com.apple.MobileSMS",
                "title": str(priority),
                "message": f"original-wire-content-{priority} 🙂",
                "date": "20261114T140830",
            }
            payload = json.dumps(packet) if wire_format == "json" else " | ".join(packet.values())
            headers = AUTH | {
                "Content-Type": "application/json" if wire_format == "json" else "text/plain"
            }
            response = await client.post(ESP, content=payload, headers=headers)
            assert response.status_code == 202
            requests.append((payload, headers))
        async with asyncio.timeout(3):
            while True:
                state = (await client.get("/api/state")).json()
                if state["counts"]["ready"] == 1 and state["counts"]["discarded"] == 1:
                    break
                await asyncio.sleep(0.01)
        log = await client.get(LOG)
        assert "original-wire-content-2" in log.text
        assert "original-wire-content-3" in log.text
        delivery = (await client.post("/api/delivery/claim", json={"device_id": "test"})).json()[
            "delivery"
        ]
        response = await client.post(
            f"/api/delivery/{delivery['lease_id']}/ack",
            json={"device_id": "test", "outcome": "played"},
        )
        assert response.status_code == 200
        for payload, headers in requests:
            assert (await client.post(ESP, content=payload, headers=headers)).status_code == 202
        log = await client.get(LOG)
        assert "original-wire-content" in log.text
        assert all(entry["payload"] is not None for entry in log.json()["entries"])


async def test_history_survives_restart_and_cursor_pages_do_not_repeat(tmp_path):
    async with connect(tmp_path) as client:
        for i in range(4):
            assert (
                await client.post(STANDARD, json={"app": "Messages", "body": f"History {i}"})
            ).status_code == 202
        first = (await client.get(LOG + "?limit=2")).json()
        assert first["total"] == 4 and len(first["entries"]) == 2
        second = (await client.get(LOG + f"?limit=2&before={first['next_cursor']}")).json()
        assert second["next_cursor"] is None
        assert [e["payload"]["body"] for e in first["entries"] + second["entries"]] == [
            f"History {i}" for i in (3, 2, 1, 0)
        ]
    async with connect(tmp_path) as client:
        restored = (await client.get(LOG)).json()
        assert restored["total"] == 4
        assert [e["id"] for e in restored["entries"]] == [
            e["id"] for e in first["entries"] + second["entries"]
        ]


def test_persistent_history_is_bounded_and_priority_survives_fast_completion(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    store = QueueStore(settings)
    store.initialize()
    for i in range(1003):
        store.record_ingress(
            {
                "id": str(uuid4()),
                "received_at": datetime.now(timezone.utc),
                "method": "POST",
                "path": ESP,
                "status_code": 401,
                "duration_ms": 1,
                "ordinal": i,
            }
        )
    result = store.ingress_history()
    assert result["total"] == 1000 and len(result["entries"]) == 100
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ingress_history").fetchone()[0] == 1000
        first = json.loads(
            connection.execute(
                "SELECT record_json FROM ingress_history ORDER BY sequence LIMIT 1"
            ).fetchone()[0]
        )
        assert first["ordinal"] == 3
