"""Normalize text and JSON ESP packets into the pager contract."""

import json
from datetime import datetime, timezone
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field

from .models import Contract, NotificationInput

_BUNDLE_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
_BUNDLE_IDENTIFIER = rf"^{_BUNDLE_LABEL}(?:\.{_BUNDLE_LABEL})+$"
_TIMESTAMP = r"^[0-9]{8}T[0-9]{6}$"
_MESSAGES_APP = "com.apple.mobilesms"


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
    return NotificationInput(
        event_id=event_id,
        app=fields.app,
        sender=(fields.title.strip() or None) if is_messages else None,
        title=fields.title,
        subtitle=fields.subtitle,
        body=fields.message,
        received_at=received_at,
        content_hidden=is_messages and not fields.message.strip(),
    )
