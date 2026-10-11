"""Request/response models. Shapes match docs/API.md."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
)

from app.models import EventStatus, RegistrationStatus

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(max_length=5000)]
Capacity = Annotated[int, Field(ge=1, le=100_000)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _utc(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class LoginIn(_Strict):
    password: str = Field(max_length=200)


class EventCreate(_Strict):
    title: Title
    description: Description = ""
    starts_at: AwareDatetime
    capacity: Capacity


class EventUpdate(_Strict):
    """starts_at is intentionally absent: rescheduling has its own endpoint (phase 6)
    so participant notification stays explicit. Sending it yields 422."""

    title: Title | None = None
    description: Description | None = None
    capacity: Capacity | None = None


class EventOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    starts_at: datetime
    capacity: int
    seats_left: int
    waitlist_count: int
    status: EventStatus

    @field_serializer("starts_at")
    def _ser_starts_at(self, value: datetime) -> str | None:
        return _utc(value)


class EventUpdateOut(EventOut):
    promoted_count: int


class RegisterIn(_Strict):
    email: str = Field(max_length=400)


class RegisterOut(BaseModel):
    created: bool
    status: RegistrationStatus
    waitlist_position: int | None
    email: str
    message: str


class RegistrationOut(BaseModel):
    event: EventOut
    email: str
    status: RegistrationStatus
    ticket_code: str | None
    waitlist_position: int | None
    checked_in_at: datetime | None

    @field_serializer("checked_in_at")
    def _ser_checked_in_at(self, value: datetime | None) -> str | None:
        return _utc(value)


class CancelOut(BaseModel):
    status: RegistrationStatus
