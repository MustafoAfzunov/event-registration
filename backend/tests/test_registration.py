import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from tests.helpers import cancel, create_event, outbox, register, registrations, token_for
from tests.invariants import assert_invariants


async def test_register_confirms_when_seat_available(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=2)
    response = await register(client, event_id, "alice@example.com")

    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["status"] == "confirmed"
    assert body["waitlist_position"] is None
    assert body["email"] == "alice@example.com"

    [row] = await registrations(engine, event_id)
    [mail] = await outbox(engine, event_id)
    assert mail["kind"] == "ticket" and mail["to_email"] == "alice@example.com"
    code = row["ticket_code"]
    assert f"{code[:4]}-{code[4:]}" in mail["body_text"]
    token = await token_for(engine, event_id, "alice@example.com")
    assert f"http://app.test/r/{token}" in mail["body_text"]
    await assert_invariants(engine, event_id)


async def test_register_waitlists_when_full(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=1)
    assert (await register(client, event_id, "a@example.com")).json()["status"] == "confirmed"

    second = (await register(client, event_id, "b@example.com")).json()
    third = (await register(client, event_id, "c@example.com")).json()

    assert (second["status"], second["waitlist_position"]) == ("waitlisted", 1)
    assert (third["status"], third["waitlist_position"]) == ("waitlisted", 2)
    kinds = [m["kind"] for m in await outbox(engine, event_id)]
    assert kinds == ["ticket", "waitlisted", "waitlisted"]
    assert "#2 on the waitlist" in (await outbox(engine, event_id))[2]["body_text"]
    await assert_invariants(engine, event_id)


async def test_duplicate_email_returns_existing_no_second_row(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    first = await register(client, event_id, "alice@example.com")
    second = await register(client, event_id, "alice@example.com")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["status"] == "confirmed"
    assert len(await registrations(engine, event_id)) == 1
    assert len(await outbox(engine, event_id)) == 1  # no second email


async def test_duplicate_of_waitlisted_returns_same_position(
    client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=1)
    await register(client, event_id, "a@example.com")
    await register(client, event_id, "b@example.com")
    again = (await register(client, event_id, "B@example.com")).json()
    assert (again["created"], again["status"], again["waitlist_position"]) == (
        False,
        "waitlisted",
        1,
    )


async def test_duplicate_email_case_and_whitespace_variants(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    variants = [
        "Alice@Example.com",
        "  alice@example.COM  ",
        "ALICE@EXAMPLE.COM\t",
        "aLiCe@eXample.Com",
    ]
    responses = [await register(client, event_id, v) for v in variants]

    assert [r.status_code for r in responses] == [201, 200, 200, 200]
    [row] = await registrations(engine, event_id)
    assert row["email_normalized"] == "alice@example.com"
    assert row["email"] == "Alice@Example.com"  # display form as first entered (trimmed)


async def test_reregister_after_cancel_creates_new_row_back_of_queue(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=1)
    await register(client, event_id, "a@example.com")
    await register(client, event_id, "b@example.com")  # waitlist #1
    await register(client, event_id, "c@example.com")  # waitlist #2

    assert (
        await cancel(client, await token_for(engine, event_id, "b@example.com"))
    ).status_code == 200
    again = await register(client, event_id, "b@example.com")

    assert again.status_code == 201  # a NEW registration, not the cancelled one
    assert (again.json()["status"], again.json()["waitlist_position"]) == ("waitlisted", 2)
    b_rows = [
        r for r in await registrations(engine, event_id) if r["email_normalized"] == "b@example.com"
    ]
    assert sorted(r["status"] for r in b_rows) == ["cancelled", "waitlisted"]
    assert b_rows[0]["ticket_code"] != b_rows[1]["ticket_code"]
    await assert_invariants(engine, event_id)


async def test_register_past_event_rejected(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=1))
    clock.advance(timedelta(hours=1))  # exactly at starts_at: closed

    response = await register(client, event_id, "late@example.com")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "registration_closed"
    assert await registrations(engine, event_id) == []


async def test_register_cancelled_event_rejected(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    # No cancel-event endpoint until phase 6; set the state directly.
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE events SET status = 'cancelled' WHERE id = :e"), {"e": uuid.UUID(event_id)}
        )

    response = await register(client, event_id, "a@example.com")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "event_cancelled"


async def test_register_unknown_event_404(client: AsyncClient) -> None:
    response = await register(client, str(uuid.uuid4()), "a@example.com")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "event_not_found"


@pytest.mark.parametrize(
    "email",
    [
        "",
        "   ",
        "not-an-email",
        "a@b",
        "two@@example.com",
        "ünïcode@example.com",
        "a" * 320 + "@x.io",
    ],
)
async def test_invalid_email_rejected(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock, email: str
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    response = await register(client, event_id, email)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_email"
    assert await registrations(engine, event_id) == []


async def test_response_never_contains_ticket_or_token(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=1)
    responses = [
        await register(client, event_id, "a@example.com"),
        await register(client, event_id, "a@example.com"),  # duplicate path
        await register(client, event_id, "b@example.com"),  # waitlist path
    ]
    for row in await registrations(engine, event_id):
        token = await token_for(engine, event_id, row["email_normalized"])
        for response in responses:
            assert row["ticket_code"] not in response.text
            assert row["ticket_code"][:4] + "-" not in response.text
            assert token not in response.text
