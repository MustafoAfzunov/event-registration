"""Reminder scheduler (ARCHITECTURE 4.7): exactly one reminder per confirmed participant,
24h before the event, restart-safe, with several scheduler instances. Time is controlled by
the FixedClock shared by the app, the scheduler and the dispatcher."""

import asyncio
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import scheduler as scheduler_module
from app.clock import FixedClock
from app.emails.dispatcher import Dispatcher
from app.emails.smtp import SmtpSender
from app.scheduler import Scheduler
from tests.concurrency import wait_for_lock_waiters
from tests.helpers import cancel, create_event, outbox, register, registrations, token_for
from tests.mailpit import Mailpit
from tests.senders import CrashBeforeSend, SimulatedCrash

MakeScheduler = Callable[..., Scheduler]
MakeDispatcher = Callable[..., Dispatcher]
DAY = timedelta(hours=24)


async def reminder_recipients(mailpit: Mailpit, settle: bool = True) -> Counter[str]:
    if settle:
        await asyncio.sleep(0.5)
    return Counter(
        t["Address"]
        for m in await mailpit.messages()
        if m["Subject"].startswith("Reminder:")
        for t in m["To"]
    )


async def reminder_rows(engine: AsyncEngine, event_id: str) -> list[dict[str, object]]:
    return [m for m in await outbox(engine, event_id) if m["kind"] == "reminder"]


async def cycle(make_scheduler: MakeScheduler, make_dispatcher: MakeDispatcher) -> None:
    """One scheduler tick, then deliver everything that is due."""
    await make_scheduler().tick()
    await make_dispatcher().run_until_idle()


async def test_reminder_sent_once_with_three_scheduler_instances(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=10, starts_in=timedelta(hours=23))
    people = [f"p{i}@example.com" for i in range(5)]
    for email in people:
        await register(client, event_id, email)

    schedulers = [make_scheduler() for _ in range(3)]
    dispatchers = [make_dispatcher() for _ in range(3)]
    for _ in range(5):  # many overlapping ticks of 3 instances, and 3 concurrent senders
        await asyncio.gather(*[s.tick() for s in schedulers])
        await asyncio.gather(*[d.run_until_idle() for d in dispatchers])
        clock.advance(timedelta(minutes=1))

    assert await reminder_recipients(mailpit) == Counter(people)
    rows = await reminder_rows(engine, event_id)
    assert len(rows) == 5 and {r["status"] for r in rows} == {"sent"}


async def test_three_schedulers_split_due_events_with_skip_locked(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    make_scheduler: MakeScheduler,
) -> None:
    """Gated: each instance locks a due event and blocks on the outbox insert until all 3
    are proven waiting; then they run. Every event's reminders are enqueued by exactly one
    instance. (An instance may still *visit* an event another one just finished: its insert
    then conflicts and enqueues nothing. See Scheduler.enqueue_next_event.)"""
    events = []
    for i in range(30):
        event_id = await create_event(
            admin, clock, capacity=5, starts_in=timedelta(hours=10, minutes=i)
        )
        await register(client, event_id, f"e{i}@example.com")
        events.append(event_id)

    schedulers = [make_scheduler() for _ in range(3)]
    async with engine.connect() as gate:
        tx = await gate.begin()
        await gate.execute(text("LOCK TABLE email_outbox IN SHARE MODE"))
        tasks = [asyncio.create_task(s.tick()) for s in schedulers]
        await wait_for_lock_waiters(engine, 3)
        await tx.commit()
    handled = await asyncio.gather(*tasks)

    flat = [str(e) for h in handled for e in h]
    assert len(flat) == len(set(flat)) == 30, "an event's reminders were enqueued by two instances"
    assert set(flat) == set(events)
    assert all(h for h in handled), (
        f"every instance should have taken work: {[len(h) for h in handled]}"
    )
    async with engine.connect() as conn:
        assert (
            await conn.scalar(text("SELECT count(*) FROM email_outbox WHERE kind = 'reminder'"))
            == 30
        )


async def test_window_opens_exactly_24h_before(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    make_scheduler: MakeScheduler,
) -> None:
    event_id = await create_event(admin, clock, capacity=5, starts_in=DAY + timedelta(seconds=1))
    await register(client, event_id, "a@example.com")

    assert await make_scheduler().tick() == []  # 24h + 1s ahead: not yet
    clock.advance(timedelta(seconds=1))  # exactly 24h ahead: due
    assert [str(e) for e in await make_scheduler().tick()] == [event_id]
    assert len(await reminder_rows(engine, event_id)) == 1
    assert await make_scheduler().tick() == []  # nothing left to do


async def test_not_sent_to_cancelled_or_waitlisted(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=2, starts_in=timedelta(hours=20))
    for email in ["a@example.com", "b@example.com", "wait@example.com", "gone@example.com"]:
        await register(client, event_id, email)
    await cancel(client, await token_for(engine, event_id, "gone@example.com"))  # was waitlisted

    await cycle(make_scheduler, make_dispatcher)
    await cycle(make_scheduler, make_dispatcher)

    assert await reminder_recipients(mailpit) == Counter(["a@example.com", "b@example.com"])


async def test_cancelled_after_enqueue_is_skipped_and_promoted_gets_one(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=1, starts_in=timedelta(hours=20))
    await register(client, event_id, "holder@example.com")
    await register(client, event_id, "next@example.com")
    await make_scheduler().tick()  # reminder for holder enqueued, not yet sent

    await cancel(client, await token_for(engine, event_id, "holder@example.com"))  # next promoted
    await make_dispatcher().run_until_idle()
    [row] = await reminder_rows(engine, event_id)
    assert row["status"] == "skipped"  # holder is no longer confirmed at send time

    await cycle(make_scheduler, make_dispatcher)  # promoted inside the window
    await cycle(make_scheduler, make_dispatcher)
    assert await reminder_recipients(mailpit) == Counter(["next@example.com"])


async def test_promoted_participant_gets_exactly_one(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=1, starts_in=timedelta(hours=20))
    await register(client, event_id, "first@example.com")
    await register(client, event_id, "second@example.com")
    await cycle(make_scheduler, make_dispatcher)  # first gets theirs

    clock.advance(timedelta(hours=1))
    await cancel(client, await token_for(engine, event_id, "first@example.com"))
    for _ in range(3):
        await cycle(make_scheduler, make_dispatcher)
        clock.advance(timedelta(minutes=5))

    assert await reminder_recipients(mailpit) == Counter(
        ["first@example.com", "second@example.com"]
    )
    second = next(
        m for m in await mailpit.to("second@example.com") if m["Subject"].startswith("Reminder:")
    )
    code = next(
        r["ticket_code"]
        for r in await registrations(engine, event_id)
        if r["email"] == "second@example.com"
    )
    assert f"{str(code)[:4]}-{str(code)[4:]}" in await mailpit.text(second)


async def test_dispatcher_restart_between_claim_and_send_neither_loses_nor_duplicates(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    smtp: SmtpSender,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=20))
    people = [f"r{i}@example.com" for i in range(3)]
    for email in people:
        await register(client, event_id, email)
    await make_dispatcher().run_until_idle()  # tickets out of the way
    await mailpit.clear()
    await make_scheduler().tick()

    # Worker claims the 3 reminders, sends one, dies before the second.
    with pytest.raises(SimulatedCrash):
        await make_dispatcher(CrashBeforeSend(smtp, succeed=1)).run_once()
    assert await make_dispatcher().run_until_idle() == 0  # restarted too early: lease held
    await make_scheduler().tick()  # the scheduler must not re-enqueue claimed reminders
    clock.advance(timedelta(seconds=61))
    await make_dispatcher().run_until_idle()

    assert await reminder_recipients(mailpit) == Counter(people)
    assert len(await reminder_rows(engine, event_id)) == 3


async def test_scheduler_crash_before_commit_loses_nothing(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    monkeypatch: pytest.MonkeyPatch,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    """The scheduler dies after locking the event and inserting reminders but before
    COMMIT: everything rolls back (no half state), and the next tick does it again."""
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=20))
    await register(client, event_id, "a@example.com")

    async def crash(*_: object, **__: object) -> None:
        raise SimulatedCrash

    monkeypatch.setattr(scheduler_module, "notify_event_changed", crash)
    with pytest.raises(SimulatedCrash):
        await make_scheduler().tick()
    assert await reminder_rows(engine, event_id) == []
    monkeypatch.undo()

    await cycle(make_scheduler, make_dispatcher)
    await cycle(make_scheduler, make_dispatcher)
    assert await reminder_recipients(mailpit) == Counter(["a@example.com"])


async def test_late_reminder_after_downtime_if_event_not_started(
    client: AsyncClient,
    admin: AsyncClient,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=30))
    await register(client, event_id, "a@example.com")
    clock.advance(timedelta(hours=28))  # worker was down while the 24h mark passed

    await cycle(make_scheduler, make_dispatcher)
    assert await reminder_recipients(mailpit) == Counter(["a@example.com"])


async def test_no_reminder_after_event_started(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    started = await create_event(
        admin, clock, capacity=5, starts_in=timedelta(hours=30), title="Down"
    )
    await register(client, started, "a@example.com")
    queued = await create_event(
        admin, clock, capacity=5, starts_in=timedelta(hours=2), title="Queued"
    )
    await register(client, queued, "b@example.com")
    await make_scheduler().tick()  # 'Queued' reminder enqueued but not sent (worker dies)

    clock.advance(timedelta(hours=31))  # back up only after both events started
    await cycle(make_scheduler, make_dispatcher)

    assert await reminder_recipients(mailpit) == Counter()
    assert await reminder_rows(engine, started) == []
    [row] = await reminder_rows(engine, queued)
    assert row["status"] == "skipped"


async def test_event_created_less_than_24h_ahead(
    client: AsyncClient,
    admin: AsyncClient,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    """Policy (A6/E17): already inside the window -> reminder at the next tick; people who
    register later inside the window get theirs at the following tick."""
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=5))
    await register(client, event_id, "early@example.com")
    await cycle(make_scheduler, make_dispatcher)
    assert await reminder_recipients(mailpit) == Counter(["early@example.com"])

    clock.advance(timedelta(hours=1))
    await register(client, event_id, "late@example.com")
    await cycle(make_scheduler, make_dispatcher)
    assert await reminder_recipients(mailpit) == Counter(["early@example.com", "late@example.com"])


async def test_cancel_and_reregister_gets_one_reminder(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=20))
    await register(client, event_id, "a@example.com")
    await cycle(make_scheduler, make_dispatcher)  # reminder sent
    await cancel(client, await token_for(engine, event_id, "a@example.com"))
    await register(client, event_id, "A@example.com")  # same person, new registration
    await cycle(make_scheduler, make_dispatcher)
    assert await reminder_recipients(mailpit) == Counter(["a@example.com"])


async def test_skipped_reminder_is_rearmed_when_person_confirmed_again(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=20))
    await register(client, event_id, "b@example.com")
    await make_scheduler().tick()  # enqueued...
    await cancel(client, await token_for(engine, event_id, "b@example.com"))
    await make_dispatcher().run_until_idle()  # ...skipped: not confirmed at send time
    await register(client, event_id, "b@example.com")  # back again, new ticket code

    await cycle(make_scheduler, make_dispatcher)

    assert await reminder_recipients(mailpit) == Counter(["b@example.com"])
    [row] = await reminder_rows(engine, event_id)
    assert row["status"] == "sent"
    current = next(r for r in await registrations(engine, event_id) if r["status"] == "confirmed")
    [mail] = [m for m in await mailpit.to("b@example.com") if m["Subject"].startswith("Reminder:")]
    code = str(current["ticket_code"])
    assert f"{code[:4]}-{code[4:]}" in await mailpit.text(mail)  # the NEW ticket


async def test_checked_in_before_reminder_is_skipped(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_scheduler: MakeScheduler,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=5, starts_in=timedelta(hours=1))
    await register(client, event_id, "early-bird@example.com")
    await make_scheduler().tick()
    [reg] = await registrations(engine, event_id)
    r = await admin.post(f"/api/admin/events/{event_id}/checkin", json={"code": reg["ticket_code"]})
    assert r.status_code == 200
    await make_dispatcher().run_until_idle()
    assert await reminder_recipients(mailpit) == Counter()


async def test_tick_without_due_events_is_a_noop(
    make_scheduler: MakeScheduler, engine: AsyncEngine
) -> None:
    assert await make_scheduler().tick() == []
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM email_outbox")) == 0


def test_reminder_key_is_per_person_per_schedule_version() -> None:
    e = uuid.UUID(int=1)
    assert scheduler_module.reminder_key(e, 1, "a@x.io") != scheduler_module.reminder_key(
        e, 2, "a@x.io"
    )
    assert scheduler_module.reminder_key(e, 1, "a@x.io") == f"reminder:{e}:v1:a@x.io"
