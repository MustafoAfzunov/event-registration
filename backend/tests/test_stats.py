"""Organizer stats: correct after EVERY kind of transition, and never inconsistent while
writes are in flight (single-statement snapshot)."""

import asyncio
import random
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from app.emails.dispatcher import Dispatcher
from tests.helpers import cancel, create_event, register, registrations, token_for
from tests.invariants import assert_invariants
from tests.mailpit import Mailpit
from tests.senders import DEAD_SMTP

COUNTS = (
    "capacity",
    "confirmed",
    "checked_in",
    "registered",
    "waitlisted",
    "cancelled",
    "seats_left",
)


async def _stats(admin: AsyncClient, event_id: str) -> dict[str, Any]:
    response = await admin.get(f"/api/admin/events/{event_id}/stats")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _recount(engine: AsyncEngine, event_id: str) -> dict[str, int]:
    """Independent computation straight from the tables (no shared code with the service)."""
    async with engine.connect() as conn:
        capacity = await conn.scalar(
            text("SELECT capacity FROM events WHERE id = :e"), {"e": uuid.UUID(event_id)}
        )
    by_status: dict[str, int] = {}
    for row in await registrations(engine, event_id):
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    confirmed, checked_in = by_status.get("confirmed", 0), by_status.get("checked_in", 0)
    return {
        "capacity": int(capacity),
        "confirmed": confirmed,
        "checked_in": checked_in,
        "registered": confirmed + checked_in,
        "waitlisted": by_status.get("waitlisted", 0),
        "cancelled": by_status.get("cancelled", 0),
        "seats_left": int(capacity) - confirmed - checked_in,
    }


async def _expect(
    admin: AsyncClient, engine: AsyncEngine, event_id: str, step: str, **expected: int
) -> None:
    stats = await _stats(admin, event_id)
    got = {k: stats[k] for k in COUNTS}
    want = {**got, **expected}
    assert got == want, f"after '{step}': {got} != expected {want}"
    assert got == await _recount(engine, event_id), f"after '{step}': API disagrees with DB"
    await assert_invariants(engine, event_id)


async def test_stats_after_every_kind_of_transition(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=3)
    e = lambda **kw: _expect(admin, engine, event_id, **kw)  # noqa: E731
    checkin = lambda code: admin.post(f"/api/admin/events/{event_id}/checkin", json={"code": code})  # noqa: E731

    async def code_of(email: str) -> str:
        return str(
            next(
                r["ticket_code"]
                for r in await registrations(engine, event_id)
                if r["email"] == email and r["status"] != "cancelled"
            )
        )

    async def leave(email: str) -> None:
        assert (await cancel(client, await token_for(engine, event_id, email))).status_code == 200

    await e(
        step="created",
        capacity=3,
        confirmed=0,
        checked_in=0,
        registered=0,
        waitlisted=0,
        cancelled=0,
        seats_left=3,
    )

    for email in ["a@x.io", "b@x.io", "c@x.io"]:
        await register(client, event_id, email)
    await e(step="3 confirmed (full)", confirmed=3, registered=3, waitlisted=0, seats_left=0)

    await register(client, event_id, "d@x.io")
    await register(client, event_id, "e@x.io")
    await e(step="2 waitlisted", confirmed=3, waitlisted=2, seats_left=0)

    await register(client, event_id, "A@X.io")  # duplicate: no change
    await e(step="duplicate registration", confirmed=3, waitlisted=2, cancelled=0)

    await leave("e@x.io")
    await e(step="waitlisted cancels", confirmed=3, waitlisted=1, cancelled=1, seats_left=0)

    await leave("a@x.io")  # d promoted
    await e(
        step="confirmed cancels -> promotion", confirmed=3, waitlisted=0, cancelled=2, seats_left=0
    )

    assert (await checkin(await code_of("b@x.io"))).status_code == 200
    await e(step="check-in", confirmed=2, checked_in=1, registered=3, seats_left=0)

    assert (await checkin(await code_of("b@x.io"))).status_code == 409
    assert (await checkin("ZZZZ-9999")).status_code == 404
    await e(step="failed check-ins change nothing", confirmed=2, checked_in=1, cancelled=2)

    await leave("c@x.io")  # free seat, nobody waiting
    await e(
        step="cancel with empty waitlist",
        confirmed=1,
        checked_in=1,
        registered=2,
        seats_left=1,
        cancelled=3,
    )

    await register(client, event_id, "a@x.io")  # re-register after cancel: takes the free seat
    await e(
        step="re-register after cancel",
        confirmed=2,
        checked_in=1,
        registered=3,
        seats_left=0,
        cancelled=3,
    )

    for email in ["f@x.io", "g@x.io", "h@x.io"]:
        await register(client, event_id, email)
    await e(step="3 more waitlisted", waitlisted=3, seats_left=0)

    r = await admin.patch(f"/api/admin/events/{event_id}", json={"capacity": 5})
    assert r.json()["promoted_count"] == 2
    await e(
        step="capacity 3 -> 5 promotes 2",
        capacity=5,
        confirmed=4,
        checked_in=1,
        registered=5,
        waitlisted=1,
        seats_left=0,
    )

    assert (
        await admin.patch(f"/api/admin/events/{event_id}", json={"capacity": 4})
    ).status_code == 409
    await e(step="rejected capacity decrease", capacity=5, registered=5)

    await leave("f@x.io")  # promoted earlier; frees a seat -> h promoted
    await e(
        step="promoted person cancels -> next promoted",
        confirmed=4,
        waitlisted=0,
        cancelled=4,
        seats_left=0,
    )

    await leave("h@x.io")
    r = await admin.patch(f"/api/admin/events/{event_id}", json={"capacity": 4})
    assert r.status_code == 200
    await e(
        step="capacity decreased to taken",
        capacity=4,
        confirmed=3,
        checked_in=1,
        registered=4,
        seats_left=0,
        cancelled=5,
    )

    for email in ["a@x.io", "d@x.io", "g@x.io"]:
        assert (await checkin(await code_of(email))).status_code == 200
    await e(step="everyone arrived", confirmed=0, checked_in=4, registered=4, seats_left=0)


async def test_stats_email_counts(
    client: AsyncClient,
    admin: AsyncClient,
    clock: FixedClock,
    mailpit: Mailpit,
    make_dispatcher: Callable[..., Dispatcher],
) -> None:
    event_id = await create_event(admin, clock, capacity=1)
    await register(client, event_id, "a@example.com")
    await register(client, event_id, "b@example.com")
    assert (await _stats(admin, event_id))["emails"] == {
        "pending": 2,
        "sending": 0,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
    }

    await make_dispatcher().run_until_idle()
    assert (await _stats(admin, event_id))["emails"]["sent"] == 2

    await register(client, event_id, "c@example.com")
    await make_dispatcher(DEAD_SMTP, outbox_max_attempts=1).run_until_idle()
    assert (await _stats(admin, event_id))["emails"] == {
        "pending": 0,
        "sending": 0,
        "sent": 2,
        "failed": 1,
        "skipped": 0,
    }


async def test_stats_never_inconsistent_during_concurrent_writes(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    """While registrations, cancels (with promotions) and check-ins run in parallel, every
    stats snapshot taken must satisfy the invariants."""
    event_id = await create_event(admin, clock, capacity=10)
    for i in range(15):
        await register(client, event_id, f"early{i}@x.io")
    rows = await registrations(engine, event_id)
    holders = [r for r in rows if r["status"] == "confirmed"]
    tokens = [await token_for(engine, event_id, r["email"]) for r in holders[:5]]
    codes = [str(r["ticket_code"]) for r in holders[5:]]

    ops = (
        [register(client, event_id, f"late{i}@x.io") for i in range(15)]
        + [cancel(client, t) for t in tokens]
        + [admin.post(f"/api/admin/events/{event_id}/checkin", json={"code": c}) for c in codes]
    )
    random.shuffle(ops)

    snapshots: list[dict[str, Any]] = []
    done = asyncio.Event()

    async def watch() -> None:
        while not done.is_set():
            snapshots.append(await _stats(admin, event_id))

    watcher = asyncio.create_task(watch())
    results = await asyncio.gather(*ops)
    done.set()
    await watcher

    assert all(r.status_code in (200, 201) for r in results), [
        r.text for r in results if r.status_code >= 300
    ]
    assert len(snapshots) > 5
    for s in snapshots:
        assert s["registered"] == s["confirmed"] + s["checked_in"]
        assert 0 <= s["seats_left"] == s["capacity"] - s["registered"]
        assert not (s["seats_left"] > 0 and s["waitlisted"] > 0), f"idle seat while waiting: {s}"
    final = await _stats(admin, event_id)
    assert {k: final[k] for k in COUNTS} == await _recount(engine, event_id)
    assert (final["checked_in"], final["registered"], final["cancelled"]) == (5, 10, 5)
    await assert_invariants(engine, event_id)


async def test_stats_unknown_event_404(admin: AsyncClient) -> None:
    response = await admin.get(f"/api/admin/events/{uuid.uuid4()}/stats")
    assert (response.status_code, response.json()["error"]["code"]) == (404, "event_not_found")


async def test_stats_requires_admin(
    client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    response = await client.get(f"/api/admin/events/{event_id}/stats")
    assert (response.status_code, response.json()["error"]["code"]) == (401, "unauthorized")


async def test_registrations_list_order_filter_and_positions(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=1)
    for email in ["a@x.io", "w1@x.io", "w2@x.io", "w3@x.io"]:
        await register(client, event_id, email)
        clock.advance(timedelta(seconds=1))
    await cancel(client, await token_for(engine, event_id, "a@x.io"))  # w1 promoted

    everyone = (await admin.get(f"/api/admin/events/{event_id}/registrations")).json()
    assert [(r["email"], r["status"], r["waitlist_position"]) for r in everyone] == [
        ("a@x.io", "cancelled", None),
        ("w1@x.io", "confirmed", None),
        ("w2@x.io", "waitlisted", 1),
        ("w3@x.io", "waitlisted", 2),
    ]
    assert all(len(r["ticket_code"]) == 9 and r["ticket_code"][4] == "-" for r in everyone)

    waiting = (
        await admin.get(f"/api/admin/events/{event_id}/registrations?status=waitlisted")
    ).json()
    assert [(r["email"], r["waitlist_position"]) for r in waiting] == [
        ("w2@x.io", 1),
        ("w3@x.io", 2),
    ]
    bad = await admin.get(f"/api/admin/events/{event_id}/registrations?status=bogus")
    assert (bad.status_code, bad.json()["error"]["code"]) == (422, "validation_error")
    assert (await client.get(f"/api/admin/events/{event_id}/registrations")).status_code == 401
