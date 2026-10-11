"""Invariants that must hold for every event after any sequence of operations
(ARCHITECTURE 4.1-4.4). Checked after every concurrency test."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def assert_invariants(engine: AsyncEngine, event_id: str) -> None:
    e = {"e": uuid.UUID(event_id)}
    async with engine.connect() as conn:
        capacity, seats_taken = (
            await conn.execute(text("SELECT capacity, seats_taken FROM events WHERE id = :e"), e)
        ).one()
        holders = await conn.scalar(
            text(
                "SELECT count(*) FROM registrations WHERE event_id = :e "
                "AND status IN ('confirmed', 'checked_in')"
            ),
            e,
        )
        waitlisted = await conn.scalar(
            text(
                "SELECT count(*) FROM registrations WHERE event_id = :e AND status = 'waitlisted'"
            ),
            e,
        )
        dup_active = await conn.scalar(
            text(
                "SELECT count(*) FROM (SELECT email_normalized FROM registrations "
                "WHERE event_id = :e AND status <> 'cancelled' "
                "GROUP BY email_normalized HAVING count(*) > 1) d"
            ),
            e,
        )
        holders_without_ticket_email = await conn.scalar(
            text(
                "SELECT count(*) FROM registrations r WHERE r.event_id = :e "
                "AND r.status IN ('confirmed', 'checked_in') AND NOT EXISTS ("
                " SELECT 1 FROM email_outbox o WHERE o.registration_id = r.id "
                " AND o.kind IN ('ticket', 'promoted'))"
            ),
            e,
        )
    assert seats_taken == holders, f"counter {seats_taken} != seat holders {holders}"
    assert holders <= capacity, f"overbooked: {holders} > {capacity}"
    assert not (holders < capacity and waitlisted), (
        f"idle seat while people wait: {holders}/{capacity} taken, {waitlisted} waitlisted"
    )
    assert dup_active == 0, "same email has more than one active registration"
    assert holders_without_ticket_email == 0, "a seat holder has no ticket/promotion email"
