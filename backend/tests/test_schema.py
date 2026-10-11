"""Schema-level guarantees from docs/ARCHITECTURE.md section 5. These prove the DB itself
rejects invalid states, independent of application code."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from alembic import command
from app.models import Base
from tests.conftest import alembic_config

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
APP_TABLES = {"events", "registrations", "email_outbox"}
APP_ENUMS = {"event_status", "registration_status", "email_kind", "outbox_status"}


def _code() -> str:
    return "".join(secrets.choice(CROCKFORD) for _ in range(8))


async def _event(conn: AsyncConnection, capacity: int = 10) -> uuid.UUID:
    event_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO events (id, title, starts_at, capacity) "
            "VALUES (:id, 'Test event', :starts_at, :capacity)"
        ),
        {"id": event_id, "starts_at": datetime.now(UTC) + timedelta(days=7), "capacity": capacity},
    )
    return event_id


async def _registration(conn: AsyncConnection, event_id: uuid.UUID, **overrides: Any) -> None:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "event_id": event_id,
        "email": "alice@example.com",
        "email_normalized": "alice@example.com",
        "status": "confirmed",
        "ticket_code": _code(),
        "manage_token": secrets.token_urlsafe(32),
        "queue_seq": None,
        "cancelled_at": None,
        "checked_in_at": None,
    }
    values.update(overrides)
    await conn.execute(
        text(
            "INSERT INTO registrations (id, event_id, email, email_normalized, status, "
            "ticket_code, manage_token, queue_seq, cancelled_at, checked_in_at) VALUES "
            "(:id, :event_id, :email, :email_normalized, :status, :ticket_code, "
            ":manage_token, :queue_seq, :cancelled_at, :checked_in_at)"
        ),
        values,
    )


def _violated_constraint(exc: pytest.ExceptionInfo[IntegrityError]) -> str | None:
    return exc.value.orig.diag.constraint_name  # type: ignore[union-attr]


def test_migrations_upgrade_downgrade_upgrade(test_db_url: str) -> None:
    cfg = alembic_config(test_db_url)
    sync_engine = create_engine(test_db_url)
    try:
        command.downgrade(cfg, "base")
        with sync_engine.connect() as conn:
            assert APP_TABLES.isdisjoint(inspect(conn).get_table_names())
            enums = conn.execute(text("SELECT typname FROM pg_type WHERE typtype = 'e'"))
            assert APP_ENUMS.isdisjoint({row[0] for row in enums})

        command.upgrade(cfg, "head")
        with sync_engine.connect() as conn:
            assert set(inspect(conn).get_table_names()) >= APP_TABLES
            current = MigrationContext.configure(conn).get_current_revision()
        assert current == ScriptDirectory.from_config(cfg).get_current_head()
    finally:
        sync_engine.dispose()


def test_models_match_migrations(test_db_url: str) -> None:
    """ORM models and migrations must describe the same schema (no autogenerate drift)."""
    sync_engine = create_engine(test_db_url)
    try:
        with sync_engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        sync_engine.dispose()
    assert diff == []


async def test_active_email_unique_index_rejects_second_active_row(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        event_id = await _event(conn)
        await _registration(conn, event_id, status="confirmed")

    with pytest.raises(IntegrityError) as exc:
        async with engine.begin() as conn:
            await _registration(conn, event_id, status="waitlisted", queue_seq=1)
    assert _violated_constraint(exc) == "uq_registrations_active_email"


async def test_active_email_unique_index_allows_cancelled_duplicates(engine: AsyncEngine) -> None:
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        event_id = await _event(conn)
        await _registration(conn, event_id, status="cancelled", cancelled_at=now)
        await _registration(conn, event_id, status="cancelled", cancelled_at=now)
        await _registration(conn, event_id, status="confirmed")
        count = await conn.scalar(
            text("SELECT count(*) FROM registrations WHERE event_id = :e"), {"e": event_id}
        )
    assert count == 3


async def test_seats_taken_check_rejects_overbooking(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        event_id = await _event(conn, capacity=2)
        await conn.execute(text("UPDATE events SET seats_taken = 2 WHERE id = :e"), {"e": event_id})

    with pytest.raises(IntegrityError) as exc:
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE events SET seats_taken = seats_taken + 1 WHERE id = :e"),
                {"e": event_id},
            )
    assert _violated_constraint(exc) == "ck_events_seats_taken_range"

    # Lowering capacity below seats_taken is rejected by the same constraint.
    with pytest.raises(IntegrityError) as exc:
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE events SET capacity = 1 WHERE id = :e"), {"e": event_id}
            )
    assert _violated_constraint(exc) == "ck_events_seats_taken_range"


async def test_checked_in_requires_timestamp(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        event_id = await _event(conn)

    with pytest.raises(IntegrityError) as exc:
        async with engine.begin() as conn:
            await _registration(conn, event_id, status="checked_in", checked_in_at=None)
    assert _violated_constraint(exc) == "ck_registrations_checked_in_has_time"

    with pytest.raises(IntegrityError) as exc:
        async with engine.begin() as conn:
            await _registration(conn, event_id, status="confirmed", checked_in_at=datetime.now(UTC))
    assert _violated_constraint(exc) == "ck_registrations_checked_in_has_time"


async def test_waitlisted_requires_queue_seq(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        event_id = await _event(conn)

    with pytest.raises(IntegrityError) as exc:
        async with engine.begin() as conn:
            await _registration(conn, event_id, status="waitlisted", queue_seq=None)
    assert _violated_constraint(exc) == "ck_registrations_waitlisted_has_seq"


async def test_email_normalized_must_be_lowercase(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        event_id = await _event(conn)

    with pytest.raises(IntegrityError) as exc:
        async with engine.begin() as conn:
            await _registration(conn, event_id, email_normalized="Alice@example.com")
    assert _violated_constraint(exc) == "ck_registrations_email_normalized_lower"


# Excluded letters (I, L, O, U), lowercase, and wrong length must all be rejected.
@pytest.mark.parametrize(
    "bad_code", ["ABCDEFGI", "ABCDEFGL", "ABCDEFGO", "ABCDEFGU", "abcdefgh", "ABC"]
)
async def test_ticket_code_format_enforced(engine: AsyncEngine, bad_code: str) -> None:
    async with engine.begin() as conn:
        event_id = await _event(conn)

    with pytest.raises(IntegrityError) as exc:
        async with engine.begin() as conn:
            await _registration(conn, event_id, ticket_code=bad_code)
    assert _violated_constraint(exc) == "ck_registrations_ticket_code_format"


async def test_outbox_dedupe_key_unique(engine: AsyncEngine) -> None:
    insert = text(
        "INSERT INTO email_outbox (kind, dedupe_key, event_id, to_email, subject, body_text) "
        "VALUES ('ticket', :key, :e, 'a@example.com', 's', 'b')"
    )
    async with engine.begin() as conn:
        event_id = await _event(conn)
        await conn.execute(insert, {"key": "ticket:1", "e": event_id})

    with pytest.raises(IntegrityError) as exc:
        async with engine.begin() as conn:
            await conn.execute(insert, {"key": "ticket:1", "e": event_id})
    assert _violated_constraint(exc) == "uq_email_outbox_dedupe_key"

    # ON CONFLICT DO NOTHING is how enqueue stays idempotent (ARCHITECTURE 4.5).
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "INSERT INTO email_outbox (kind, dedupe_key, event_id, to_email, subject, "
                "body_text) VALUES ('ticket', 'ticket:1', :e, 'a@example.com', 's', 'b') "
                "ON CONFLICT (dedupe_key) DO NOTHING"
            ),
            {"e": event_id},
        )
        assert result.rowcount == 0
        total = await conn.scalar(text("SELECT count(*) FROM email_outbox"))
    assert total == 1
