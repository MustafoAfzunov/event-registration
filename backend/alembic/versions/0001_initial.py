"""initial schema: events, registrations, email_outbox

Hand-written (DECISIONS D-002). See docs/ARCHITECTURE.md section 5 for the meaning of every
constraint. Partial indexes and CHECKs here are the last line of defence for correctness.

Revision ID: 0001
Revises:
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUMS = {
    "event_status": ("scheduled", "cancelled"),
    "registration_status": ("confirmed", "waitlisted", "cancelled", "checked_in"),
    "email_kind": (
        "ticket",
        "waitlisted",
        "promoted",
        "reminder",
        "rescheduled",
        "event_cancelled",
        "cancelled",
    ),
    "outbox_status": ("pending", "sending", "sent", "failed", "skipped"),
}


def _enum(name: str) -> pg.ENUM:
    return pg.ENUM(*ENUMS[name], name=name, create_type=False)


def _ts(name: str, nullable: bool = True, default_now: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if default_now else None,
    )


def upgrade() -> None:
    for name, values in ENUMS.items():
        pg.ENUM(*values, name=name).create(op.get_bind(), checkfirst=False)

    op.execute(sa.schema.CreateSequence(sa.Sequence("registration_queue_seq")))

    op.create_table(
        "events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        _ts("starts_at", nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("seats_taken", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", _enum("event_status"), nullable=False, server_default="scheduled"),
        sa.Column("schedule_version", sa.Integer(), nullable=False, server_default="1"),
        _ts("created_at", nullable=False, default_now=True),
        _ts("updated_at", nullable=False, default_now=True),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 200", name="ck_events_title_length"),
        sa.CheckConstraint("char_length(description) <= 5000", name="ck_events_description_length"),
        sa.CheckConstraint("capacity BETWEEN 1 AND 100000", name="ck_events_capacity_range"),
        sa.CheckConstraint(
            "seats_taken >= 0 AND seats_taken <= capacity", name="ck_events_seats_taken_range"
        ),
        sa.CheckConstraint("schedule_version >= 1", name="ck_events_schedule_version_positive"),
    )
    op.create_index(
        "ix_events_starts_at_scheduled",
        "events",
        ["starts_at"],
        postgresql_where=sa.text("status = 'scheduled'"),
    )

    op.create_table(
        "registrations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="RESTRICT", name="fk_registrations_event_id"),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("email_normalized", sa.Text(), nullable=False),
        sa.Column("status", _enum("registration_status"), nullable=False),
        sa.Column("ticket_code", sa.String(8), nullable=False),
        sa.Column("manage_token", sa.Text(), nullable=False),
        sa.Column("queue_seq", sa.BigInteger(), nullable=True),
        _ts("created_at", nullable=False, default_now=True),
        _ts("updated_at", nullable=False, default_now=True),
        _ts("confirmed_at"),
        _ts("cancelled_at"),
        _ts("checked_in_at"),
        sa.UniqueConstraint("ticket_code", name="uq_registrations_ticket_code"),
        sa.UniqueConstraint("manage_token", name="uq_registrations_manage_token"),
        sa.UniqueConstraint("queue_seq", name="uq_registrations_queue_seq"),
        sa.CheckConstraint(
            "email_normalized = lower(email_normalized)",
            name="ck_registrations_email_normalized_lower",
        ),
        sa.CheckConstraint(
            "char_length(email_normalized) BETWEEN 3 AND 320",
            name="ck_registrations_email_length",
        ),
        sa.CheckConstraint(
            "ticket_code ~ '^[0-9A-HJKMNP-TV-Z]{8}$'", name="ck_registrations_ticket_code_format"
        ),
        sa.CheckConstraint(
            "char_length(manage_token) >= 32", name="ck_registrations_manage_token_length"
        ),
        sa.CheckConstraint(
            "(status = 'checked_in') = (checked_in_at IS NOT NULL)",
            name="ck_registrations_checked_in_has_time",
        ),
        sa.CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name="ck_registrations_cancelled_has_time",
        ),
        sa.CheckConstraint(
            "status <> 'waitlisted' OR queue_seq IS NOT NULL",
            name="ck_registrations_waitlisted_has_seq",
        ),
    )
    # One active (non-cancelled) registration per email per event. DECISIONS D-005.
    op.create_index(
        "uq_registrations_active_email",
        "registrations",
        ["event_id", "email_normalized"],
        unique=True,
        postgresql_where=sa.text("status <> 'cancelled'"),
    )
    op.create_index("ix_registrations_event_status", "registrations", ["event_id", "status"])
    op.create_index(
        "ix_registrations_waitlist",
        "registrations",
        ["event_id", "queue_seq"],
        postgresql_where=sa.text("status = 'waitlisted'"),
    )

    op.create_table(
        "email_outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("kind", _enum("email_kind"), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column(
            "event_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="RESTRICT", name="fk_email_outbox_event_id"),
            nullable=False,
        ),
        sa.Column(
            "registration_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey(
                "registrations.id", ondelete="RESTRICT", name="fk_email_outbox_registration_id"
            ),
            nullable=True,
        ),
        sa.Column("schedule_version", sa.Integer(), nullable=True),
        sa.Column("to_email", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("status", _enum("outbox_status"), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        _ts("next_attempt_at", nullable=False, default_now=True),
        _ts("locked_until"),
        _ts("sent_at"),
        sa.Column("last_error", sa.Text(), nullable=True),
        _ts("created_at", nullable=False, default_now=True),
        sa.UniqueConstraint("dedupe_key", name="uq_email_outbox_dedupe_key"),
        sa.CheckConstraint("attempts >= 0", name="ck_email_outbox_attempts_nonnegative"),
        sa.CheckConstraint(
            "(status = 'sent') = (sent_at IS NOT NULL)", name="ck_email_outbox_sent_has_time"
        ),
    )
    op.create_index(
        "ix_email_outbox_due",
        "email_outbox",
        ["next_attempt_at"],
        postgresql_where=sa.text("status IN ('pending', 'sending')"),
    )


def downgrade() -> None:
    op.drop_table("email_outbox")
    op.drop_table("registrations")
    op.drop_table("events")
    op.execute(sa.schema.DropSequence(sa.Sequence("registration_queue_seq")))
    for name in reversed(list(ENUMS)):
        op.execute(f"DROP TYPE {name}")
