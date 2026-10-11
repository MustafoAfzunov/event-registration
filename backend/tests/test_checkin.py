"""Check-in (ARCHITECTURE 4.6): one atomic conditional UPDATE; exactly one success per ticket."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from tests.concurrency import row_lock_gate, wait_for_lock_waiters
from tests.helpers import cancel, create_event, register, registrations, token_for
from tests.invariants import assert_invariants


async def checkin(admin: AsyncClient, event_id: str, code: str) -> Response:
    return await admin.post(f"/api/admin/events/{event_id}/checkin", json={"code": code})


async def _ticket(engine: AsyncEngine, event_id: str, email: str) -> dict[str, object]:
    [row] = [r for r in await registrations(engine, event_id) if r["email"] == email]
    return row


def _error(response: Response) -> str:
    code: str = response.json()["error"]["code"]
    return code


async def test_checkin_success(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    await register(client, event_id, "Alice@Example.com")
    code = str((await _ticket(engine, event_id, "Alice@Example.com"))["ticket_code"])

    response = await checkin(admin, event_id, f"{code[:4]}-{code[4:]}")

    assert response.status_code == 200
    body = response.json()
    assert (body["result"], body["email"]) == ("checked_in", "Alice@Example.com")
    assert body["checked_in_at"] == clock.now().isoformat().replace("+00:00", "Z")
    mine = await client.get(
        f"/api/registrations/{await token_for(engine, event_id, 'alice@example.com')}"
    )
    assert mine.json()["status"] == "checked_in"
    await assert_invariants(engine, event_id)


async def test_checkin_twice_sequential_second_is_409_with_original_time(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    await register(client, event_id, "a@example.com")
    code = str((await _ticket(engine, event_id, "a@example.com"))["ticket_code"])

    first = await checkin(admin, event_id, code)
    clock.advance(timedelta(minutes=10))
    second = await checkin(admin, event_id, code)

    assert first.status_code == 200
    assert (second.status_code, _error(second)) == (409, "already_checked_in")
    details = second.json()["error"]["details"]
    assert details["checked_in_at"] == first.json()["checked_in_at"]  # original time, unchanged
    assert details["email"] == "a@example.com"


async def test_concurrent_checkin_same_code_exactly_one_succeeds(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    """10 door scanners submit the same ticket at the same moment, 10 rounds. The gate holds
    the registration row until all 10 UPDATEs are proven blocked on it, then releases."""
    for round_ in range(10):
        event_id = await create_event(admin, clock, capacity=5, title=f"Door {round_}")
        await register(client, event_id, "guest@example.com")
        ticket = await _ticket(engine, event_id, "guest@example.com")

        async with row_lock_gate(engine, "registrations", ticket["id"]):
            tasks = [
                asyncio.create_task(checkin(admin, event_id, str(ticket["ticket_code"])))
                for _ in range(10)
            ]
            await wait_for_lock_waiters(engine, 10)
        responses = await asyncio.gather(*tasks)

        codes = sorted(r.status_code for r in responses)
        assert codes == [200] + [409] * 9, f"round {round_}: {codes}"
        assert {_error(r) for r in responses if r.status_code == 409} == {"already_checked_in"}
        winner_time = next(r.json()["checked_in_at"] for r in responses if r.status_code == 200)
        assert {
            r.json()["error"]["details"]["checked_in_at"] for r in responses if r.status_code == 409
        } == {winner_time}
        stats = (await admin.get(f"/api/admin/events/{event_id}/stats")).json()
        assert (stats["checked_in"], stats["confirmed"]) == (1, 0)
        await assert_invariants(engine, event_id)


async def test_concurrent_checkins_of_different_tickets_all_succeed(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    """Check-in takes no event lock: a crowd at the door doesn't serialize or block."""
    event_id = await create_event(admin, clock, capacity=30)
    for i in range(30):
        await register(client, event_id, f"g{i}@example.com")
    tickets = [str(r["ticket_code"]) for r in await registrations(engine, event_id)]

    responses = await asyncio.gather(*[checkin(admin, event_id, c) for c in tickets])

    assert [r.status_code for r in responses] == [200] * 30
    stats = (await admin.get(f"/api/admin/events/{event_id}/stats")).json()
    assert (stats["checked_in"], stats["confirmed"], stats["seats_left"]) == (30, 0, 0)
    await assert_invariants(engine, event_id)


async def test_checkin_wrong_code_404(admin: AsyncClient, clock: FixedClock) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    response = await checkin(admin, event_id, "ZZZZ-9999")
    assert (response.status_code, _error(response)) == (404, "ticket_not_found")


@pytest.mark.parametrize("bad", ["", "ABC", "ABCD-EFGH-J", "ABCD-EFGU", "!!!!????"])
async def test_checkin_malformed_code_422(admin: AsyncClient, clock: FixedClock, bad: str) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    response = await checkin(admin, event_id, bad)
    assert (response.status_code, _error(response)) == (422, "invalid_code_format")


async def test_checkin_cancelled_ticket_rejected(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    await register(client, event_id, "a@example.com")
    code = str((await _ticket(engine, event_id, "a@example.com"))["ticket_code"])
    await cancel(client, await token_for(engine, event_id, "a@example.com"))

    response = await checkin(admin, event_id, code)

    assert (response.status_code, _error(response)) == (409, "ticket_cancelled")
    assert response.json()["error"]["details"] == {"status": "cancelled", "email": "a@example.com"}


async def test_checkin_waitlisted_ticket_rejected(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=1)
    await register(client, event_id, "a@example.com")
    await register(client, event_id, "b@example.com")  # waitlisted
    code = str((await _ticket(engine, event_id, "b@example.com"))["ticket_code"])

    response = await checkin(admin, event_id, code)

    assert (response.status_code, _error(response)) == (409, "ticket_waitlisted")
    assert response.json()["error"]["details"] == {"status": "waitlisted", "email": "b@example.com"}
    await assert_invariants(engine, event_id)


async def test_promoted_ticket_can_check_in(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=1)
    await register(client, event_id, "a@example.com")
    await register(client, event_id, "b@example.com")
    code = str((await _ticket(engine, event_id, "b@example.com"))["ticket_code"])
    await cancel(client, await token_for(engine, event_id, "a@example.com"))  # b promoted

    assert (await checkin(admin, event_id, code)).status_code == 200


async def test_checkin_other_event_code_404(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_a = await create_event(admin, clock, capacity=5, title="A")
    event_b = await create_event(admin, clock, capacity=5, title="B")
    await register(client, event_a, "a@example.com")
    code = str((await _ticket(engine, event_a, "a@example.com"))["ticket_code"])

    response = await checkin(admin, event_b, code)

    assert (response.status_code, _error(response)) == (404, "ticket_not_found")
    assert (await checkin(admin, event_a, code)).status_code == 200  # still valid where it belongs


async def test_checkin_normalizes_input(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    await register(client, event_id, "a@example.com")
    code = str((await _ticket(engine, event_id, "a@example.com"))["ticket_code"])
    # What a human might type: lowercase, a space, O for 0 and l for 1.
    typed = (code[:4] + " " + code[4:]).lower().replace("0", "o").replace("1", "l")

    response = await checkin(admin, event_id, f"  {typed} ")

    assert response.status_code == 200, (code, typed, response.text)


async def test_cancel_after_checkin_rejected(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=1)
    await register(client, event_id, "a@example.com")
    await register(client, event_id, "b@example.com")
    code = str((await _ticket(engine, event_id, "a@example.com"))["ticket_code"])
    await checkin(admin, event_id, code)

    response = await cancel(client, await token_for(engine, event_id, "a@example.com"))

    assert (response.status_code, _error(response)) == (409, "already_checked_in")
    statuses = {r["email"]: r["status"] for r in await registrations(engine, event_id)}
    assert statuses == {"a@example.com": "checked_in", "b@example.com": "waitlisted"}
    await assert_invariants(engine, event_id)


@pytest.mark.parametrize("first", ["checkin", "cancel"])
async def test_checkin_vs_cancel_race_exactly_one_wins(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock, first: str
) -> None:
    """Participant cancels while staff scans the same ticket. Both requests are blocked on the
    registration row at the same time (gate + pg_locks); `first` queued first, so Postgres
    hands it the row first. Exactly one wins, the loser gets a clear error, and the state
    is consistent (a cancelled seat goes to the waitlist; a checked-in seat stays taken)."""
    for round_ in range(5):
        event_id = await create_event(admin, clock, capacity=1, title=f"Race {first} {round_}")
        await register(client, event_id, "a@example.com")
        await register(client, event_id, "next@example.com")  # waitlisted
        ticket = await _ticket(engine, event_id, "a@example.com")
        token = await token_for(engine, event_id, "a@example.com")
        code = str(ticket["ticket_code"])
        ops = {
            "checkin": lambda e=event_id, c=code: checkin(admin, e, c),
            "cancel": lambda t=token: cancel(client, t),
        }
        second = "cancel" if first == "checkin" else "checkin"

        async with row_lock_gate(engine, "registrations", ticket["id"]):
            task_first = asyncio.create_task(ops[first]())
            await wait_for_lock_waiters(engine, 1)
            task_second = asyncio.create_task(ops[second]())
            await wait_for_lock_waiters(engine, 2)
        results = dict(
            zip([first, second], await asyncio.gather(task_first, task_second), strict=True)
        )

        statuses = {r["email"]: r["status"] for r in await registrations(engine, event_id)}
        if first == "checkin":
            assert results["checkin"].status_code == 200
            assert (results["cancel"].status_code, _error(results["cancel"])) == (
                409,
                "already_checked_in",
            )
            assert statuses == {"a@example.com": "checked_in", "next@example.com": "waitlisted"}
        else:
            assert results["cancel"].status_code == 200
            assert (results["checkin"].status_code, _error(results["checkin"])) == (
                409,
                "ticket_cancelled",
            )
            assert statuses == {"a@example.com": "cancelled", "next@example.com": "confirmed"}
        await assert_invariants(engine, event_id)


async def test_checkin_cancelled_event_rejected(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    await register(client, event_id, "a@example.com")
    code = str((await _ticket(engine, event_id, "a@example.com"))["ticket_code"])
    async with engine.begin() as conn:  # event-cancel endpoint arrives in phase 6
        await conn.execute(
            text("UPDATE events SET status = 'cancelled' WHERE id = :e"), {"e": uuid.UUID(event_id)}
        )

    response = await checkin(admin, event_id, code)
    assert (response.status_code, _error(response)) == (409, "event_cancelled")


async def test_checkin_unknown_event_404(admin: AsyncClient) -> None:
    response = await checkin(admin, str(uuid.uuid4()), "ABCD-EFGH")
    assert (response.status_code, _error(response)) == (404, "event_not_found")


async def test_checkin_requires_organizer(
    client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    response = await checkin(client, event_id, "ABCD-EFGH")
    assert (response.status_code, _error(response)) == (401, "unauthorized")
