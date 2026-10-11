"""Outbox dispatcher (ARCHITECTURE 4.5, DECISIONS D-007, D-043).

Guarantees:
  * enqueue is exactly-once (business transaction + unique dedupe_key);
  * delivery is AT-LEAST-ONCE: a row is marked `sent` only after the SMTP server accepted it.
    The single duplicate window is "SMTP accepted, then crash before the DB commit"; the copy
    carries the same Message-ID. Every other crash/restart point causes no duplicate.

Mechanics:
  * claim: one UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED) moves a batch to
    `sending`, sets a lease (`locked_until`) and increments `attempts`;
  * N dispatchers can run concurrently: SKIP LOCKED + the status change mean a row is claimed
    by exactly one of them;
  * a row whose lease expired (its worker died) is claimable again;
  * fencing: `attempts` after the claim is the claim token. Completion updates require
    `status='sending' AND attempts=:token`, so a worker that lost its lease can never
    overwrite the outcome of the worker that re-claimed the row;
  * SMTP failure -> back to `pending` with exponential backoff; after max attempts -> `failed`.
"""

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clock import Clock
from app.config import Settings
from app.emails.smtp import Sender, build_message

logger = logging.getLogger(__name__)

_CLAIM = text(
    """
    UPDATE email_outbox
       SET status = 'sending', attempts = attempts + 1, locked_until = :lease_until
     WHERE id IN (
           SELECT id FROM email_outbox
            WHERE (status = 'pending' AND next_attempt_at <= :now)
               OR (status = 'sending' AND locked_until < :now)
            ORDER BY id
            LIMIT :limit
              FOR UPDATE SKIP LOCKED)
    RETURNING id, kind::text AS kind, dedupe_key, to_email, subject, body_text, attempts,
              event_id, registration_id
    """
)
# Every completion is fenced: WHERE id = :id AND status = 'sending' AND attempts = :token.
_MARK_SENT = text(
    "UPDATE email_outbox SET status = 'sent', sent_at = :now, locked_until = NULL, "
    "last_error = NULL WHERE id = :id AND status = 'sending' AND attempts = :token"
)
_RETRY_LATER = text(
    "UPDATE email_outbox SET status = 'pending', next_attempt_at = :next, locked_until = NULL, "
    "last_error = :error WHERE id = :id AND status = 'sending' AND attempts = :token"
)
_GIVE_UP = text(
    "UPDATE email_outbox SET status = 'failed', locked_until = NULL, last_error = :error "
    "WHERE id = :id AND status = 'sending' AND attempts = :token"
)
_RELEASE = text(
    "UPDATE email_outbox SET status = 'pending', locked_until = NULL "
    "WHERE id = :id AND status = 'sending' AND attempts = :token"
)


@dataclass(frozen=True)
class Claimed:
    id: int
    kind: str
    dedupe_key: str
    to_email: str
    subject: str
    body_text: str
    attempts: int  # == claim (fencing) token
    event_id: uuid.UUID
    registration_id: uuid.UUID | None


class Dispatcher:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        sender: Sender,
        clock: Clock,
        settings: Settings,
    ) -> None:
        worst_case = settings.outbox_batch_size * (
            settings.smtp_timeout_seconds + settings.outbox_send_interval_seconds
        )
        if settings.outbox_lease_seconds <= worst_case:
            # Otherwise another worker could re-claim rows this one is still sending.
            raise ValueError(
                f"OUTBOX_LEASE_SECONDS ({settings.outbox_lease_seconds}) must exceed "
                f"batch_size * (smtp_timeout + send_interval) = {worst_case}"
            )
        self.sessionmaker = sessionmaker
        self.sender = sender
        self.clock = clock
        self.settings = settings

    def backoff(self, attempts: int) -> timedelta:
        seconds = self.settings.outbox_backoff_base_seconds * 2 ** max(attempts - 1, 0)
        return timedelta(seconds=min(seconds, self.settings.outbox_backoff_max_seconds))

    async def claim(self) -> list[Claimed]:
        now = self.clock.now()
        lease_until = now + timedelta(seconds=self.settings.outbox_lease_seconds)
        async with self.sessionmaker() as session, session.begin():
            rows = await session.execute(
                _CLAIM,
                {"now": now, "lease_until": lease_until, "limit": self.settings.outbox_batch_size},
            )
            claimed = [Claimed(**row._mapping) for row in rows]
        return sorted(claimed, key=lambda c: c.id)

    async def _complete(self, statement: TextClause, item: Claimed, **params: object) -> bool:
        async with self.sessionmaker() as session, session.begin():
            result = await session.execute(
                statement, {"id": item.id, "token": item.attempts, **params}
            )
        if not getattr(result, "rowcount", 0):
            logger.warning("outbox %s: lost the claim (lease expired and re-claimed)", item.id)
            return False
        return True

    async def mark_sent(self, item: Claimed) -> bool:
        return await self._complete(_MARK_SENT, item, now=self.clock.now())

    async def mark_failed_attempt(self, item: Claimed, error: str) -> bool:
        if item.attempts >= self.settings.outbox_max_attempts:
            logger.error(
                "outbox %s (%s): giving up after %s attempts", item.id, item.kind, item.attempts
            )
            return await self._complete(_GIVE_UP, item, error=error)
        next_at: datetime = self.clock.now() + self.backoff(item.attempts)
        return await self._complete(_RETRY_LATER, item, next=next_at, error=error)

    async def release(self, item: Claimed) -> bool:
        """Hand an unsent row back immediately (graceful shutdown)."""
        return await self._complete(_RELEASE, item)

    async def deliver(self, item: Claimed) -> bool:
        message = build_message(
            mail_from=self.settings.mail_from,
            to=item.to_email,
            subject=item.subject,
            body=item.body_text,
            dedupe_key=item.dedupe_key,
        )
        try:
            await self.sender.send(message)
        except Exception as exc:  # SMTP / network / timeout: retry later
            error = f"{type(exc).__name__}: {exc}"[:500]
            logger.warning(
                "outbox %s (%s) attempt %s failed: %s", item.id, item.kind, item.attempts, error
            )
            await self.mark_failed_attempt(item, error)
            return False
        # Never log the body: it holds the ticket code and manage link.
        logger.info("outbox %s (%s) sent, attempt %s", item.id, item.kind, item.attempts)
        return await self.mark_sent(item)

    async def run_once(self, stop: asyncio.Event | None = None) -> int:
        """Claim one batch and process it. Returns the number of rows claimed."""
        claimed = await self.claim()
        for index, item in enumerate(claimed):
            if stop is not None and stop.is_set():
                for rest in claimed[index:]:
                    await self.release(rest)
                break
            if index and self.settings.outbox_send_interval_seconds:
                await asyncio.sleep(self.settings.outbox_send_interval_seconds)
            await self.deliver(item)
        return len(claimed)

    async def run_until_idle(self, max_batches: int = 1000) -> int:
        """Test/ops helper: process batches until nothing is due. Returns rows claimed."""
        total = 0
        for _ in range(max_batches):
            claimed = await self.run_once()
            if not claimed:
                return total
            total += claimed
        raise RuntimeError("outbox not idle after max_batches")

    async def run(self, stop: asyncio.Event) -> None:
        heartbeat = Path(self.settings.worker_heartbeat_file)
        while not stop.is_set():
            await asyncio.to_thread(heartbeat.touch)
            try:
                claimed = await self.run_once(stop)
            except Exception:  # DB hiccup etc.: log, back off, keep the worker alive
                logger.exception("dispatcher loop error")
                claimed = 0
            if not claimed:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self.settings.outbox_poll_seconds)
