"""Event create / read / update (organizer) and public views. There is no delete: an event
is cancelled instead (phase 6), which keeps history and notifies people (ARCHITECTURE E27)."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.errors import DomainError, not_found
from app.models import Event, EventStatus, Registration, RegistrationStatus
from app.schemas import EventCreate, EventOut, EventUpdate
from app.services.seats import lock_event, promote_waitlisted


def _waitlist_counts() -> Select[uuid.UUID, int]:
    return (
        select(Registration.event_id, func.count().label("n"))
        .where(Registration.status == RegistrationStatus.waitlisted)
        .group_by(Registration.event_id)
    )


def to_out(event: Event, waitlist_count: int) -> EventOut:
    return EventOut(
        id=event.id,
        title=event.title,
        description=event.description,
        starts_at=event.starts_at,
        capacity=event.capacity,
        seats_left=event.capacity - event.seats_taken,
        waitlist_count=waitlist_count,
        status=event.status,
    )


async def _with_counts(session: AsyncSession, stmt: Select[Event]) -> list[EventOut]:
    counts = _waitlist_counts().subquery()
    rows = await session.execute(
        stmt.add_columns(func.coalesce(counts.c.n, 0)).outerjoin(
            counts, counts.c.event_id == Event.id
        )
    )
    return [to_out(event, int(n)) for event, n in rows.all()]


async def event_out(session: AsyncSession, event_id: uuid.UUID) -> EventOut:
    found = await _with_counts(session, select(Event).where(Event.id == event_id))
    if not found:
        raise not_found("event_not_found", "Event not found.")
    return found[0]


async def create_event(
    sessionmaker: async_sessionmaker[AsyncSession], data: EventCreate, now: datetime
) -> EventOut:
    if data.starts_at <= now:
        raise DomainError("starts_in_past", "The event must start in the future.", status=422)
    async with sessionmaker() as session, session.begin():
        event = Event(
            id=uuid.uuid4(),
            title=data.title,
            description=data.description,
            starts_at=data.starts_at,
            capacity=data.capacity,
            seats_taken=0,
            status=EventStatus.scheduled,
            schedule_version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(event)
        await session.flush()
        return to_out(event, 0)


async def list_public(
    sessionmaker: async_sessionmaker[AsyncSession], now: datetime
) -> list[EventOut]:
    async with sessionmaker() as session:
        stmt = (
            select(Event)
            .where(Event.status == EventStatus.scheduled, Event.starts_at > now)
            .order_by(Event.starts_at, Event.id)
        )
        return await _with_counts(session, stmt)


async def list_all(sessionmaker: async_sessionmaker[AsyncSession]) -> list[EventOut]:
    async with sessionmaker() as session:
        return await _with_counts(session, select(Event).order_by(Event.starts_at.desc(), Event.id))


async def get_event(
    sessionmaker: async_sessionmaker[AsyncSession], event_id: uuid.UUID
) -> EventOut:
    async with sessionmaker() as session:
        return await event_out(session, event_id)


@dataclass(frozen=True)
class UpdateResult:
    event: EventOut
    promoted_count: int


async def update_event(
    sessionmaker: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    data: EventUpdate,
    now: datetime,
    settings: Settings,
) -> UpdateResult:
    async with sessionmaker() as session, session.begin():
        event = await lock_event(session, event_id)
        if event.status == EventStatus.cancelled:
            raise DomainError("event_cancelled", "This event has been cancelled.")

        promoted_count = 0
        if data.capacity is not None and data.capacity != event.capacity:
            if event.starts_at <= now:
                raise DomainError("event_started", "Capacity cannot change after the start.")
            if data.capacity < event.seats_taken:
                # Never bump confirmed people (ARCHITECTURE E6).
                raise DomainError(
                    "capacity_below_taken",
                    f"{event.seats_taken} seats are already taken; capacity cannot go below that.",
                    details={"seats_taken": event.seats_taken},
                )
            event.capacity = data.capacity
            event.updated_at = now
            await session.flush()
            # More seats: promote FIFO in the same transaction (ARCHITECTURE E7).
            promoted_count = len(await promote_waitlisted(session, event, now, settings))

        if data.title is not None:
            event.title = data.title
        if data.description is not None:
            event.description = data.description
        event.updated_at = now
        await session.flush()
        return UpdateResult(await event_out(session, event_id), promoted_count)
