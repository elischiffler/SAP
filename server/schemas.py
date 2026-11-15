from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, StringConstraints

from contracts.models import Contract

DeviceId = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Priority = Annotated[int, Field(strict=True, ge=3, le=5)]
Outcome = Literal["played", "retry"]


class PiAckRequest(Contract):
    ids: Annotated[list[UUID], Field(min_length=1, max_length=1)]


class PiDownloadRequest(Contract):
    id: UUID
    transfer_id: UUID
    size: Annotated[int, Field(strict=True, gt=0, le=5 * 1024 * 1024)]
    sha256: Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]


class DeviceRequest(Contract):
    device_id: DeviceId


class AckRequest(DeviceRequest):
    outcome: Outcome


class HealthResponse(Contract):
    status: Literal["ok"]


class EnqueueResponse(Contract):
    event_id: UUID
    status: Literal["pending", "ready", "leased", "failed", "played", "discarded"]


class IngressLogEntry(Contract):
    sequence: int | None = None
    priority: Annotated[int, Field(ge=1, le=5)] | None = None
    id: UUID
    received_at: AwareDatetime
    method: Literal["POST"]
    path: Literal["/api/notifications", "/api/esp/notifications"]
    status_code: Annotated[int, Field(ge=100, le=599)]
    duration_ms: Annotated[float, Field(ge=0)]
    event_id: UUID | None = None
    app: Annotated[str, Field(max_length=100)] | None = None
    app_label: Annotated[str, Field(max_length=100)] | None = None
    sender: Annotated[str, Field(max_length=120)] | None = None
    preview: Annotated[str, Field(max_length=160)] | None = None
    # Only accepted, size-limited request bodies are captured; no server defaults are added.
    payload: dict[str, JsonValue] | str | None = None
    payload_redacted: bool = False
    payload_expired: bool = False
    queue_status: (
        Literal["pending", "ready", "leased", "failed", "played", "discarded", "unavailable"] | None
    ) = None


class IngressLogResponse(Contract):
    entries: list[IngressLogEntry]
    total: int
    next_cursor: int | None = None


class RetryResponse(Contract):
    status: Literal["pending", "ready"]


class AckResponse(Contract):
    status: Literal["played", "ready", "failed"]


class DeliveryLease(Contract):
    lease_id: UUID
    message_id: UUID
    device_id: DeviceId
    priority: Priority
    app: str
    sender: str | None
    conversation_name: str | None = None
    notification_count: Annotated[int, Field(ge=1, le=50)] = 1
    spoken_text: str
    audio_url: str
    expires_at: AwareDatetime
    received_at: AwareDatetime
    attempt: Annotated[int, Field(ge=1)]


class ClaimResponse(Contract):
    delivery: DeliveryLease | None


class HeartbeatResponse(Contract):
    delivery: DeliveryLease


class QueueItem(Contract):
    id: UUID
    app: str
    sender: str | None
    conversation_name: str | None = None
    notification_count: Annotated[int, Field(ge=1, le=50)] = 1
    priority: Priority | None
    status: Literal["pending", "ready", "leased", "failed"]
    spoken_text: str | None
    error: str | None
    created_at: AwareDatetime
    received_at: AwareDatetime


class QueueCounts(Contract):
    pending: int
    ready: int
    leased: int
    played: int
    discarded: int
    failed: int


class QueueAlert(Contract):
    id: UUID
    priority: Literal[5]
    created_at: AwareDatetime


class ProviderNames(Contract):
    classifier: Literal["openai", "demo"]
    tts: Literal["openai", "macos"]


class ProviderLimits(Contract):
    provider_calls: int
    max_provider_calls: int


class StateResponse(Contract):
    providers: ProviderNames
    counts: QueueCounts
    items: list[QueueItem]
    alerts: list[QueueAlert]
    limits: ProviderLimits
    active_delivery: None
