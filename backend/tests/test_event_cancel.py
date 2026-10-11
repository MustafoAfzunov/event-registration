import asyncio
from collections import Counter
from collections.abc import Callable
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from app.emails.dispatcher import Dispatcher
from app.scheduler import Scheduler
from tests.helpers import create_event, register, registrations, token_for
from tests.mailpit import Mailpit
from tests.test_reminders import reminder_rows


async def test_cancel_event_notifies_and_blocks_actions(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: Callable[..., Scheduler],
    make_dispatcher: Callable[..., Dispatcher],
) -> None:
    event_id = await create_event(
        admin, clock, capacity=1, starts_in=timedelta(hours=20), title="Gig"
    )
    await register(client, event_id, "a@example.com")
    await register(client, event_id, "w@example.com")
    await make_scheduler().tick()  # reminder for a pending
    await make_dispatcher(outbox_batch_size=1).run_once()  # only the first ticket goes out
    await mailpit.clear()

    r = await admin.post(f"/api/admin/events/{event_id}/cancel")

    assert r.status_code == 200
    assert (r.json()["changed"], r.json()["notified"], r.json()["event"]["status"]) == (
        True,
        2,
        "cancelled",
    )
    assert {row["status"] for row in await reminder_rows(engine, event_id)} == {"skipped"}
    await make_dispatcher().run_until_idle()
    await asyncio.sleep(0.5)
    cancelled = [m for m in await mailpit.messages() if m["Subject"] == "Cancelled: Gig"]
    assert Counter(t["Address"] for m in cancelled for t in m["To"]) == Counter(
        ["a@example.com", "w@example.com"]
    )
    assert not [m for m in await mailpit.messages() if m["Subject"].startswith("Reminder:")]

    code = next(
        r["ticket_code"]
        for r in await registrations(engine, event_id)
        if r["email"] == "a@example.com"
    )
    blocked = [
        await register(client, event_id, "new@example.com"),
        await client.post(
            f"/api/registrations/{await token_for(engine, event_id, 'a@example.com')}/cancel"
        ),
        await admin.post(f"/api/admin/events/{event_id}/checkin", json={"code": code}),
        await admin.patch(f"/api/admin/events/{event_id}", json={"capacity": 5}),
    ]
    assert [(x.status_code, x.json()["error"]["code"]) for x in blocked] == [
        (409, "event_cancelled")
    ] * 4
    assert await make_scheduler().tick() == []  # no reminders for a cancelled event
    assert (await client.get(f"/api/events/{event_id}")).json()["status"] == "cancelled"


async def test_cancel_event_idempotent(
    client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    await register(client, event_id, "a@example.com")
    first = await admin.post(f"/api/admin/events/{event_id}/cancel")
    second = await admin.post(f"/api/admin/events/{event_id}/cancel")
    assert (first.json()["notified"], second.json()["notified"]) == (1, 0)
    assert second.json()["changed"] is False


async def test_cancel_event_requires_organizer(
    client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    r = await client.post(f"/api/admin/events/{event_id}/cancel")
    assert (r.status_code, r.json()["error"]["code"]) == (401, "unauthorized")
