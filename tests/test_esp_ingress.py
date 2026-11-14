import asyncio
import wave
from uuid import uuid4

import httpx
import pytest

from contracts import ClassificationResult, Settings
from server.app import create_app

TOKEN = "test-esp-token-for-local-unit-tests-only-12345"
PACKET = "com.apple.MobileSMS | Eli Schiffler | This is an example text | 20261114T125641"
HEADERS = {"Content-Type": "text/plain; charset=utf-8", "Authorization": f"Bearer {TOKEN}"}
JSON_HEADERS = HEADERS | {"Content-Type": "application/json; charset=utf-8"}
JSON_PACKET = {
    "app": "com.apple.MobileSMS",
    "title": "Matthew Cheese Ellis",
    "message": "T minus 10 min",
    "date": "20261114T130105",
}


class Classifier:
    def __init__(self):
        self.notifications = []

    async def classify(self, notification):
        self.notifications.append(notification)
        return ClassificationResult(
            priority=3,
            reason="Personal message",
            spoken_text="An example message.",
            evidence="sufficient",
            deadline_at=None,
        )


class Speech:
    async def synthesize(self, text, destination):
        with wave.open(str(destination), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * 80)
        return destination


@pytest.fixture
async def client(tmp_path):
    classifier = Classifier()
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        classifier_provider="demo",
        tts_provider="macos",
        esp_ingest_token=TOKEN,
        esp_timezone="America/Los_Angeles",
        grouping_window_seconds=0,
    )
    app = create_app(settings, classifier=classifier, speech=Speech())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as http,
    ):
        yield http, classifier


async def ready(http, count):
    async with asyncio.timeout(3):
        while True:
            state = (await http.get("/api/state")).json()
            if state["counts"]["ready"] == count:
                return state
            await asyncio.sleep(0.01)


async def test_packet_timestamp_idempotency_and_device_supplied_event_id(client):
    http, classifier = client
    first = await http.post("/api/esp/notifications", content=PACKET, headers=HEADERS)
    assert first.status_code == 202
    state = await ready(http, 1)
    assert state["items"][0]["received_at"] == "2026-11-14T20:56:41Z"
    assert classifier.notifications[0].sender == "Eli Schiffler"
    assert classifier.notifications[0].body == "This is an example text"
    duplicate = await http.post("/api/esp/notifications", content=PACKET, headers=HEADERS)
    assert duplicate.json() == {"event_id": first.json()["event_id"], "status": "ready"}
    assert len(classifier.notifications) == 1
    separate_id = str(uuid4())
    separate = await http.post(
        "/api/esp/notifications", content=PACKET, headers=HEADERS | {"X-Event-ID": separate_id}
    )
    assert separate.json()["event_id"] == separate_id
    await ready(http, 2)
    assert len(classifier.notifications) == 2


async def test_esp_json_timestamp_and_device_supplied_event_id(client):
    http, classifier = client
    device_event_id = str(uuid4())
    headers = JSON_HEADERS | {"X-Event-ID": device_event_id}
    response = await http.post("/api/esp/notifications", json=JSON_PACKET, headers=headers)
    assert response.status_code == 202
    assert response.json()["event_id"] == device_event_id
    state = await ready(http, 1)
    assert state["items"][0]["received_at"] == "2026-11-14T21:01:05Z"
    [notification] = classifier.notifications
    assert notification.sender == "Matthew Cheese Ellis"
    assert notification.body == "T minus 10 min"
    duplicate = await http.post("/api/esp/notifications", json=JSON_PACKET, headers=headers)
    assert duplicate.json() == {"event_id": device_event_id, "status": "ready"}
    assert len(classifier.notifications) == 1


async def test_esp_json_requires_same_bearer_token(client):
    http, classifier = client
    response = await http.post("/api/esp/notifications", json=JSON_PACKET)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert not classifier.notifications


async def test_actual_source_time_orders_delayed_esp_packets(client):
    http, _ = client
    late = await http.post(
        "/api/esp/notifications", content=PACKET.replace("125641", "125700"), headers=HEADERS
    )
    await ready(http, 1)
    early = await http.post("/api/esp/notifications", content=PACKET, headers=HEADERS)
    state = await ready(http, 2)
    assert [item["id"] for item in state["items"]] == [
        early.json()["event_id"],
        late.json()["event_id"],
    ]
    lease = (await http.post("/api/delivery/claim", json={"device_id": "test-pager"})).json()[
        "delivery"
    ]
    assert lease["message_id"] == early.json()["event_id"]
    assert lease["received_at"] == "2026-11-14T20:56:41Z"


async def test_transport_line_terminator_keeps_packet_identity(client):
    http, _ = client
    first = await http.post("/api/esp/notifications", content=PACKET, headers=HEADERS)
    repeated = await http.post("/api/esp/notifications", content=PACKET + "\r\n", headers=HEADERS)
    assert first.status_code == repeated.status_code == 202
    assert first.json()["event_id"] == repeated.json()["event_id"]


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic invalid"])
async def test_unauthorized_esp_request_does_not_enter_queue(client, authorization):
    http, _ = client
    headers = {"Content-Type": "text/plain"}
    if authorization is not None:
        headers["Authorization"] = authorization
    response = await http.post("/api/esp/notifications", content=PACKET, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert (await http.get("/api/state")).json()["items"] == []


@pytest.mark.parametrize(
    "body,headers,status",
    [
        (PACKET, HEADERS | {"Content-Type": "application/xml"}, 415),
        (PACKET, JSON_HEADERS, 422),
        ('{"private":"details"}', JSON_HEADERS, 422),
        (b"\xff", JSON_HEADERS, 422),
        ('{"message":"' + "x" * 32769 + '"}', JSON_HEADERS, 413),
        (PACKET, HEADERS | {"X-Event-ID": "invalid-private-id"}, 422),
        ("sensitive-private-invalid-packet", HEADERS, 422),
        (PACKET.replace("20261114", "20260230"), HEADERS, 422),
        (b"\xff", HEADERS, 422),
        ("x" * 32769, HEADERS, 413),
    ],
)
async def test_invalid_esp_packets_return_safe_errors(client, body, headers, status):
    http, classifier = client
    response = await http.post("/api/esp/notifications", content=body, headers=headers)
    assert response.status_code == status
    assert "Eli" not in response.text and "private" not in response.text
    assert not classifier.notifications


async def test_production_esp_path_fails_closed_without_token(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        environment="production",
        public_host="pager.example.com",
        openai_api_key="fake-test-key",
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http,
    ):
        response = await http.post(
            "https://pager.example.com/api/esp/notifications", content=PACKET, headers=HEADERS
        )
        assert response.status_code == 503


@pytest.mark.parametrize(
    "values",
    [
        {"esp_timezone": "Unknown/Zone"},
        {"esp_ingest_token": "short"},
        {"esp_ingest_token": "with spaces " * 5},
    ],
)
def test_invalid_esp_configuration(values):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **values)
