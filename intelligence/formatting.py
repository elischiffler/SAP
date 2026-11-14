"""Format pager speech from the original notification."""

import re

from contracts import ClassificationResult, NotificationInput
from contracts.app_names import display_app_name

from .common import clean_spoken_text, redact_sensitive_text

_SPOKEN_LIMIT = 350
_MESSAGING_APPS = frozenset(
    {
        "discord",
        "facebook messenger",
        "google messages",
        "imessage",
        "instagram",
        "messages",
        "messenger",
        "microsoft teams",
        "signal",
        "slack",
        "sms",
        "teams",
        "telegram",
        "whatsapp",
    }
)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_SECRET_LABEL = (
    r"(?:password|passcode|PIN|OTP|(?:verification|security|authentication|login) code"
    r"|one[- ]time (?:passcode|code|password))"
)
_QUOTED_SECRET = re.compile(
    rf"""(?ix)(\b{_SECRET_LABEL}\s*(?::|=|\bis\b)\s*)(?:"[^"]+"|'[^']+'|“[^”]+”|‘[^’]+’)"""
)
_NAMED_DIGIT_SECRET = re.compile(
    rf"(?i)(\b{_SECRET_LABEL}\b\s*(?:[:=]\s*|is\s+)?)(?:\d[ -]?){{3,7}}\d(?!\d)"
)
_LEADING_DIGIT_SECRET = re.compile(
    rf"(?i)\b(?:\d[ -]?){{3,7}}\d(?=\s+is\s+(?:(?:your|the|a)\s+)?{_SECRET_LABEL}\b)"
)


def redact_preview_secrets(text: str) -> str:
    """Keep original text except for sensitive-value redaction."""
    text = _QUOTED_SECRET.sub(r"\1redacted", text)
    text = _NAMED_DIGIT_SECRET.sub(r"\1redacted", text)
    text = _LEADING_DIGIT_SECRET.sub("redacted", text)
    return redact_sensitive_text(text)


def _safe_preview(text: str) -> str:
    text = " ".join(_CONTROL_CHARACTERS.sub(" ", text).split())
    return clean_spoken_text(redact_preview_secrets(text))


def _source_label(text: str, limit: int) -> str:
    label = _safe_preview(text)
    if len(label) <= limit:
        return label
    suffix = " (label shortened)"
    return label[: limit - len(suffix)].rstrip() + suffix


def _display_app(app: str) -> str:
    return display_app_name(app)


def format_notification_for_speech(
    notification: NotificationInput, result: ClassificationResult
) -> ClassificationResult:
    """Keep the classification and build the exact text to send to the speech provider."""
    if result.priority <= 2:
        return result

    app = _source_label(_display_app(notification.app), 100) or "an unknown app"
    is_message = app.casefold() in _MESSAGING_APPS
    prefix = f"New {'message' if is_message else 'notification'} on {app}"

    sender = _source_label(notification.sender or "", 120)
    if sender:
        prefix += f" from {sender}"
    elif is_message:
        prefix += " from an unknown sender"

    preview = ""
    if not notification.content_hidden and result.evidence == "sufficient":
        # The title can repeat the sender label in mirrored notifications.
        subtitle = _safe_preview(notification.subtitle)
        body = _safe_preview(notification.body)
        preview = ". ".join(dict.fromkeys(part for part in (subtitle, body) if part))
        preview = preview or _safe_preview(notification.title)
    if not preview:
        spoken_text = f"{prefix}. Content unavailable. Check your phone."
    else:
        quote_start = f"{prefix}: '"
        if len(quote_start) + len(preview) + 1 > _SPOKEN_LIMIT:
            # Reuse the classification response: no second summarization request.
            # Never quote a paraphrase or truncate a summary mid-negation/deadline.
            summary = _safe_preview(result.spoken_text or "")
            candidate = f"{prefix}. Summary: {summary}"
            if summary and len(candidate) <= _SPOKEN_LIMIT:
                spoken_text = candidate
            else:
                spoken_text = f"{prefix}. Long message. Summary unavailable. Check your phone."
        else:
            spoken_text = f"{quote_start}{preview}'"

    fields = result.model_dump()
    fields["spoken_text"] = spoken_text
    return ClassificationResult.model_validate(fields)
