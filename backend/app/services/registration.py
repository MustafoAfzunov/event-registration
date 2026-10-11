"""Register and cancel (ARCHITECTURE 4.2-4.4, state machine 4.10)."""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.emails import templates
from app.emails.outbox import dedupe_key, enqueue
from app.errors import DomainError, constraint_name, not_found
from app.models import (
    EmailKind,
    Event,
    EventStatus,
    Registration,
    RegistrationStatus,
    registration_queue_seq,
)
from app.services import codes
from app.services.normalize import normalize_email
from app.services.seats import add_seats_taken, lock_event, promote_waitlisted, waitlist_position

logger = logging.getLogger(__name__)

ACTIVE_EMAIL_INDEX = "uq_registrations_active_email"
_CODE_CONSTRAINTS = {"uq_registrations_ticket_code", "uq_registrations_manage_token"}
_CODE_ATTEMPTS = 5


@dataclass(frozen=True)
class RegisterResult:
    registration: Registration
    created: bool
    waitlist_position: int | None


def _ensure_open(event: Event, now: datetime) -> None:
    if event.status == EventStatus.cancelled:
        raise DomainError("event_cancelled", "This event has been cancelled.")
    if event.starts_at <= now:
        raise DomainError("registration_closed", "Registration closed: the event has started.")


async def _active_registration(
    session: AsyncSession, event_id: uuid.UUID, email_normalized: str
) -> Registration | None:
    return await session.scalar(
        select(Registration).where(
            Registration.event_id == event_id,
            Registration.email_normalized == email_normalized,
            Registration.status != RegistrationStatus.cancelled,
        )
    )


async def _insert_with_unique_codes(
    session: AsyncSession, values: dict[str, object]
) -> Registration:
    """Insert, regenerating ticket code / token on the (astronomically rare) collision.
    Each attempt runs in a SAVEPOINT so a collision does not abort the outer transaction
    or release the event lock."""
    for _ in range(_CODE_ATTEMPTS):
        registration = Registration(
            id=uuid.uuid4(),
            ticket_code=codes.new_ticket_code(),
            manage_token=codes.new_manage_token(),
            **values,
        )
        try:
            async with session.begin_nested():
                session.add(registration)
                await session.flush()
        except IntegrityError as exc:
            if constraint_name(exc) not in _CODE_CONSTRAINTS:
                raise
            logger.warning("ticket code/token collision, retrying")
            continue
        return registration
    raise RuntimeError(f"no unique ticket code after {_CODE_ATTEMPTS} attempts")


async def _register_once(
    session: AsyncSession,
    event_id: uuid.UUID,
    email: str,
    email_normalized: str,
    now: datetime,
    settings: Settings,
) -> RegisterResult:
    event = await lock_event(session, event_id)  # serializes all seat changes for this event
    _ensure_open(event, now)

    existing = await _active_registration(session, event_id, email_normalized)
    if existing is not None:
        # Idempotent repeat: same row, no new seat, no new email (ARCHITECTURE E1).
        return RegisterResult(existing, False, await waitlist_position(session, existing))

    base: dict[str, object] = {
        "event_id": event_id,
        "email": email,
        "email_normalized": email_normalized,
        "created_at": now,
        "updated_at": now,
    }
    if event.seats_taken < event.capacity:
        registration = await _insert_with_unique_codes(
            session, {**base, "status": RegistrationStatus.confirmed, "confirmed_at": now}
        )
        await add_seats_taken(session, event, 1, now)
        kind = EmailKind.ticket
        rendered = templates.ticket(
            event.title,
            event.starts_at,
            registration.ticket_code,
            settings.public_base_url,
            registration.manage_token,
        )
        position = None
    else:
        # Sequence value taken while holding the event lock => FIFO = arrival order (D-006).
        queue_seq = await session.scalar(select(registration_queue_seq.next_value()))
        registration = await _insert_with_unique_codes(
            session, {**base, "status": RegistrationStatus.waitlisted, "queue_seq": queue_seq}
        )
        position = await waitlist_position(session, registration)
        assert position is not None
        kind = EmailKind.waitlisted
        rendered = templates.waitlisted(
            event.title,
            event.starts_at,
            position,
            settings.public_base_url,
            registration.manage_token,
        )

    await enqueue(
        session,
        kind=kind,
        key=dedupe_key(kind, registration.id),
        event_id=event_id,
        registration_id=registration.id,
        to_email=email,
        email=rendered,
        now=now,
    )
    return RegisterResult(registration, True, position)


async def register(
    sessionmaker: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    raw_email: str,
    now: datetime,
    settings: Settings,
) -> RegisterResult:
    email, email_normalized = normalize_email(raw_email)
    try:
        async with sessionmaker() as session, session.begin():
            return await _register_once(session, event_id, email, email_normalized, now, settings)
    except IntegrityError as exc:
        # Backstop: the event lock makes this unreachable in practice, but if the DB-level
        # unique index ever fires, answer like a normal duplicate instead of a 500.
        if constraint_name(exc) != ACTIVE_EMAIL_INDEX:
            raise
        logger.error("active-email unique index fired despite event lock; returning existing")
    async with sessionmaker() as session, session.begin():
        existing = await _active_registration(session, event_id, email_normalized)
        if existing is None:  # the conflicting row was cancelled in between: try once more
            return await _register_once(session, event_id, email, email_normalized, now, settings)
        return RegisterResult(existing, False, await waitlist_position(session, existing))


async def get_by_token(
    session: AsyncSession, manage_token: str, *, for_update: bool = False
) -> Registration:
    stmt = select(Registration).where(Registration.manage_token == manage_token)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    registration = await session.scalar(stmt)
    if registration is None:
        raise not_found("registration_not_found", "Registration not found.")
    return registration


async def cancel(
    sessionmaker: async_sessionmaker[AsyncSession],
    manage_token: str,
    now: datetime,
    settings: Settings,
) -> Registration:
    async with sessionmaker() as session, session.begin():
        # 1) Unlocked read only to learn which event to lock (lock order: event first).
        event_id = (await get_by_token(session, manage_token)).event_id
        event = await lock_event(session, event_id)
        # 2) Re-read under lock: the row may have changed (promoted, checked in, cancelled).
        registration = await get_by_token(session, manage_token, for_update=True)

        if registration.status == RegistrationStatus.cancelled:
            return registration  # idempotent (ARCHITECTURE E9)
        if registration.status == RegistrationStatus.checked_in:
            raise DomainError("already_checked_in", "This ticket was already checked in.")
        if event.status == EventStatus.cancelled:
            raise DomainError("event_cancelled", "This event has been cancelled.")
        if event.starts_at <= now:
            raise DomainError("event_started", "The event has already started.")

        held_seat = registration.status == RegistrationStatus.confirmed
        registration.status = RegistrationStatus.cancelled
        registration.cancelled_at = now
        registration.updated_at = now
        await session.flush()
        await enqueue(
            session,
            kind=EmailKind.cancelled,
            key=dedupe_key(EmailKind.cancelled, registration.id),
            event_id=event.id,
            registration_id=registration.id,
            to_email=registration.email,
            email=templates.cancelled(event.title, event.starts_at),
            now=now,
        )
        if held_seat:
            await add_seats_taken(session, event, -1, now)
            # Same transaction: the freed seat can never be grabbed by a newcomer first.
            await promote_waitlisted(session, event, now, settings)
        return registration
