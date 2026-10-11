"""Check-in by ticket code (ARCHITECTURE 4.6).

The whole decision is ONE conditional UPDATE:
    UPDATE registrations SET status='checked_in' ...
     WHERE event_id=:e AND ticket_code=:c AND status='confirmed'
Postgres row locking + re-evaluation of the WHERE clause under READ COMMITTED means that of
any number of concurrent attempts for the same ticket exactly one matches; the others see
status='checked_in' after the winner commits and update nothing. Only when nothing was
updated do we read the row again, purely to choose the right error.

Check-in does not take the event lock: it does not change who holds a seat (a checked-in
registration still holds its seat), so it never touches seats_taken. Lock order is not at
risk: it locks only the one registration row. A racing cancel (event lock, then this row)
and this UPDATE serialize on the row; whichever commits first wins, the other sees the new
status (tested)."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import DomainError, not_found
from app.models import Event, EventStatus, Registration, RegistrationStatus
from app.services.codes import normalize_ticket_input


@dataclass(frozen=True)
class CheckInResult:
    email: str
    checked_in_at: datetime


async def _event_or_404(session: AsyncSession, event_id: uuid.UUID) -> Event:
    event = await session.get(Event, event_id)
    if event is None:
        raise not_found("event_not_found", "Event not found.")
    return event


async def check_in(
    sessionmaker: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    raw_code: str,
    now: datetime,
) -> CheckInResult:
    code = normalize_ticket_input(raw_code)
    if code is None:
        raise DomainError(
            "invalid_code_format", "A ticket code has 8 letters/digits, e.g. ABCD-EFGH.", status=422
        )

    async with sessionmaker() as session, session.begin():
        event = await _event_or_404(session, event_id)
        if event.status == EventStatus.cancelled:
            raise DomainError("event_cancelled", "This event has been cancelled.")

        won = (
            await session.execute(
                update(Registration)
                .where(
                    Registration.event_id == event_id,
                    Registration.ticket_code == code,
                    Registration.status == RegistrationStatus.confirmed,
                )
                .values(status=RegistrationStatus.checked_in, checked_in_at=now, updated_at=now)
                .returning(Registration.email, Registration.checked_in_at)
                .execution_options(synchronize_session=False)
            )
        ).one_or_none()
        if won is not None:
            # pg_notify for live counters is added here in phase 5.
            return CheckInResult(email=won.email, checked_in_at=won.checked_in_at)

        # Nothing updated: find out why (read only, to pick the error).
        row = (
            await session.execute(
                select(Registration.status, Registration.email, Registration.checked_in_at).where(
                    Registration.event_id == event_id, Registration.ticket_code == code
                )
            )
        ).one_or_none()

    if row is None:
        raise not_found("ticket_not_found", "No ticket with this code for this event.")
    if row.status == RegistrationStatus.checked_in:
        raise DomainError(
            "already_checked_in",
            "This ticket was already used.",
            details={"checked_in_at": row.checked_in_at, "email": row.email},
        )
    if row.status == RegistrationStatus.cancelled:
        raise DomainError(
            "ticket_cancelled",
            "This ticket was cancelled and is not valid for entry.",
            details={"status": row.status.value, "email": row.email},
        )
    raise DomainError(
        "ticket_waitlisted",
        "This person is on the waitlist and has no seat.",
        details={"status": row.status.value, "email": row.email},
    )
