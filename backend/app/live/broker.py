"""Cross-process fan-out of "event X changed" signals (ARCHITECTURE 4.9, DECISIONS D-010).

Writers call `notify_event_changed` inside their transaction; Postgres delivers the NOTIFY to
every LISTENing connection only when that transaction commits (never on rollback). Each
backend process runs ONE Broker = one dedicated LISTEN connection, and wakes only the SSE
subscribers of that event. Because every uvicorn worker (and every replica) has its own
listener, a change made by any process reaches clients connected to any other process.

Signals carry no data, only the event id. Subscribers re-read a snapshot from the DB, so a
lost, duplicated or coalesced signal can never leave a client with wrong numbers. If the
LISTEN connection drops, the broker reconnects and wakes EVERY subscriber ("resync"):
changes committed while nobody was listening are picked up by that re-read."""

import asyncio
import contextlib
import logging
import uuid
from collections import defaultdict

import psycopg
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CHANNEL = "event_changed"


async def notify_event_changed(session: AsyncSession, event_id: uuid.UUID) -> None:
    """Call inside the business transaction; delivered on commit only."""
    await session.execute(
        text("SELECT pg_notify(:channel, :event_id)"),
        {"channel": CHANNEL, "event_id": str(event_id)},
    )


class Subscription:
    def __init__(self, broker: "Broker", event_id: str) -> None:
        self._broker = broker
        self.event_id = event_id
        self._changed = asyncio.Event()

    def wake(self) -> None:
        self._changed.set()

    async def wait(self, within: float) -> bool:
        """True if woken (one or more signals since the last wait), False on timeout.
        Several signals while the consumer is busy collapse into one wake-up."""
        try:
            await asyncio.wait_for(self._changed.wait(), within)
        except TimeoutError:
            return False
        self._changed.clear()
        return True

    def close(self) -> None:
        self._broker._remove(self)


class Broker:
    def __init__(self, database_url: str, reconnect_delay: float = 1.0) -> None:
        # SQLAlchemy URL (postgresql+psycopg://...) -> libpq conninfo for a raw psycopg conn.
        self._conninfo = (
            make_url(database_url)
            .set(drivername="postgresql")
            .render_as_string(hide_password=False)
        )
        self._reconnect_delay = reconnect_delay
        self._subscribers: dict[str, set[Subscription]] = defaultdict(set)
        self._task: asyncio.Task[None] | None = None
        self.connected = asyncio.Event()

    def subscribe(self, event_id: uuid.UUID) -> Subscription:
        self._ensure_started()
        subscription = Subscription(self, str(event_id))
        self._subscribers[subscription.event_id].add(subscription)
        return subscription

    def _remove(self, subscription: Subscription) -> None:
        subs = self._subscribers.get(subscription.event_id)
        if subs is not None:
            subs.discard(subscription)
            if not subs:
                del self._subscribers[subscription.event_id]

    def subscriber_count(self) -> int:
        return sum(len(s) for s in self._subscribers.values())

    def _ensure_started(self) -> None:
        # Started lazily on first use: works under uvicorn and in tests without a lifespan.
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="live-broker")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def _dispatch(self, event_id: str) -> None:
        for subscription in list(self._subscribers.get(event_id, ())):
            subscription.wake()

    def _wake_all(self) -> None:
        for subs in list(self._subscribers.values()):
            for subscription in list(subs):
                subscription.wake()

    async def _run(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._conninfo, autocommit=True
                ) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    self.connected.set()
                    # Anything committed while we were not listening: make everyone re-read.
                    self._wake_all()
                    logger.info("live broker listening on %r", CHANNEL)
                    async for note in conn.notifies():
                        self._dispatch(note.payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("live broker: LISTEN connection lost; reconnecting", exc_info=True)
            self.connected.clear()
            await asyncio.sleep(self._reconnect_delay)
