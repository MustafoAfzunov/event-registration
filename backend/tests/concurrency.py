"""Tools that make concurrency tests prove a race actually happened, instead of hoping.

`event_lock_gate` holds `SELECT ... FOR UPDATE` on the event row from a separate connection.
The test fires N requests; `wait_for_lock_waiters` polls pg_locks until N backends are
blocked waiting for that lock; releasing the gate then lets all N race for it at once."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

WAITERS_SQL = text(
    "SELECT count(DISTINCT l.pid) FROM pg_locks l "
    "JOIN pg_stat_activity a ON a.pid = l.pid "
    "WHERE NOT l.granted AND a.datname = current_database()"
)


@asynccontextmanager
async def event_lock_gate(engine: AsyncEngine, event_id: str) -> AsyncIterator[None]:
    async with engine.connect() as conn:
        transaction = await conn.begin()
        await conn.execute(
            text("SELECT 1 FROM events WHERE id = :e FOR UPDATE"), {"e": uuid.UUID(event_id)}
        )
        try:
            yield
        finally:
            await transaction.commit()


async def wait_for_lock_waiters(engine: AsyncEngine, expected: int, within: float = 15.0) -> int:
    """Block until at least `expected` backends wait on a lock; return the count seen."""
    seen = 0
    try:
        async with asyncio.timeout(within), engine.connect() as raw:
            # AUTOCOMMIT: pg_stat_activity is snapshotted once per transaction, so polling
            # inside one long transaction would keep returning the first, stale snapshot.
            conn = await raw.execution_options(isolation_level="AUTOCOMMIT")
            while True:
                seen = int(await conn.scalar(WAITERS_SQL) or 0)
                if seen >= expected:
                    return seen
                await asyncio.sleep(0.01)
    except TimeoutError:
        raise AssertionError(
            f"only {seen}/{expected} requests were waiting on the event lock"
        ) from None
