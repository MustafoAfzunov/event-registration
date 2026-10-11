"""ORM models. Must stay in sync with the Alembic migrations; this is enforced by
tests/test_schema.py::test_models_match_migrations. Constraint names are explicit because
tests and error mapping refer to them (docs/ARCHITECTURE.md section 5)."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData()


class EventStatus(enum.StrEnum):
    scheduled = "scheduled"
    cancelled = "cancelled"


class RegistrationStatus(enum.StrEnum):
    confirmed = "confirmed"
    waitlisted = "waitlisted"
    cancelled = "cancelled"
    checked_in = "checked_in"


class EmailKind(enum.StrEnum):
    ticket = "ticket"
    waitlisted = "waitlisted"
    promoted = "promoted"
    reminder = "reminder"
    rescheduled = "rescheduled"
    event_cancelled = "event_cancelled"
    cancelled = "cancelled"


class OutboxStatus(enum.StrEnum):
    pending = "pending"
    sending = "sending"
    sent = "sent"
    failed = "failed"
    skipped = "skipped"


def _pg_enum(py_enum: type[enum.Enum], name: str) -> Enum:
    # Types are created by the migration, not by metadata.create_all.
    return Enum(
        py_enum,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        create_type=False,
    )


# Waitlist FIFO order (DECISIONS D-006); values assigned while holding the event lock.
registration_queue_seq = Sequence("registration_queue_seq", metadata=Base.metadata)

TS = DateTime(timezone=True)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("char_length(title) BETWEEN 1 AND 200", name="ck_events_title_length"),
        CheckConstraint("char_length(description) <= 5000", name="ck_events_description_length"),
        CheckConstraint("capacity BETWEEN 1 AND 100000", name="ck_events_capacity_range"),
        # DB-level overbooking guard (DECISIONS D-004).
        CheckConstraint(
            "seats_taken >= 0 AND seats_taken <= capacity", name="ck_events_seats_taken_range"
        ),
        CheckConstraint("schedule_version >= 1", name="ck_events_schedule_version_positive"),
        Index(
            "ix_events_starts_at_scheduled",
            "starts_at",
            postgresql_where=text("status = 'scheduled'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    starts_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    seats_taken: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[EventStatus] = mapped_column(
        _pg_enum(EventStatus, "event_status"), nullable=False, server_default="scheduled"
    )
    schedule_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())


class Registration(Base):
    __tablename__ = "registrations"
    __table_args__ = (
        UniqueConstraint("ticket_code", name="uq_registrations_ticket_code"),
        UniqueConstraint("manage_token", name="uq_registrations_manage_token"),
        UniqueConstraint("queue_seq", name="uq_registrations_queue_seq"),
        CheckConstraint(
            "email_normalized = lower(email_normalized)",
            name="ck_registrations_email_normalized_lower",
        ),
        CheckConstraint(
            "char_length(email_normalized) BETWEEN 3 AND 320",
            name="ck_registrations_email_length",
        ),
        CheckConstraint(
            "ticket_code ~ '^[0-9A-HJKMNP-TV-Z]{8}$'", name="ck_registrations_ticket_code_format"
        ),
        CheckConstraint(
            "char_length(manage_token) >= 32", name="ck_registrations_manage_token_length"
        ),
        CheckConstraint(
            "(status = 'checked_in') = (checked_in_at IS NOT NULL)",
            name="ck_registrations_checked_in_has_time",
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name="ck_registrations_cancelled_has_time",
        ),
        CheckConstraint(
            "status <> 'waitlisted' OR queue_seq IS NOT NULL",
            name="ck_registrations_waitlisted_has_seq",
        ),
        # One active (non-cancelled) registration per email per event (DECISIONS D-005).
        Index(
            "uq_registrations_active_email",
            "event_id",
            "email_normalized",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
        ),
        Index("ix_registrations_event_status", "event_id", "status"),
        Index(
            "ix_registrations_waitlist",
            "event_id",
            "queue_seq",
            postgresql_where=text("status = 'waitlisted'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="RESTRICT", name="fk_registrations_event_id"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    email_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RegistrationStatus] = mapped_column(
        _pg_enum(RegistrationStatus, "registration_status"), nullable=False
    )
    ticket_code: Mapped[str] = mapped_column(String(8), nullable=False)
    manage_token: Mapped[str] = mapped_column(Text, nullable=False)
    queue_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_email_outbox_dedupe_key"),
        CheckConstraint("attempts >= 0", name="ck_email_outbox_attempts_nonnegative"),
        CheckConstraint(
            "(status = 'sent') = (sent_at IS NOT NULL)", name="ck_email_outbox_sent_has_time"
        ),
        Index(
            "ix_email_outbox_due",
            "next_attempt_at",
            postgresql_where=text("status IN ('pending', 'sending')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    kind: Mapped[EmailKind] = mapped_column(_pg_enum(EmailKind, "email_kind"), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="RESTRICT", name="fk_email_outbox_event_id"),
        nullable=False,
    )
    registration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("registrations.id", ondelete="RESTRICT", name="fk_email_outbox_registration_id"),
        nullable=True,
    )
    schedule_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_email: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        _pg_enum(OutboxStatus, "outbox_status"), nullable=False, server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())
    locked_until: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, server_default=func.now())
