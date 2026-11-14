"""Regressions for device-only ingestion, Unicode speech, and ESP subtitles."""

import asyncio
import json

import httpx
import pytest

from contracts import ClassificationResult, NotificationInput, Settings
from contracts.esp import parse_esp_json
from intelligence.common import clean_spoken_text
from intelligence.formatting import format_notification_for_speech
from server.app import create_app


@pytest.mark.parametrize(
    "glyph, name",
    [
        ("🙂", "slightly smiling face"),
        ("😊", "smiling face with smiling eyes"),
        ("👍🏽", "thumbs up medium skin tone"),
        ("👨‍👩‍👧‍👦", "family man woman girl boy"),
        ("🇺🇸", "United States"),
        ("❤️", "red heart"),
    ],
)
def test_emoji_names_are_complete_and_idempotent(glyph, name):
    output = clean_spoken_text(f"Meet at 4:30 {glyph}z")
    assert output == f"Meet at 4:30 {name} z"
    assert clean_spoken_text(output) == output


def test_long_emoji_preview_stays_bounded_and_hidden_subtitle_is_not_spoken():
    result = ClassificationResult(
        priority=3,
        reason="Personal message",
        spoken_text="Summary",
        evidence="sufficient",
        deadline_at=None,
    )
    notification = NotificationInput(app="Messages", subtitle="Family 🙂", body="🙂" * 100)
    spoken = format_notification_for_speech(notification, result).spoken_text
    assert len(spoken) <= 350
    assert spoken.endswith(". Summary: Summary")
    hidden = notification.model_copy(update={"content_hidden": True})
    assert "Family" not in format_notification_for_speech(hidden, result).spoken_text
    assert clean_spoken_text("z :slightly_smiling_face:") == "z :slightly_smiling_face:"


@pytest.mark.parametrize("production", [False, True])
async def test_manual_ingestion_unavailable_in_default_app_and_production(tmp_path, production):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        environment="production" if production else "local",
        public_host="pager.example.com" if production else None,
        openai_api_key="fake-test-key",
        max_provider_calls=0,
    )
    # Even the isolated-test hook cannot enable this route on production.
    app = create_app(settings, allow_test_ingestion=production)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://pager.example.com" if production else "http://localhost",
        ) as client,
    ):
        response = await client.post("/api/notifications", json={"app": "Messages", "body": "Hi"})
        assert response.status_code == 405
        assert "/api/notifications" not in {getattr(route, "path", None) for route in app.routes}
        assert (await client.get("/api/state")).json()["items"] == []
        page_response = await client.get("/")
        assert page_response.headers["cache-control"] == "no-store"
        assert (await client.get("/app.js")).headers["cache-control"] == "no-store"
        page = page_response.text
        assert 'id="custom"' not in page and 'id="samples"' not in page
        assert "Stay reachable" not in page
        assert 'id="connection"' in page


@pytest.mark.parametrize("escaped_json", [False, True])
async def test_esp_subtitle_and_emoji_reach_classification_logs_and_speech(tmp_path, escaped_json):
    seen, heard = [], []

    class Classifier:
        async def classify(self, notification):
            seen.append(notification)
            return ClassificationResult(
                priority=3,
                reason="Personal message",
                spoken_text="Summary",
                evidence="sufficient",
                deadline_at=None,
            )

    class Speech:
        async def synthesize(self, text, destination):
            heard.append(text)
            raise RuntimeError("Stop after recording TTS input")

    token = "test-emoji-esp-token-01234567890123456789"
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        esp_ingest_token=token,
        max_provider_calls=5,
        grouping_window_seconds=0,
    )
    app = create_app(settings, classifier=Classifier(), speech=Speech())
    packet = {
        "app": "com.apple.MobileSMS",
        "title": "Sam",
        "subtitle": "Dinner plans",
        "message": "Can you come? 🙂",
        "date": "20261114T130105",
    }
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost",
        ) as client,
    ):
        response = await client.post(
            "/api/esp/notifications",
            content=json.dumps(packet, ensure_ascii=escaped_json).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 202
        async with asyncio.timeout(3):
            while not heard:
                await asyncio.sleep(0.01)
        assert seen[0].body == "Can you come? 🙂"
        assert seen[0].subtitle == "Dinner plans"
        assert heard == [
            "New message on Messages from Sam: 'Dinner plans. Can you come? slightly smiling face'"
        ]
        entry = (await client.get("/api/ingress-log")).json()["entries"][0]
        assert entry["payload"]["subtitle"] == "Dinner plans"
        assert entry["payload"] == packet
        assert seen[0].received_at.isoformat() == "2026-11-14T21:01:05+00:00"


def test_subtitle_validation_and_retry_identity():
    packet = {
        "app": "com.apple.MobileSMS",
        "title": "Sam",
        "message": "Hi",
        "date": "20261114T130105",
    }

    def parse(**extra):
        return parse_esp_json(json.dumps(packet | extra), timezone_name="America/Los_Angeles")

    assert parse().subtitle == ""
    assert parse().event_id == parse(subtitle="").event_id
    assert parse(subtitle="A").event_id != parse(subtitle="B").event_id
    for invalid in (None, 123, [], "x" * 257):
        with pytest.raises(ValueError):
            parse(subtitle=invalid)
