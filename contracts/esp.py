"""Normalize text and JSON ESP packets into the pager contract."""

import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field

from .app_names import display_app_name
from .models import Contract, NotificationInput

_BUNDLE_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
_BUNDLE_IDENTIFIER = rf"^{_BUNDLE_LABEL}(?:\.{_BUNDLE_LABEL})+$"
_TIMESTAMP = r"^[0-9]{8}T[0-9]{6}$"
_MESSAGES_APP = "com.apple.mobilesms"


# Sender-bearing titles on communication apps. Other apps require an explicit
# "From ..." label; an arbitrary notification headline is not a person's name.
_SENDER_APPS = {
    "messages", "slack", "discord", "snapchat", "whatsapp", "signal", "telegram",
    "messenger", "microsoft teams", "instagram", "mail", "gmail", "outlook",
    "phone", "facetime", "facebook", "linkedin", "x", "threads", "tiktok",
}


def _sender(fields: "_ESPPacket") -> str | None:
    if fields.app.casefold() == _MESSAGES_APP:
        return fields.title.strip() or None
    title = " ".join(fields.title.split())
    app = display_app_name(fields.app).casefold()
    explicit = re.fullmatch(r"From\s+(.+)", title, flags=re.IGNORECASE)
    candidate = explicit[1] if explicit else title if app in _SENDER_APPS else ""
    generic = {app, fields.app.casefold(), "new message", "new notification", "notification",
               "notifications", "message", "messages", "unknown", "unknown sender",
               "incoming call", "missed call"}
    if (not candidate or len(candidate) > 120 or candidate.casefold() in generic
            or candidate.startswith(("#", "@channel", "@everyone"))
            or re.fullmatch(r"\d+ new (?:messages|notifications)", candidate, re.IGNORECASE)):
        return None
    return candidate


def _chat_label(value: str) -> str:
    return unicodedata.normalize("NFC", " ".join(value.split()))


def _messages_chat(fields: "_ESPPacket", event_id: UUID) -> tuple[str | None, str | None]:
    """Interpret the observed Messages labels without guessing opaque ANCS IDs."""
    label = _chat_label(fields.subtitle)
    if fields.app.casefold() != _MESSAGES_APP or not label:
        return None, None
    sender = _chat_label(fields.title)
    identity = None
    display = label
    # Observed unnamed three-person chat: the sender is absent from the subtitle.
    # Treat the remainder as ONE contact; do not split ambiguous contact labels.
    recipient = re.fullmatch(r"To you & (.+)", label, flags=re.IGNORECASE)
    clipped = re.search(r"(?:…|\.{3})$", label) or re.search(r"(?:…|\.{3})$", sender)
    if recipient and sender and not clipped:
        other = recipient[1]
        ambiguous = re.search(
            r",|&|\band\b|\b\d+\s+(?:others?|people|participants)\b", other, re.IGNORECASE
        )
        participants = sorted({sender.casefold(), other.casefold()})
        if not ambiguous and len(participants) == 2:
            identity = ["messages-participants-v1", participants]
            display = "Group with " + ", ".join(sorted((sender, other), key=str.casefold))
    elif not label.casefold().startswith("to ") and not clipped:
        identity = ["messages-chat-name-v1", label.casefold()]
    if identity is None:
        # An incomplete recipient list must not merge unrelated chats or DMs.
        chat_id = f"ancs-unresolved:{event_id}"
    else:
        chat_id = "ancs-chat:" + str(uuid5(NAMESPACE_URL, json.dumps(identity, ensure_ascii=False)))
    display = display if len(display) <= 120 else display[:119].rstrip() + "…"
    return chat_id, display


class _ESPPacket(Contract):
    app: Annotated[
        str, Field(strict=True, min_length=1, max_length=100, pattern=_BUNDLE_IDENTIFIER)
    ]
    title: Annotated[str, Field(strict=True, max_length=256)]
    subtitle: Annotated[str, Field(strict=True, max_length=256)] = ""
    message: Annotated[str, Field(strict=True, max_length=4096)]
    date: Annotated[str, Field(strict=True, min_length=15, max_length=15, pattern=_TIMESTAMP)]


def _utc_timestamp(timestamp: str, timezone_name: str) -> datetime:
    try:
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("The ESP timezone must be a valid IANA timezone.") from None
    try:
        local_time = datetime.strptime(timestamp, "%Y%m%dT%H%M%S")
        candidates = {
            local_time.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc) for fold in (0, 1)
        }
        matching_times = {
            candidate
            for candidate in candidates
            if candidate.astimezone(zone).replace(tzinfo=None) == local_time
        }
    except (OverflowError, ValueError):
        raise ValueError("The ESP timestamp is invalid.") from None
    if not matching_times:
        raise ValueError("The ESP timestamp falls in a skipped local hour.")
    if len(matching_times) != 1:
        raise ValueError("The ESP timestamp is ambiguous in the configured timezone.")
    return matching_times.pop()


def parse_esp_packet(
    packet: str, *, timezone_name: str, event_id: UUID | None = None
) -> NotificationInput:
    """Parse app, label, body, and local timestamp. Only the body may contain pipes.

    Prefer a device-generated event ID. Without one, same-second packets with
    identical normalized fields resolve to the same ID.
    """
    if not isinstance(packet, str):
        raise ValueError("The ESP packet must be text.")
    # Serial line-oriented firmware may preserve its transport line terminator.
    packet = packet.rstrip("\r\n")
    header = packet.split("|", 2)
    if len(header) != 3:
        raise ValueError("The ESP packet must contain four fields.")
    app, title, body_and_time = header
    body, separator, timestamp = body_and_time.rpartition("|")
    if not separator:
        raise ValueError("The ESP packet must contain four fields.")
    fields = _ESPPacket(
        app=app.strip(" "),
        title=title.strip(" "),
        message=body.strip(" "),
        date=timestamp.strip(" "),
    )
    return _to_notification(fields, timezone_name=timezone_name, event_id=event_id)


def parse_esp_json(
    packet: str | bytes | bytearray, *, timezone_name: str, event_id: UUID | None = None
) -> NotificationInput:
    """Parse a UTF-8 JSON object with app, title, message, and ANCS date fields."""
    fields = _ESPPacket.model_validate_json(packet)
    return _to_notification(fields, timezone_name=timezone_name, event_id=event_id)


def _to_notification(
    fields: _ESPPacket, *, timezone_name: str, event_id: UUID | None
) -> NotificationInput:
    received_at = _utc_timestamp(fields.date, timezone_name)
    if event_id is None:
        identity_fields = [fields.app, fields.title, fields.message, received_at.isoformat()]
        # Preserve legacy retry IDs when the new optional field is absent or empty.
        if fields.subtitle:
            identity_fields.append(fields.subtitle)
        identity = json.dumps(
            identity_fields,
            separators=(",", ":"),
        )
        event_id = uuid5(NAMESPACE_URL, f"sap:esp:{identity}")
    is_messages = fields.app.casefold() == _MESSAGES_APP
    conversation_id, conversation_name = _messages_chat(fields, event_id)
    return NotificationInput(
        event_id=event_id,
        app=fields.app,
        sender=_sender(fields),
        title=fields.title,
        subtitle=fields.subtitle,
        body=fields.message,
        received_at=received_at,
        content_hidden=is_messages and not fields.message.strip(),
        # A sender label alone cannot identify a Slack workspace/channel or
        # another platform's conversation. Do not merge distinct threads.
        conversation_id=conversation_id if is_messages else (
            f"ancs-source:{event_id}" if _sender(fields) and fields.app.casefold() != "com.toyopagroup.picaboo" else None
        ),
        conversation_name=conversation_name,
    )
