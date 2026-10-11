import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from tests.helpers import cancel, create_event, outbox, register, registrations, token_for
from tests.invariants import assert_invariants


async def _status_of(engine: AsyncEngine, event_id: str) -> dict[str, str]:
    return {
        r["email"]: r["status"]
        for r in await registrations(engine, event_id)
        if r["status"] != "cancelled"
    }


async def test_cancel_confirmed_promotes_first_waitlisted(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=2)
    for email in ["a@x.io", "b@x.io", "c@x.io", "d@x.io", "e@x.io"]:
        await register(client, event_id, email)

    response = await cancel(client, await token_for(engine, event_id, "a@x.io"))

    assert response.status_code == 200 and response.json() == {"status": "cancelled"}
    assert await _status_of(engine, event_id) == {
        "b@x.io": "confirmed",
        "c@x.io": "confirmed",  # first in line got the seat
        "d@x.io": "waitlisted",
        "e@x.io": "waitlisted",
    }
    d = (
        await client.get(f"/api/registrations/{await token_for(engine, event_id, 'd@x.io')}")
    ).json()
    assert d["waitlist_position"] == 1
    promoted = [m for m in await outbox(engine, event_id) if m["kind"] == "promoted"]
    assert [m["to_email"] for m in promoted] == ["c@x.io"]  # exactly one promotion email
    assert any(
        m["kind"] == "cancelled" and m["to_email"] == "a@x.io"
        for m in await outbox(engine, event_id)
    )
    await assert_invariants(engine, event_id)


async def test_promotion_is_fifo_by_queue_seq(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=1)
    await register(client, event_id, "holder@x.io")
    queue = [f"w{i}@x.io" for i in range(1, 6)]
    for email in queue:
        await register(client, event_id, email)
    # w3 leaves the queue before their turn: they must be skipped, order otherwise kept.
    await cancel(client, await token_for(engine, event_id, "w3@x.io"))

    promoted_order = []
    current = "holder@x.io"
    for _ in range(4):
        await cancel(client, await token_for(engine, event_id, current))
        [current] = [e for e, s in (await _status_of(engine, event_id)).items() if s == "confirmed"]
        promoted_order.append(current)
        await assert_invariants(engine, event_id)

    assert promoted_order == ["w1@x.io", "w2@x.io", "w4@x.io", "w5@x.io"]


async def test_cancel_waitlisted_does_not_promote(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=1)
    for email in ["a@x.io", "b@x.io", "c@x.io"]:
        await register(client, event_id, email)

    await cancel(client, await token_for(engine, event_id, "b@x.io"))

    assert await _status_of(engine, event_id) == {"a@x.io": "confirmed", "c@x.io": "waitlisted"}
    assert not [m for m in await outbox(engine, event_id) if m["kind"] == "promoted"]
    await assert_invariants(engine, event_id)


async def test_cancel_is_idempotent(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=2)
    await register(client, event_id, "a@x.io")
    await register(client, event_id, "b@x.io")
    token = await token_for(engine, event_id, "a@x.io")

    first = await cancel(client, token)
    second = await cancel(client, token)

    assert (first.status_code, second.status_code) == (200, 200)
    assert second.json() == {"status": "cancelled"}
    event = (await client.get(f"/api/events/{event_id}")).json()
    assert event["seats_left"] == 1  # seat freed once, not twice
    assert len([m for m in await outbox(engine, event_id) if m["kind"] == "cancelled"]) == 1
    await assert_invariants(engine, event_id)


async def test_cancel_after_event_start_rejected(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=2, starts_in=timedelta(hours=1))
    await register(client, event_id, "a@x.io")
    clock.advance(timedelta(hours=2))

    response = await cancel(client, await token_for(engine, event_id, "a@x.io"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "event_started"
    assert await _status_of(engine, event_id) == {"a@x.io": "confirmed"}


async def test_cancel_after_checkin_rejected(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=2)
    await register(client, event_id, "a@x.io")
    token = await token_for(engine, event_id, "a@x.io")
    # No check-in endpoint until phase 4; set the state directly.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE registrations SET status = 'checked_in', checked_in_at = :t "
                "WHERE manage_token = :k"
            ),
            {"t": datetime.now(UTC), "k": token},
        )

    response = await cancel(client, token)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_checked_in"
    await assert_invariants(engine, event_id)


async def test_cancel_on_cancelled_event_rejected(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=2)
    await register(client, event_id, "a@x.io")
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE events SET status = 'cancelled' WHERE id = :e"), {"e": uuid.UUID(event_id)}
        )

    response = await cancel(client, await token_for(engine, event_id, "a@x.io"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "event_cancelled"


async def test_cancel_invalid_token_404(client: AsyncClient) -> None:
    response = await cancel(client, "no-such-token")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "registration_not_found"


async def test_get_registration_shows_ticket_only_when_confirmed(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=1)
    await register(client, event_id, "a@x.io")
    await register(client, event_id, "b@x.io")
    rows = {r["email"]: r for r in await registrations(engine, event_id)}

    a = (
        await client.get(f"/api/registrations/{await token_for(engine, event_id, 'a@x.io')}")
    ).json()
    b = (
        await client.get(f"/api/registrations/{await token_for(engine, event_id, 'b@x.io')}")
    ).json()

    code = rows["a@x.io"]["ticket_code"]
    assert a["status"] == "confirmed" and a["ticket_code"] == f"{code[:4]}-{code[4:]}"
    assert b["status"] == "waitlisted" and b["ticket_code"] is None and b["waitlist_position"] == 1
    assert a["event"]["id"] == event_id
