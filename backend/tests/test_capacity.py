"""Organizer event CRUD (create/read/update; no delete by design) and capacity rules."""

import uuid
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from tests.helpers import create_event, outbox, register, registrations
from tests.invariants import assert_invariants


async def _patch(admin: AsyncClient, event_id: str, **body: object) -> object:
    return await admin.patch(f"/api/admin/events/{event_id}", json=body)


async def test_create_and_read_event(
    admin: AsyncClient, client: AsyncClient, clock: FixedClock
) -> None:
    starts_at = (clock.now() + timedelta(days=3)).replace(microsecond=0)
    response = await admin.post(
        "/api/admin/events",
        json={
            "title": "  Meetup ",
            "description": "Talks",
            "starts_at": starts_at.isoformat(),
            "capacity": 30,
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert created["title"] == "Meetup"
    assert created["starts_at"].endswith("Z")
    assert (created["capacity"], created["seats_left"], created["waitlist_count"]) == (30, 30, 0)
    assert created["status"] == "scheduled"

    assert (await client.get(f"/api/events/{created['id']}")).json() == created
    assert [e["id"] for e in (await client.get("/api/events")).json()] == [created["id"]]
    assert [e["id"] for e in (await admin.get("/api/admin/events")).json()] == [created["id"]]


async def test_create_event_validation(admin: AsyncClient, clock: FixedClock) -> None:
    past = (clock.now() - timedelta(minutes=1)).isoformat()
    future = (clock.now() + timedelta(days=1)).isoformat()

    r = await admin.post("/api/admin/events", json={"title": "x", "starts_at": past, "capacity": 5})
    assert (r.status_code, r.json()["error"]["code"]) == (422, "starts_in_past")
    for bad in [
        {"title": "x", "starts_at": future, "capacity": 0},
        {"title": "", "starts_at": future, "capacity": 5},
        {"title": "x", "starts_at": "2030-01-01T10:00:00", "capacity": 5},  # naive datetime
        {"title": "x", "starts_at": future, "capacity": 5, "seats_taken": 3},  # unknown field
    ]:
        r = await admin.post("/api/admin/events", json=bad)
        assert (r.status_code, r.json()["error"]["code"]) == (422, "validation_error"), bad


async def test_patch_rejects_starts_at(admin: AsyncClient, clock: FixedClock) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    r = await _patch(admin, event_id, starts_at=(clock.now() + timedelta(days=9)).isoformat())
    assert r.status_code == 422  # rescheduling has its own endpoint (phase 6)


async def test_update_title_and_description(admin: AsyncClient, clock: FixedClock) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    r = await _patch(admin, event_id, title="New title", description="New text")
    assert r.status_code == 200
    assert (r.json()["title"], r.json()["description"], r.json()["promoted_count"]) == (
        "New title",
        "New text",
        0,
    )


async def test_increase_capacity_promotes_fifo(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=1)
    for email in ["a@x.io", "w1@x.io", "w2@x.io", "w3@x.io"]:
        await register(client, event_id, email)

    r = await _patch(admin, event_id, capacity=3)

    assert r.status_code == 200
    assert (r.json()["promoted_count"], r.json()["seats_left"], r.json()["waitlist_count"]) == (
        2,
        0,
        1,
    )
    status = {row["email"]: row["status"] for row in await registrations(engine, event_id)}
    assert status == {
        "a@x.io": "confirmed",
        "w1@x.io": "confirmed",
        "w2@x.io": "confirmed",
        "w3@x.io": "waitlisted",
    }
    assert sorted(
        m["to_email"] for m in await outbox(engine, event_id) if m["kind"] == "promoted"
    ) == ["w1@x.io", "w2@x.io"]
    await assert_invariants(engine, event_id)


async def test_decrease_below_taken_rejected(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    for i in range(3):
        await register(client, event_id, f"a{i}@x.io")

    r = await _patch(admin, event_id, capacity=2)

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "capacity_below_taken"
    assert r.json()["error"]["details"] == {"seats_taken": 3}
    assert (await client.get(f"/api/events/{event_id}")).json()["capacity"] == 5
    await assert_invariants(engine, event_id)


async def test_decrease_to_taken_allowed(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    for i in range(3):
        await register(client, event_id, f"a{i}@x.io")

    r = await _patch(admin, event_id, capacity=3)

    assert r.status_code == 200 and r.json()["seats_left"] == 0
    assert (await register(client, event_id, "late@x.io")).json()["status"] == "waitlisted"
    await assert_invariants(engine, event_id)


async def test_capacity_change_after_start_rejected(admin: AsyncClient, clock: FixedClock) -> None:
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=1))
    clock.advance(timedelta(hours=2))
    r = await _patch(admin, event_id, capacity=10)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "event_started")


async def test_update_cancelled_event_rejected(
    admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE events SET status = 'cancelled' WHERE id = :e"), {"e": uuid.UUID(event_id)}
        )
    r = await _patch(admin, event_id, capacity=10)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "event_cancelled")


async def test_unknown_event_404(admin: AsyncClient, client: AsyncClient) -> None:
    missing = str(uuid.uuid4())
    assert (await client.get(f"/api/events/{missing}")).json()["error"]["code"] == "event_not_found"
    r = await _patch(admin, missing, capacity=3)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "event_not_found")


async def test_public_list_hides_past_and_cancelled(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    soon = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=1), title="Soon")
    later = await create_event(admin, clock, capacity=5, starts_in=timedelta(days=2), title="Later")
    gone = await create_event(admin, clock, capacity=5, starts_in=timedelta(days=3), title="Gone")
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE events SET status = 'cancelled' WHERE id = :e"), {"e": uuid.UUID(gone)}
        )

    assert [e["id"] for e in (await client.get("/api/events")).json()] == [soon, later]
    clock.advance(timedelta(hours=2))
    assert [e["id"] for e in (await client.get("/api/events")).json()] == [later]
    assert len((await admin.get("/api/admin/events")).json()) == 3  # organizer sees all
