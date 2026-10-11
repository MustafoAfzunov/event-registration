"""Request/response models. Shapes match docs/API.md."""

import uuid
from datetime import datetime
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
from app.timefmt import iso_utc

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(max_length=5000)]
Capacity = Annotated[int, Field(ge=1, le=100_000)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _utc(value: datetime | None) -> str | None:
    return None if value is None else iso_utc(value)


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


class CheckInIn(_Strict):
    code: str = Field(max_length=40)


class CheckInOut(BaseModel):
    result: str = "checked_in"
    email: str
    checked_in_at: datetime

    @field_serializer("checked_in_at")
    def _ser_checked_in_at(self, value: datetime) -> str | None:
        return _utc(value)


class EmailCounts(BaseModel):
    pending: int
    sending: int
    sent: int
    failed: int
    skipped: int


class StatsOut(BaseModel):
    capacity: int
    confirmed: int  # holds a seat, not arrived yet
    checked_in: int  # arrived (still holds the seat)
    registered: int  # confirmed + checked_in
    waitlisted: int
    cancelled: int
    seats_left: int  # capacity - registered
    emails: EmailCounts


class LiveAvailabilityOut(BaseModel):
    """Public live view of an event: no personal data, no attendance numbers."""

    event_id: uuid.UUID
    status: EventStatus
    starts_at: datetime
    capacity: int
    seats_left: int
    waitlist_count: int

    @field_serializer("starts_at")
    def _ser_starts_at(self, value: datetime) -> str | None:
        return _utc(value)


class LiveStatsOut(StatsOut):
    event_id: uuid.UUID


class RegistrationAdminOut(BaseModel):
    id: uuid.UUID
    email: str
    status: RegistrationStatus
    ticket_code: str
    waitlist_position: int | None
    created_at: datetime
    checked_in_at: datetime | None

    @field_serializer("created_at", "checked_in_at")
    def _ser_times(self, value: datetime | None) -> str | None:
        return _utc(value)
