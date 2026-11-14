import asyncio
import sqlite3
import wave
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from starlette.responses import FileResponse

from contracts import ClassificationResult, Settings
from server.app import create_app


class Classifier:
    async def classify(self, notification):
        return ClassificationResult(
            priority=int(notification.title),
            reason="Test",
            spoken_text="Test preview",
            evidence="sufficient",
            deadline_at=None,
        )


class Speech:
    async def synthesize(self, text, destination):
        with wave.open(str(destination), "wb") as file:
            file.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            file.writeframes(b"\x00\x00" * 80)
        return destination


@asynccontextmanager
async def connect(tmp_path):
    settings = Settings(
        _env_file=None, data_dir=tmp_path, max_provider_calls=30, grouping_window_seconds=0
    )
    app = create_app(settings, classifier=Classifier(), speech=Speech(), allow_test_ingestion=True)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://localhost",
        ) as client,
    ):
        yield client


async def enqueue(client, priority):
    response = await client.post(
        "/api/notifications",
        json={"app": "Messages", "title": str(priority), "body": "Offline test only"},
    )
    assert response.status_code == 202
    event_id = response.json()["event_id"]
    async with asyncio.timeout(3):
        while True:
            state = (await client.get("/api/state")).json()
            if any(x["id"] == event_id and x["status"] == "ready" for x in state["items"]):
                return event_id
            await asyncio.sleep(0.01)


async def test_pi_one_message_poll_download_ack_and_lost_ack_retry(tmp_path):
    async with connect(tmp_path) as c:
        assert (await c.get("/api/pi/status")).json()["last_seen"] is None
        lower = await enqueue(c, 3)
        urgent = await enqueue(c, 5)
        assert (await c.get("/status")).json() == {
            "items": [{"id": urgent, "priority": 5}],
            "led_on": True,
        }
        assert (await c.get("/api/state")).json()["counts"]["leased"] == 0
        assert (await c.post("/ack", json={"ids": [urgent]})).status_code == 409
        assert (await c.get("/audio/" + lower)).status_code == 409
        assert (await c.get("/api/state")).json()["counts"]["leased"] == 0
        audio = await c.get("/audio/" + urgent)
        assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
        assert audio.content[:4] == b"RIFF"
        assert (await c.get("/api/pi/status")).json()["transfers"][0]["status"] == "awaiting_ack"
        assert (await c.get("/status")).json()["items"][0]["id"] == urgent
        assert (await c.get("/audio/" + lower)).status_code == 409
        assert (await c.post("/ack", json={"ids": [lower]})).status_code == 409
        ack = await c.post("/ack", json={"ids": [urgent]})
        assert ack.status_code == 200
        assert (await c.post("/ack", json={"ids": [urgent]})).json() == ack.json()
        assert (await c.get("/api/pi/status")).json()["transfers"][0]["status"] == "acknowledged"
        assert (await c.get("/status")).json() == {
            "items": [{"id": lower, "priority": 3}],
            "led_on": False,
        }
        assert (await c.get("/api/state")).json()["counts"]["played"] == 1


async def test_active_pi_item_not_interrupted_by_new_emergency(tmp_path):
    async with connect(tmp_path) as c:
        first = await enqueue(c, 3)
        assert (await c.get("/audio/" + first)).status_code == 200
        urgent = await enqueue(c, 5)
        status = (await c.get("/status")).json()
        assert status["items"][0]["id"] == first
        assert status["led_on"] is True
        assert (await c.get("/audio/" + urgent)).status_code == 409
        assert (await c.post("/ack", json={"ids": [first]})).status_code == 200
        assert (await c.get("/status")).json()["items"][0]["id"] == urgent


async def test_partial_download_and_batch_ack_are_rejected(tmp_path):
    async with connect(tmp_path) as c:
        event = await enqueue(c, 3)
        assert (await c.get("/audio/" + event, headers={"Range": "bytes=0-10"})).status_code == 416
        assert (await c.get("/api/state")).json()["counts"]["leased"] == 0
        for ids in ([], [event, str(uuid4())], ["bad"]):
            assert (await c.post("/ack", json={"ids": ids})).status_code == 422
        assert (await c.post("/ack", content=b"x" * 1025)).status_code == 413


async def test_expired_pi_download_can_retry_without_losing_item(tmp_path):
    async with connect(tmp_path) as c:
        event = await enqueue(c, 4)
        assert (await c.get("/audio/" + event)).status_code == 200
        with sqlite3.connect(tmp_path / "pager.sqlite3") as db:
            db.execute("UPDATE delivery_leases SET expires_at=0")
        assert (await c.get("/api/pi/status")).json()["transfers"][0]["status"] == "expired"
        assert (await c.post("/ack", json={"ids": [event]})).status_code == 409
        assert (await c.get("/status")).json()["items"][0]["id"] == event
        assert (await c.get("/audio/" + event)).status_code == 200
        assert (await c.post("/ack", json={"ids": [event]})).status_code == 200
        assert (await c.get("/status")).json() == {"items": [], "led_on": False}


async def test_failed_stream_keeps_item_and_releases_download_lock(tmp_path, monkeypatch):
    async with connect(tmp_path) as c:
        event = await enqueue(c, 3)

        async def broken(self, scope, receive, send):
            raise OSError("Synthetic interrupted transfer")

        with monkeypatch.context() as patch:
            patch.setattr(FileResponse, "__call__", broken)
            assert (await c.get("/audio/" + event)).status_code == 500
        assert (await c.get("/api/pi/status")).json()["transfers"][0]["status"] == "failed"
        assert (await c.post("/ack", json={"ids": [event]})).status_code == 409
        assert (await c.get("/audio/" + event)).status_code == 200
        assert (await c.post("/ack", json={"ids": [event]})).status_code == 200


async def test_pi_transfer_and_ack_state_survive_server_restart(tmp_path):
    async with connect(tmp_path) as c:
        event = await enqueue(c, 3)
        assert (await c.get("/audio/" + event)).status_code == 200
    async with connect(tmp_path) as c:
        assert (await c.get("/api/pi/status")).json()["transfers"][0]["status"] == "awaiting_ack"
        assert (await c.post("/ack", json={"ids": [event]})).status_code == 200
    async with connect(tmp_path) as c:
        assert (await c.post("/ack", json={"ids": [event]})).status_code == 200
        assert (await c.get("/api/state")).json()["counts"]["played"] == 1


async def test_missing_audio_fails_the_item_without_claiming_another(tmp_path):
    async with connect(tmp_path) as c:
        low = await enqueue(c, 3)
        high = await enqueue(c, 5)
        (tmp_path / "audio" / f"{high}.wav").unlink()
        assert (await c.get("/audio/" + high)).status_code == 409
        state = (await c.get("/api/state")).json()
        assert state["counts"]["failed"] == 1 and state["counts"]["leased"] == 0
        assert (await c.get("/status")).json()["items"][0]["id"] == low


async def test_led_only_lights_for_priority_five_until_last_urgent_ack(tmp_path):
    async with connect(tmp_path) as c:
        assert (await c.get("/status")).json()["led_on"] is False
        await enqueue(c, 3)
        await enqueue(c, 4)
        assert (await c.get("/status")).json()["led_on"] is False
        first = await enqueue(c, 5)
        second = await enqueue(c, 5)
        assert (await c.get("/status")).json()["led_on"] is True
        assert (await c.post("/ack", json={"ids": [first]})).status_code == 409
        assert (await c.get("/status")).json()["led_on"] is True
        assert (await c.get("/audio/" + first)).status_code == 200
        assert (await c.get("/status")).json()["led_on"] is True
        assert (await c.post("/ack", json={"ids": [first]})).status_code == 200
        assert (await c.get("/status")).json()["led_on"] is True
        assert (await c.get("/audio/" + second)).status_code == 200
        assert (await c.post("/ack", json={"ids": [second]})).status_code == 200
        assert (await c.get("/status")).json()["led_on"] is False


def test_pi_gpio_adapter_never_lights_for_count_or_connection_errors():
    from bridges.pi.led import update_led

    class LED:
        lit = False

        def on(self):
            self.lit = True

        def off(self):
            self.lit = False

    led = LED()
    update_led(led, {"led_on": True, "items": []})
    assert led.lit is True
    for status in (
        None,
        {},
        {"led_on": "true"},
        {"led_on": 1},
        {"led_on": False, "items": [{"priority": 4}] * 50},
    ):
        update_led(led, status)
        assert led.lit is False
