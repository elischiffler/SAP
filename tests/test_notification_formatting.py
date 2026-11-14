import time

import pytest
from fastapi.testclient import TestClient

from contracts import ClassificationResult, NotificationInput, Settings
from intelligence.common import clean_spoken_text
from intelligence.formatting import format_notification_for_speech
from server.app import create_app


def classification(priority=4, evidence="sufficient"):
    return ClassificationResult(
        priority=priority,
        reason="There is a request with a deadline.",
        spoken_text="GPT invented summary." if priority >= 3 else None,
        evidence=evidence,
        deadline_at="2026-11-14T23:10:00+00:00",
    )


def test_source_preview_replaces_model_text_and_preserves_classification():
    original_result = classification()
    notification = NotificationInput(
        app="iMessage", sender="Sam", title="Sam", body="Want dinner tonight?"
    )
    result = format_notification_for_speech(notification, original_result)
    assert result.spoken_text == "New message on iMessage from Sam: 'Want dinner tonight?'"
    assert result.model_dump(exclude={"spoken_text"}) == original_result.model_dump(
        exclude={"spoken_text"}
    )
    assert original_result.spoken_text == "GPT invented summary."


@pytest.mark.parametrize(
    "app,sender,expected",
    [
        ("com.apple.MobileSMS", None, "New message on Messages from an unknown sender"),
        ("Messages", " ", "New message on Messages from an unknown sender"),
        ("Calendar", None, "New notification on Calendar"),
        ("Calendar", "Work calendar", "New notification on Calendar from Work calendar"),
    ],
)
def test_source_display_and_sender_fallback(app, sender, expected):
    notification = NotificationInput(app=app, sender=sender, title="Dinner tonight")
    result = format_notification_for_speech(notification, classification())
    assert result.spoken_text == f"{expected}: 'Dinner tonight'"


@pytest.mark.parametrize(
    "hidden,body,title,evidence",
    [
        (True, "private body marker", "private title marker", "sufficient"),
        (False, "private body marker", "private title marker", "insufficient"),
        (False, "\x00  ", " ", "sufficient"),
    ],
)
def test_unavailable_previews_never_reveal_title_or_body(hidden, body, title, evidence):
    notification = NotificationInput(
        app="Messages", sender="Riley", title=title, body=body, content_hidden=hidden
    )
    result = format_notification_for_speech(notification, classification(3, evidence))
    assert result.spoken_text == (
        "New message on Messages from Riley. Content unavailable. Check your phone."
    )


@pytest.mark.parametrize("priority", [1, 2])
def test_discarded_notification_has_no_speech(priority):
    notification = NotificationInput(app="Shop", body="Sale today")
    assert (
        format_notification_for_speech(notification, classification(priority)).spoken_text is None
    )


def test_long_preview_uses_classification_summary_with_bounded_label_sizes():
    notification = NotificationInput(
        app="A" * 100, sender="B" * 120, body="Please bring the projector tomorrow. " * 60
    )
    spoken = format_notification_for_speech(notification, classification()).spoken_text
    assert len(spoken) <= 350
    assert spoken.endswith(". Summary: GPT invented summary.")
    assert "Please bring the projector tomorrow." not in spoken


def test_redaction_expansion_keeps_source_labels_and_preview_within_bound():
    notification = NotificationInput(app="OTP: x " * 14, sender="OTP: y " * 17, body="Z" * 4096)
    spoken = format_notification_for_speech(notification, classification()).spoken_text
    assert len(spoken) <= 350
    assert "OTP: x" not in spoken and "OTP: y" not in spoken
    assert spoken.count("(label shortened)") == 2
    assert spoken.endswith(". Summary: GPT invented summary.")


def test_redacts_secrets_and_preserves_time_and_negation():
    notification = NotificationInput(
        app="Messages",
        sender="Avery",
        body=(
            'Please do not leave before 4:30. Password: "several secret words". '
            "246810 is your verification code. Authentication code 7 8 9 1 2 3. "
            "The account number is 123456789012345. "
            "Use https://example.test/path."
        ),
    )
    spoken = format_notification_for_speech(notification, classification()).spoken_text
    for secret in (
        "several",
        "secret words",
        "246810",
        "7 8 9 1 2 3",
        "123456789012345",
        "example.test",
    ):
        assert secret not in spoken
    assert "do not leave before 4:30" in spoken
    assert spoken.count("redacted") == 5


@pytest.mark.parametrize(
    "body,preview",
    [
        ("Password: marigold", "Password: redacted"),
        ("Password: redacted-secret", "Password: redacted"),
        ('Password: "hazel leaf"', "Password: redacted"),
        ("Your verification code is 123 456", "Your verification code is redacted"),
    ],
)
def test_speech_provider_resanitization_preserves_quoted_format(body, preview):
    notification = NotificationInput(app="Messages", sender="Avery", body=body)
    spoken = format_notification_for_speech(notification, classification()).spoken_text
    assert spoken == f"New message on Messages from Avery: '{preview}'"
    assert spoken == clean_spoken_text(spoken)


@pytest.mark.parametrize("long", [False, True])
def test_server_uses_one_classification_for_short_quote_or_long_summary(tmp_path, long):
    heard = []
    classified = []

    class MockClassifier:
        async def classify(self, notification):
            classified.append(notification.body)
            return classification()

    class MockSpeech:
        async def synthesize(self, text, destination):
            heard.append(text)
            raise RuntimeError("stop after capturing the speech input")

    settings = Settings(data_dir=tmp_path, max_provider_calls=5)
    app = create_app(
        settings, allow_test_ingestion=True, classifier=MockClassifier(), speech=MockSpeech()
    )
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/api/notifications",
            json={
                "app": "iMessage",
                "sender": "Sam",
                "body": "Want dinner tonight?" * (100 if long else 1),
            },
        )
        assert response.status_code == 202
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = client.get("/api/state").json()
            if state["counts"]["failed"]:
                break
            time.sleep(0.01)
        expected = (
            "New message on iMessage from Sam. Summary: GPT invented summary."
            if long
            else "New message on iMessage from Sam: 'Want dinner tonight?'"
        )
        assert len(classified) == 1
        assert heard == [expected]
        assert state["items"][0]["spoken_text"] == heard[0]


@pytest.mark.parametrize("summary", ["", "X" * 350])
def test_unusable_long_summary_does_not_cut_off_critical_details(summary):
    result = classification().model_copy(update={"spoken_text": summary})
    notification = NotificationInput(app="Messages", body="Long original. " * 100)
    spoken = format_notification_for_speech(notification, result).spoken_text
    assert spoken.endswith("Long message. Summary unavailable. Check your phone.")
    assert len(spoken) <= 350


def test_long_summary_keeps_late_correction_and_redacts_secrets():
    summary = "Sam says do not go to Gate 4; meet at Gate 9 at 5:30. PIN: 123456."
    result = classification().model_copy(update={"spoken_text": summary})
    notification = NotificationInput(
        app="Messages",
        sender="Sam",
        body="Original plan at Gate 4. " * 80
        + "Correction: do not go to Gate 4; meet at Gate 9 at 5:30. PIN: 123456.",
    )
    spoken = format_notification_for_speech(notification, result).spoken_text
    assert ". Summary: Sam says do not go to Gate 4; meet at Gate 9 at 5:30." in spoken
    assert "123456" not in spoken
    assert "'" not in spoken


def test_quote_threshold_includes_source_introduction():
    prefix = "New message on Messages from Sam: '"
    body = "a" * (350 - len(prefix) - 1)
    notification = NotificationInput(app="Messages", sender="Sam", body=body)
    assert (
        format_notification_for_speech(notification, classification()).spoken_text
        == prefix + body + "'"
    )
    longer = notification.model_copy(update={"body": body + "b"})
    assert ". Summary:" in format_notification_for_speech(longer, classification()).spoken_text
