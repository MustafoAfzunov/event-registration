"""Reminder scheduler (ARCHITECTURE 4.7, DECISIONS D-008, D-067).

DB-driven and restart-safe: there are no in-memory timers. Every tick asks the database
"which scheduled event is inside its reminder window and still has a confirmed participant
without a reminder for the CURRENT schedule version?", takes that event with
`FOR UPDATE SKIP LOCKED`, and enqueues the missing reminders into the email outbox, all in
one transaction. Then the next event, until none is left.

Why this gives "exactly one reminder per confirmed participant per event date":
  * the outbox row's dedupe key `reminder:{event}:v{schedule_version}:{email}` IS the record
    that a reminder exists: a second tick, a second scheduler instance or a restart finds it
    and enqueues nothing;
  * SKIP LOCKED partitions events between concurrent scheduler instances, and while the
    event row is locked no registration/cancel/reschedule for it can run (they lock it too),
    so the confirmed set and schedule_version are stable while we enqueue;
  * a crash before commit rolls everything back: the next tick simply does it again;
  * delivery reuses the outbox dispatcher (lease, fencing, retry; phase 3), and the
    dispatcher re-validates every reminder right before sending (see dispatcher._prepare_
    reminder): event still scheduled, same schedule_version, not started, person still
    confirmed. Otherwise the row is marked `skipped`.

Policies (ARCHITECTURE A6, E16-E18):
  * window = [starts_at - REMINDER_LEAD, starts_at). An event created, rescheduled, or a
    person confirmed/promoted, when already inside the window gets the reminder at the next
    tick;
  * downtime: reminders missed while the worker was down are sent late if the event has
    not started yet; never after the start;
  * reschedule bumps schedule_version, so the new date gets its own reminders;
  * a `skipped` reminder is re-armed if the same person is confirmed again inside the
    window (e.g. cancelled, then re-registered); a `sent` one never is."""

import asyncio
import contextlib
import logging
import uuid
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clock import Clock
from app.config import Settings
from app.emails import templates
from app.live.broker import notify_event_changed
from app.models import EmailKind, EmailOutbox, Event, OutboxStatus, Registration, RegistrationStatus

logger = logging.getLogger(__name__)


def reminder_key(event_id: uuid.UUID, schedule_version: int, email_normalized: str) -> str:
    return f"reminder:{event_id}:v{schedule_version}:{email_normalized}"


# The next due event that still needs work, locked so no other scheduler takes it.
# The dedupe key is built exactly like reminder_key(). It is written ':' || 'v' in SQL because
# a colon directly followed by a letter would be parsed as a bind parameter by text().
_NEXT_DUE_EVENT = text(
    """
    SELECT e.id
      FROM events e
     WHERE e.status = 'scheduled'
       AND e.starts_at - make_interval(secs => :lead) <= :now
       AND :now < e.starts_at
       AND EXISTS (
             SELECT 1 FROM registrations r
              WHERE r.event_id = e.id AND r.status = 'confirmed'
                AND NOT EXISTS (
                      SELECT 1 FROM email_outbox o
                       WHERE o.dedupe_key = 'reminder:' || e.id || ':' || 'v' || e.schedule_version
                                            || ':' || r.email_normalized
                         AND o.status <> 'skipped'))
     ORDER BY e.starts_at, e.id
     LIMIT 1
       FOR UPDATE OF e SKIP LOCKED
    """
)


class Scheduler:
    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], clock: Clock, settings: Settings
    ) -> None:
        self.sessionmaker = sessionmaker
        self.clock = clock
        self.settings = settings

    async def tick(self) -> list[uuid.UUID]:
        """Enqueue every due reminder. Returns the events for which THIS instance enqueued
        (or re-armed) at least one reminder."""
        handled: list[uuid.UUID] = []
        for _ in range(self.settings.scheduler_max_events_per_tick):
            visit = await self.enqueue_next_event()
            if visit is None:
                break
            event_id, enqueued = visit
            if enqueued:
                handled.append(event_id)
        return handled

    async def enqueue_next_event(self) -> tuple[uuid.UUID, int] | None:
        """Lock the next due event and enqueue its missing reminders.

        Under READ COMMITTED another instance may have just finished this very event: our
        query snapshot was taken before its commit, and SKIP LOCKED only skips rows that are
        locked *at that moment*. Then the INSERT below hits ON CONFLICT for every row and
        enqueues 0. That is why the unique dedupe key, not SKIP LOCKED, is the exactly-once
        guarantee; SKIP LOCKED only keeps instances from waiting on each other (D-067)."""
        now = self.clock.now()
        async with self.sessionmaker() as session, session.begin():
            event_id = await session.scalar(
                _NEXT_DUE_EVENT, {"now": now, "lead": self.settings.reminder_lead_seconds}
            )
            if event_id is None:
                return None
            event = await session.get(Event, event_id)
            assert event is not None
            confirmed = (
                await session.scalars(
                    select(Registration).where(
                        Registration.event_id == event_id,
                        Registration.status == RegistrationStatus.confirmed,
                    )
                )
            ).all()
            rows = []
            for reg in confirmed:
                rendered = templates.reminder(
                    event.title,
                    event.starts_at,
                    reg.ticket_code,
                    self.settings.public_base_url,
                    reg.manage_token,
                )
                rows.append(
                    {
                        "kind": EmailKind.reminder,
                        "dedupe_key": reminder_key(
                            event.id, event.schedule_version, reg.email_normalized
                        ),
                        "event_id": event.id,
                        "registration_id": reg.id,
                        "schedule_version": event.schedule_version,
                        "to_email": reg.email,
                        "subject": rendered.subject,
                        "body_text": rendered.body,
                        "next_attempt_at": now,
                        "created_at": now,
                    }
                )
            if not rows:  # cannot happen (the query requires a confirmed person); be safe
                return event.id, 0
            stmt = insert(EmailOutbox).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["dedupe_key"],
                # Re-arm only a reminder that was skipped (person was not confirmed when it was
                # about to be sent); a sent/pending/failed one is left alone.
                set_={
                    "status": OutboxStatus.pending,
                    "registration_id": stmt.excluded.registration_id,
                    "to_email": stmt.excluded.to_email,
                    "subject": stmt.excluded.subject,
                    "body_text": stmt.excluded.body_text,
                    "next_attempt_at": stmt.excluded.next_attempt_at,
                    "locked_until": None,
                    "last_error": None,
                },
                where=EmailOutbox.status == OutboxStatus.skipped,
            )
            # RETURNING lists exactly the rows inserted or re-armed (rowcount is not reliable
            # for multi-row INSERT ... ON CONFLICT through the driver: it reported -1).
            result = await session.execute(stmt.returning(EmailOutbox.id))
            enqueued = len(result.all())
            if enqueued:
                await notify_event_changed(session, event.id)  # email counts in organizer stats
                logger.info(
                    "reminders enqueued for event %s (v%s): %s",
                    event.id,
                    event.schedule_version,
                    enqueued,
                )
            return event.id, enqueued

    async def run(self, stop: asyncio.Event) -> None:
        heartbeat = Path(self.settings.scheduler_heartbeat_file)
        while not stop.is_set():
            await asyncio.to_thread(heartbeat.touch)
            try:
                await self.tick()
            except Exception:  # keep the loop alive; the next tick retries everything
                logger.exception("scheduler tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.settings.scheduler_tick_seconds)
