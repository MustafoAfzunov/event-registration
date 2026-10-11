"""Seat bookkeeping shared by every seat-changing operation (ARCHITECTURE 4.1-4.4).

THE RULE: an operation that can change who holds a seat (register, cancel, capacity change,
later reschedule / cancel event) runs in ONE transaction whose first statement is
`lock_event` (SELECT ... FOR UPDATE on the event row). Lock order is always event row first,
then registration rows, so these operations cannot deadlock each other. `events.seats_taken`
is only changed while that lock is held, and a CHECK constraint (seats_taken <= capacity)
backs it up at the DB level."""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.emails import templates
from app.emails.outbox import dedupe_key, enqueue
from app.errors import not_found
from app.models import EmailKind, Event, Registration, RegistrationStatus


async def lock_event(session: AsyncSession, event_id: uuid.UUID) -> Event:
    event = await session.scalar(
        select(Event)
        .where(Event.id == event_id)
        .with_for_update()
        # Re-read the row after acquiring the lock even if this session cached it before.
        .execution_options(populate_existing=True)
    )
    if event is None:
        raise not_found("event_not_found", "Event not found.")
    return event


async def add_seats_taken(session: AsyncSession, event: Event, delta: int, now: datetime) -> None:
    """Atomic in-SQL increment (the CHECK constraint sees the real new value)."""
    await session.execute(
        update(Event)
        .where(Event.id == event.id)
        .values(seats_taken=Event.seats_taken + delta, updated_at=now)
        .execution_options(synchronize_session="fetch")
    )


async def waitlist_position(session: AsyncSession, registration: Registration) -> int | None:
    """1-based position among this event's waitlisted registrations, by queue_seq."""
    if registration.status != RegistrationStatus.waitlisted or registration.queue_seq is None:
        return None
    ahead = await session.scalar(
        select(func.count())
        .select_from(Registration)
        .where(
            Registration.event_id == registration.event_id,
            Registration.status == RegistrationStatus.waitlisted,
            Registration.queue_seq < registration.queue_seq,
        )
    )
    return int(ahead or 0) + 1


async def promote_waitlisted(
    session: AsyncSession, event: Event, now: datetime, settings: Settings
) -> list[Registration]:
    """Fill every free seat from the head of the waitlist (FIFO by queue_seq).
    Caller MUST hold the event lock (lock_event) in this same transaction."""
    await session.refresh(event, ["capacity", "seats_taken"])
    free = event.capacity - event.seats_taken
    if free <= 0:
        return []
    promoted = list(
        (
            await session.scalars(
                select(Registration)
                .where(
                    Registration.event_id == event.id,
                    Registration.status == RegistrationStatus.waitlisted,
                )
                .order_by(Registration.queue_seq)
                .limit(free)
                .with_for_update()
            )
        ).all()
    )
    for registration in promoted:
        registration.status = RegistrationStatus.confirmed
        registration.confirmed_at = now
        registration.updated_at = now
        await enqueue(
            session,
            kind=EmailKind.promoted,
            key=dedupe_key(EmailKind.promoted, registration.id),
            event_id=event.id,
            registration_id=registration.id,
            to_email=registration.email,
            email=templates.promoted(
                event.title,
                event.starts_at,
                registration.ticket_code,
                settings.public_base_url,
                registration.manage_token,
            ),
            now=now,
        )
    if promoted:
        await session.flush()
        await add_seats_taken(session, event, len(promoted), now)
    return promoted
