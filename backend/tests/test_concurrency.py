"""Real concurrency against real Postgres (no mocks).

Requests run in parallel through the ASGI app; each holds its own pooled DB connection, so
contention happens inside Postgres. Where the test claims "at the same moment", the event
lock gate (tests/concurrency.py) holds the lock until every request is *proven* (pg_locks)
to be waiting, then releases them all at once."""

import asyncio
import random
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from tests.concurrency import event_lock_gate, wait_for_lock_waiters
from tests.helpers import cancel, create_event, outbox, register, registrations, statuses, token_for
from tests.invariants import assert_invariants


async def _race(engine: AsyncEngine, event_id: str, coros: list[Any]) -> list[Response]:
    """Start all coroutines while the event lock is held, wait until all are blocked on it,
    then release. Returns responses in the order the coroutines were given."""
    async with event_lock_gate(engine, event_id):
        tasks = [asyncio.create_task(c) for c in coros]
        await wait_for_lock_waiters(engine, len(tasks))
    return await asyncio.gather(*tasks)


async def test_20_parallel_registrations_5_seats(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    emails = [f"user{i}@example.com" for i in range(20)]

    responses = await _race(engine, event_id, [register(client, event_id, e) for e in emails])

    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    bodies = [r.json() for r in responses]
    confirmed = [b for b in bodies if b["status"] == "confirmed"]
    waitlisted = [b for b in bodies if b["status"] == "waitlisted"]
    assert len(confirmed) == 5
    assert len(waitlisted) == 15
    # Positions handed out under the lock are exactly 1..15, no duplicates, no gaps.
    assert sorted(b["waitlist_position"] for b in waitlisted) == list(range(1, 16))
    assert await statuses(engine, event_id) == {"confirmed": 5, "waitlisted": 15}
    seqs = sorted(r["queue_seq"] for r in await registrations(engine, event_id) if r["queue_seq"])
    assert len(seqs) == len(set(seqs)) == 15
    await assert_invariants(engine, event_id)


async def test_100_parallel_registrations_10_seats_never_overbook(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    """No gate: natural contention with more requests than the pool has connections."""
    event_id = await create_event(admin, clock, capacity=10)
    responses = await asyncio.gather(
        *[register(client, event_id, f"p{i}@example.com") for i in range(100)]
    )
    assert all(r.status_code == 201 for r in responses)
    assert await statuses(engine, event_id) == {"confirmed": 10, "waitlisted": 90}
    await assert_invariants(engine, event_id)


async def test_last_seat_race_one_confirmed_one_waitlisted(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    for round_ in range(25):
        event_id = await create_event(admin, clock, capacity=3, title=f"Race {round_}")
        for i in range(2):
            assert (await register(client, event_id, f"early{i}@example.com")).status_code == 201

        a, b = await _race(
            engine,
            event_id,
            [
                register(client, event_id, "alice@example.com"),
                register(client, event_id, "bob@example.com"),
            ],
        )

        outcomes = sorted([a.json()["status"], b.json()["status"]])
        assert outcomes == ["confirmed", "waitlisted"], f"round {round_}: {outcomes}"
        assert await statuses(engine, event_id) == {"confirmed": 3, "waitlisted": 1}
        await assert_invariants(engine, event_id)


@pytest.mark.parametrize(
    "variants",
    [
        ["same@example.com"] * 10,
        ["Same@Example.com", " same@example.com", "SAME@EXAMPLE.COM ", "same@EXAMPLE.com"] * 2
        + ["\tsame@example.com", "sAmE@eXaMpLe.CoM"],
    ],
    ids=["identical", "case_whitespace_variants"],
)
async def test_concurrent_same_email_creates_one_row(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    variants: list[str],
) -> None:
    event_id = await create_event(admin, clock, capacity=5)

    responses = await _race(engine, event_id, [register(client, event_id, v) for v in variants])

    codes = sorted(r.status_code for r in responses)
    assert codes == [200] * 9 + [201], codes
    assert sum(r.json()["created"] for r in responses) == 1
    rows = await registrations(engine, event_id)
    assert len(rows) == 1 and rows[0]["email_normalized"] == "same@example.com"
    assert len(await outbox(engine, event_id)) == 1  # exactly one ticket email enqueued
    await assert_invariants(engine, event_id)


async def test_parallel_cancels_and_registrations_keep_invariants(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    """5 seats held, 10 waiting. Then 5 holders cancel while 10 newcomers register, all at
    once in random order. Expected: seats go to the 5 OLDEST waitlisters (FIFO), every
    newcomer is waitlisted behind the rest, and confirmed never exceeds 5, even mid-run."""
    event_id = await create_event(admin, clock, capacity=5)
    holders = [f"holder{i}@example.com" for i in range(5)]
    waiters = [f"waiter{i}@example.com" for i in range(10)]
    newcomers = [f"new{i}@example.com" for i in range(10)]
    for email in holders + waiters:  # sequential: defines the queue order
        assert (await register(client, event_id, email)).status_code == 201
    tokens = [await token_for(engine, event_id, e) for e in holders]

    ops = [cancel(client, t) for t in tokens] + [register(client, event_id, e) for e in newcomers]
    random.shuffle(ops)

    samples: list[int] = []
    stop = asyncio.Event()

    async def observe() -> None:
        async with engine.connect() as conn:
            while not stop.is_set():
                samples.append(
                    int(
                        await conn.scalar(
                            text(
                                "SELECT count(*) FROM registrations WHERE event_id = "
                                "CAST(:e AS uuid) AND status IN ('confirmed', 'checked_in')"
                            ),
                            {"e": event_id},
                        )
                        or 0
                    )
                )
                await asyncio.sleep(0)

    observer = asyncio.create_task(observe())
    responses = await _race(engine, event_id, ops)
    stop.set()
    await observer

    assert all(r.status_code in (200, 201) for r in responses), [r.text for r in responses]
    assert samples and max(samples) <= 5, f"confirmed exceeded capacity mid-run: {max(samples)}"

    by_email = {r["email"]: r["status"] for r in await registrations(engine, event_id)}
    assert [by_email[e] for e in holders] == ["cancelled"] * 5
    assert [by_email[e] for e in waiters[:5]] == ["confirmed"] * 5  # oldest five promoted
    assert [by_email[e] for e in waiters[5:]] == ["waitlisted"] * 5
    assert [by_email[e] for e in newcomers] == ["waitlisted"] * 10  # nobody jumped the queue
    await assert_invariants(engine, event_id)
