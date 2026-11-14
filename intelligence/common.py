"""Provider failures and speech text normalization."""

import re

import emoji
from openai import AsyncOpenAI

from contracts import Settings


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def openai_client(settings: Settings) -> AsyncOpenAI:
    secret = settings.openai_api_key
    key = secret.get_secret_value().strip() if secret is not None else ""
    if not key:
        raise ProviderError("missing_api_key", "OpenAI API key is missing.")
    return AsyncOpenAI(
        api_key=key,
        base_url="https://api.openai.com/v1",
        timeout=settings.provider_timeout_seconds,
        max_retries=0,
    )


_SPEECH_SECRETS = (
    re.compile(r"(?i)\b(?:https?://|www\.)\S+"),
    re.compile(r"\b(?:sk|rk)-[\w-]{12,}\b"),
    re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"),
    re.compile(
        r"(?i)(\b(?:password|passcode|PIN|OTP|verification code|security code|"
        r"one[- ]time (?:passcode|code|password))\s*(?::|=|\bis\b)\s*)"
        r"(?!redacted(?=$|[\s.,!?;:)'…]))\S+"
    ),
    re.compile(r"(?i)(\b(?:code|passcode|PIN|OTP)\s+)(?:\d[ -]?){3,7}\d\b"),
    re.compile(r"(?i)(\b(?:account|card) (?:number|no\.?)\s*[:#]?\s*)(?:\d[ -]?){4,}\d\b"),
)


def redact_sensitive_text(text: str) -> str:
    """Redact common secrets without changing whitespace or Unicode characters."""
    for pattern in _SPEECH_SECRETS:
        replacement = r"\1redacted" if pattern.groups else "redacted"
        text = pattern.sub(replacement, text)
    return text


def clean_spoken_text(text: str) -> str:
    """Remove secrets and expand emoji before text reaches a speech engine."""
    text = redact_sensitive_text(text)
    # Match complete emoji sequences (including skin tones, flags, and ZWJ families).
    # Leave ordinary letters and user-written shortcode text untouched.
    text = emoji.replace_emoji(
        text, replace=lambda _glyph, data: " " + data["en"].strip(":").replace("_", " ") + " "
    )
    return " ".join(text.split())
