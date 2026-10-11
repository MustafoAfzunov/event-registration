"""Organizer stats and registration list.

All counts come from ONE SQL statement, i.e. one snapshot: a reader can never observe a
half-applied transition (e.g. a cancelled seat before its promotion), so the numbers always
satisfy the invariants, even while writes are happening (tested under concurrency)."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import not_found
from app.models import RegistrationStatus

_STATS = text(
    """
    SELECT e.capacity,
           count(r.id) FILTER (WHERE r.status = 'confirmed')  AS confirmed,
           count(r.id) FILTER (WHERE r.status = 'checked_in') AS checked_in,
           count(r.id) FILTER (WHERE r.status = 'waitlisted') AS waitlisted,
           count(r.id) FILTER (WHERE r.status = 'cancelled')  AS cancelled,
           (SELECT count(*) FROM email_outbox o WHERE o.event_id = e.id AND o.status = 'pending')
               AS emails_pending,
           (SELECT count(*) FROM email_outbox o WHERE o.event_id = e.id AND o.status = 'sending')
               AS emails_sending,
           (SELECT count(*) FROM email_outbox o WHERE o.event_id = e.id AND o.status = 'sent')
               AS emails_sent,
           (SELECT count(*) FROM email_outbox o WHERE o.event_id = e.id AND o.status = 'failed')
               AS emails_failed,
           (SELECT count(*) FROM email_outbox o WHERE o.event_id = e.id AND o.status = 'skipped')
               AS emails_skipped
      FROM events e
      LEFT JOIN registrations r ON r.event_id = e.id
     WHERE e.id = :event_id
     GROUP BY e.id
    """
)

_LIST = text(
    """
    SELECT r.id, r.email, r.status::text AS status, r.ticket_code, r.created_at,
           r.checked_in_at,
           CASE WHEN r.status = 'waitlisted'
                THEN row_number() OVER (PARTITION BY r.status = 'waitlisted' ORDER BY r.queue_seq)
           END AS waitlist_position
      FROM registrations r
     WHERE r.event_id = :event_id
       AND (CAST(:status AS registration_status) IS NULL
            OR r.status = CAST(:status AS registration_status))
     -- seat holders / cancelled first by registration time, then the waitlist in queue order
     -- (promoted rows keep their old queue_seq, so it must only order waitlisted rows)
     ORDER BY (r.status = 'waitlisted'),
              CASE WHEN r.status = 'waitlisted' THEN r.queue_seq END,
              r.created_at, r.id
    """
)


@dataclass(frozen=True)
class Stats:
    capacity: int
    confirmed: int
    checked_in: int
    waitlisted: int
    cancelled: int
    emails: dict[str, int]

    @property
    def registered(self) -> int:
        """Seat holders: confirmed (not arrived yet) + checked in."""
        return self.confirmed + self.checked_in

    @property
    def seats_left(self) -> int:
        return self.capacity - self.registered


async def event_stats(sessionmaker: async_sessionmaker[AsyncSession], event_id: uuid.UUID) -> Stats:
    async with sessionmaker() as session:
        row = (await session.execute(_STATS, {"event_id": event_id})).one_or_none()
    if row is None:
        raise not_found("event_not_found", "Event not found.")
    return Stats(
        capacity=row.capacity,
        confirmed=row.confirmed,
        checked_in=row.checked_in,
        waitlisted=row.waitlisted,
        cancelled=row.cancelled,
        emails={
            "pending": row.emails_pending,
            "sending": row.emails_sending,
            "sent": row.emails_sent,
            "failed": row.emails_failed,
            "skipped": row.emails_skipped,
        },
    )


@dataclass(frozen=True)
class RegistrationRow:
    id: uuid.UUID
    email: str
    status: RegistrationStatus
    ticket_code: str
    waitlist_position: int | None
    created_at: datetime
    checked_in_at: datetime | None


async def list_registrations(
    sessionmaker: async_sessionmaker[AsyncSession],
    event_id: uuid.UUID,
    status: RegistrationStatus | None,
) -> list[RegistrationRow]:
    async with sessionmaker() as session:
        exists = await session.scalar(text("SELECT 1 FROM events WHERE id = :e"), {"e": event_id})
        if not exists:
            raise not_found("event_not_found", "Event not found.")
        rows = await session.execute(
            _LIST, {"event_id": event_id, "status": status.value if status else None}
        )
        return [
            RegistrationRow(
                id=r.id,
                email=r.email,
                status=RegistrationStatus(r.status),
                ticket_code=r.ticket_code,
                waitlist_position=r.waitlist_position,
                created_at=r.created_at,
                checked_in_at=r.checked_in_at,
            )
            for r in rows
        ]
