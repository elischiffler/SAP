from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotificationInput(Contract):
    event_id: UUID = Field(default_factory=uuid4)
    app: Annotated[str, Field(strict=True, min_length=1, max_length=100)]
    sender: Annotated[str, Field(strict=True, max_length=120)] | None = None
    title: Annotated[str, Field(strict=True, max_length=256)] = ""
    subtitle: Annotated[str, Field(strict=True, max_length=256)] = ""
    body: Annotated[str, Field(strict=True, max_length=4096)] = ""
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_hidden: bool = Field(default=False, strict=True)
    sender_id: Annotated[str, Field(strict=True, min_length=1, max_length=120)] | None = None
    conversation_id: Annotated[str, Field(strict=True, min_length=1, max_length=120)] | None = None
    conversation_name: Annotated[str, Field(strict=True, min_length=1, max_length=120)] | None = (
        None
    )

    @field_validator("sender_id", "conversation_id", "conversation_name")
    @classmethod
    def nonblank_identity(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("conversation and sender identifiers must not be blank")
        return value.strip() if value is not None else None

    @field_validator("app")
    @classmethod
    def nonblank_app(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("app must not be blank")
        return value.strip()

    @field_validator("received_at", mode="before")
    @classmethod
    def timestamp_type(cls, value: object) -> object:
        if not isinstance(value, (str, datetime)):
            raise ValueError("received_at must be an ISO timestamp")
        return value

    @field_validator("received_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("received_at requires a timezone")
        return value.astimezone(timezone.utc)


class ClassificationResult(Contract):
    priority: Annotated[StrictInt, Field(ge=1, le=5)]
    reason: Annotated[str, Field(strict=True, min_length=1, max_length=240)]
    spoken_text: Annotated[str, Field(strict=True, min_length=1, max_length=350)] | None
    evidence: Literal["sufficient", "insufficient"]
    deadline_at: str | None

    @model_validator(mode="after")
    def coherent_result(self) -> "ClassificationResult":
        if self.priority <= 2 and self.spoken_text is not None:
            raise ValueError("discarded notifications must not contain spoken_text")
        if self.priority >= 3 and not (self.spoken_text or "").strip():
            raise ValueError("playable notifications require spoken_text")
        if self.deadline_at is not None:
            parsed = datetime.fromisoformat(self.deadline_at.replace("Z", "+00:00"))
            if parsed.utcoffset() is None:
                raise ValueError("deadline_at requires a timezone")
        return self


class GroupMember(Contract):
    event_id: UUID
    sender: Annotated[str, Field(strict=True, max_length=120)] | None
    priority: Annotated[StrictInt, Field(ge=3, le=5)]
    spoken_text: Annotated[str, Field(strict=True, min_length=1, max_length=350)]
    received_at: AwareDatetime


class NotificationGroup(Contract):
    app: Annotated[str, Field(strict=True, min_length=1, max_length=100)]
    sender: Annotated[str, Field(strict=True, max_length=120)] | None
    conversation_name: Annotated[str, Field(strict=True, max_length=120)] | None = None
    members: Annotated[list[GroupMember], Field(min_length=2, max_length=50)]
