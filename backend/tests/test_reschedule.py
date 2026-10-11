"""Reschedule (ARCHITECTURE 4.8): everyone with a stake is emailed; reminder state is reset
so the reminder follows the new date (one per person per schedule version)."""

import asyncio
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from app.emails.dispatcher import Dispatcher
from app.scheduler import Scheduler
from tests.helpers import cancel, create_event, outbox, register, registrations, token_for
from tests.mailpit import Mailpit
from tests.test_reminders import cycle, reminder_recipients, reminder_rows

MakeScheduler = Callable[..., Scheduler]
MakeDispatcher = Callable[..., Dispatcher]


def when(dt: datetime) -> str:  # the format used in email bodies
    return dt.astimezone(UTC).strftime("%a, %d %b %Y %H:%M UTC")


async def reschedule(admin: AsyncClient, event_id: str, starts_at: datetime) -> Response:
    return await admin.post(
        f"/api/admin/events/{event_id}/reschedule", json={"starts_at": starts_at.isoformat()}
    )


async def version(engine: AsyncEngine, event_id: str) -> int:
    async with engine.connect() as conn:
        v = await conn.scalar(
            text("SELECT schedule_version FROM events WHERE id = :e"), {"e": uuid.UUID(event_id)}
        )
    return int(v)


async def test_reschedule_emails_every_participant(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_dispatcher: MakeDispatcher,
) -> None:
    old = clock.now() + timedelta(days=5)
    event_id = await create_event(
        admin, clock, capacity=3, starts_in=timedelta(days=5), title="Gala"
    )
    for email in [
        "a@example.com",
        "b@example.com",
        "arrived@example.com",
        "wait@example.com",
        "gone@example.com",
    ]:
        await register(client, event_id, email)
    await cancel(client, await token_for(engine, event_id, "gone@example.com"))  # waitlisted, left
    arrived = next(
        r for r in await registrations(engine, event_id) if r["email"] == "arrived@example.com"
    )
    await admin.post(f"/api/admin/events/{event_id}/checkin", json={"code": arrived["ticket_code"]})
    await make_dispatcher().run_until_idle()
    await mailpit.clear()

    new = (clock.now() + timedelta(days=9)).replace(microsecond=0)
    r = await reschedule(admin, event_id, new)

    assert r.status_code == 200
    assert (r.json()["changed"], r.json()["notified"]) == (True, 4)
    assert r.json()["event"]["starts_at"] == new.isoformat().replace("+00:00", "Z")
    await make_dispatcher().run_until_idle()
    await asyncio.sleep(0.5)
    moved = [
        m for m in await mailpit.messages() if m["Subject"] == f"New date for Gala: {when(new)}"
    ]
    assert Counter(t["Address"] for m in moved for t in m["To"]) == Counter(
        ["a@example.com", "b@example.com", "arrived@example.com", "wait@example.com"]
    )
    [to_a] = [m for m in moved if m["To"][0]["Address"] == "a@example.com"]
    [to_wait] = [m for m in moved if m["To"][0]["Address"] == "wait@example.com"]
    body_a, body_wait = await mailpit.text(to_a), await mailpit.text(to_wait)
    assert f"Old date: {when(old)}" in body_a and f"New date: {when(new)}" in body_a
    assert "ticket stay valid" in body_a
    assert "still on the waitlist" in body_wait
    assert len(await mailpit.messages()) == 4  # nobody else, nothing twice


async def test_reschedule_resets_reminders_and_reminder_follows_new_date(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=23))
    for email in ["a@example.com", "b@example.com"]:
        await register(client, event_id, email)
    await cycle(make_scheduler, make_dispatcher)  # v1 reminders sent
    assert await reminder_recipients(mailpit) == Counter(["a@example.com", "b@example.com"])

    new = (clock.now() + timedelta(days=3)).replace(microsecond=0)
    assert (await reschedule(admin, event_id, new)).json()["changed"] is True
    assert await version(engine, event_id) == 2
    await cycle(make_scheduler, make_dispatcher)  # new date is >24h away: nothing yet
    assert await reminder_recipients(mailpit) == Counter(["a@example.com", "b@example.com"])

    clock.set(new - timedelta(hours=23))  # inside the new window
    for _ in range(3):
        await cycle(make_scheduler, make_dispatcher)
    assert await reminder_recipients(mailpit) == Counter(["a@example.com", "b@example.com"] * 2)
    newest = [m for m in await mailpit.to("a@example.com") if m["Subject"].startswith("Reminder:")]
    assert {m["Subject"] for m in newest} >= {f"Reminder: Test event starts {when(new)}"}
    rows = await reminder_rows(engine, event_id)
    assert sorted(str(r["dedupe_key"]).split(":")[2] for r in rows) == ["v1", "v1", "v2", "v2"]


async def test_reschedule_voids_pending_reminders(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=23))
    await register(client, event_id, "a@example.com")
    await make_scheduler().tick()  # v1 reminder enqueued, not sent yet

    await reschedule(admin, event_id, clock.now() + timedelta(days=4))
    [row] = await reminder_rows(engine, event_id)
    assert row["status"] == "skipped"
    await make_dispatcher().run_until_idle()
    assert await reminder_recipients(mailpit) == Counter()


async def test_reminder_claimed_before_reschedule_is_not_sent_with_old_date(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    """Race: a dispatcher has already claimed the v1 reminder ('sending', so the reschedule
    does not touch it) when the reschedule commits. The send-time check catches it."""
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=23))
    await register(client, event_id, "a@example.com")
    await make_dispatcher().run_until_idle()
    await make_scheduler().tick()
    dispatcher = make_dispatcher()
    [claimed] = await dispatcher.claim()

    await reschedule(admin, event_id, clock.now() + timedelta(days=4))
    await dispatcher.deliver(claimed)

    [row] = await reminder_rows(engine, event_id)
    assert row["status"] == "skipped"
    assert await reminder_recipients(mailpit) == Counter()


async def test_reschedule_into_near_future_sends_new_reminder_next_tick(
    client: AsyncClient,
    admin: AsyncClient,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(days=5))
    await register(client, event_id, "a@example.com")
    await cycle(make_scheduler, make_dispatcher)
    assert await reminder_recipients(mailpit) == Counter()

    soon = (clock.now() + timedelta(hours=2)).replace(microsecond=0)
    await reschedule(admin, event_id, soon)
    await cycle(make_scheduler, make_dispatcher)
    await cycle(make_scheduler, make_dispatcher)

    assert await reminder_recipients(mailpit) == Counter(["a@example.com"])
    [mail] = [m for m in await mailpit.to("a@example.com") if m["Subject"].startswith("Reminder:")]
    assert when(soon) in mail["Subject"]


async def test_reschedule_into_past_rejected(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    await register(client, event_id, "a@example.com")
    before = (await client.get(f"/api/events/{event_id}")).json()
    emails_before = len(await outbox(engine, event_id))

    for bad in (clock.now() - timedelta(hours=1), clock.now()):
        r = await reschedule(admin, event_id, bad)
        assert (r.status_code, r.json()["error"]["code"]) == (422, "starts_in_past")

    assert (await client.get(f"/api/events/{event_id}")).json() == before
    assert await version(engine, event_id) == 1
    assert len(await outbox(engine, event_id)) == emails_before


async def test_reschedule_same_time_is_noop(
    client: AsyncClient, admin: AsyncClient, engine: AsyncEngine, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    await register(client, event_id, "a@example.com")
    starts_at = datetime.fromisoformat(
        (await client.get(f"/api/events/{event_id}")).json()["starts_at"]
    )
    emails_before = len(await outbox(engine, event_id))

    r = await reschedule(admin, event_id, starts_at)

    assert (r.status_code, r.json()["changed"], r.json()["notified"]) == (200, False, 0)
    assert await version(engine, event_id) == 1
    assert len(await outbox(engine, event_id)) == emails_before


async def test_reschedule_after_start_reopens_registration(
    client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=1))
    clock.advance(timedelta(hours=2))
    assert (await register(client, event_id, "late@example.com")).status_code == 409
    assert (await reschedule(admin, event_id, clock.now() + timedelta(days=1))).status_code == 200
    assert (await register(client, event_id, "late@example.com")).status_code == 201


async def test_reschedule_errors(
    client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    future = clock.now() + timedelta(days=2)
    r = await client.post(
        f"/api/admin/events/{event_id}/reschedule", json={"starts_at": future.isoformat()}
    )
    assert (r.status_code, r.json()["error"]["code"]) == (401, "unauthorized")
    r = await reschedule(admin, str(uuid.uuid4()), future)
    assert (r.status_code, r.json()["error"]["code"]) == (404, "event_not_found")
    r = await admin.post(
        f"/api/admin/events/{event_id}/reschedule", json={"starts_at": "2099-01-01T10:00:00"}
    )
    assert (r.status_code, r.json()["error"]["code"]) == (422, "validation_error")  # naive time
    await admin.post(f"/api/admin/events/{event_id}/cancel")
    r = await reschedule(admin, event_id, future)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "event_cancelled")
