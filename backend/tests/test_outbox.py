"""Outbox + dispatcher mechanics: transactional enqueue, leases, fencing, concurrency,
give-up, graceful release."""

import asyncio
import uuid
from collections.abc import Callable
from datetime import timedelta
from email.message import EmailMessage

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from app.emails.dispatcher import Dispatcher
from app.emails.smtp import SmtpSender, message_id
from app.services import registration as registration_service
from tests.concurrency import wait_for_lock_waiters
from tests.helpers import cancel, create_event, outbox, register, registrations, token_for
from tests.mailpit import Mailpit
from tests.senders import DEAD_SMTP

MakeDispatcher = Callable[..., Dispatcher]


async def _event_with_registrations(
    admin: AsyncClient, client: AsyncClient, clock: FixedClock, n: int, capacity: int = 100
) -> str:
    event_id = await create_event(admin, clock, capacity=capacity)
    for i in range(n):
        await register(client, event_id, f"user{i}@example.com")
    return event_id


async def test_ticket_email_enqueued_in_same_tx_as_registration(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If anything fails after the email row is written, the registration AND the email
    roll back together: no seat without email, no email without seat."""
    event_id = await create_event(admin, clock, capacity=5)
    real_enqueue = registration_service.enqueue

    async def enqueue_then_fail(*args: object, **kwargs: object) -> bool:
        await real_enqueue(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("boom after enqueue")

    monkeypatch.setattr(registration_service, "enqueue", enqueue_then_fail)
    with pytest.raises(RuntimeError, match="boom after enqueue"):
        await register(client, event_id, "a@example.com")

    assert await registrations(engine, event_id) == []
    assert await outbox(engine, event_id) == []
    assert (await client.get(f"/api/events/{event_id}")).json()["seats_left"] == 5


def test_backoff_is_exponential_and_capped(make_dispatcher: MakeDispatcher) -> None:
    d = make_dispatcher(outbox_backoff_base_seconds=5, outbox_backoff_max_seconds=60)
    assert [d.backoff(n).total_seconds() for n in range(1, 7)] == [5, 10, 20, 40, 60, 60]


def test_lease_must_exceed_batch_send_time(make_dispatcher: MakeDispatcher) -> None:
    with pytest.raises(ValueError, match="OUTBOX_LEASE_SECONDS"):
        make_dispatcher(outbox_batch_size=10, smtp_timeout_seconds=10, outbox_lease_seconds=100)


async def test_dispatch_marks_failed_after_max_attempts(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await _event_with_registrations(admin, client, clock, 1)
    dispatcher = make_dispatcher(DEAD_SMTP, outbox_max_attempts=3, outbox_backoff_base_seconds=1)

    for _ in range(3):
        assert await dispatcher.run_once() == 1
        clock.advance(timedelta(hours=1))
    assert await dispatcher.run_until_idle() == 0  # failed rows are never retried

    [row] = await outbox(engine, event_id)
    assert (row["status"], row["attempts"]) == ("failed", 3)
    async with engine.connect() as conn:
        last_error = await conn.scalar(text("SELECT last_error FROM email_outbox"))
    assert last_error and "Connect" in last_error
    assert await mailpit.messages() == []


async def test_failed_promotion_email_keeps_seat(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await _event_with_registrations(admin, client, clock, 2, capacity=1)
    await cancel(client, await token_for(engine, event_id, "user0@example.com"))
    dispatcher = make_dispatcher(DEAD_SMTP, outbox_max_attempts=2, outbox_backoff_base_seconds=1)
    for _ in range(3):
        await dispatcher.run_until_idle()
        clock.advance(timedelta(hours=1))

    promoted = [m for m in await outbox(engine, event_id) if m["kind"] == "promoted"]
    assert [m["status"] for m in promoted] == ["failed"]
    status = {r["email"]: r["status"] for r in await registrations(engine, event_id)}
    assert status["user1@example.com"] == "confirmed"  # the seat is NOT taken back
    assert (await client.get(f"/api/events/{event_id}")).json()["seats_left"] == 0


async def test_two_dispatchers_never_send_same_row(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await _event_with_registrations(admin, client, clock, 30)
    a = make_dispatcher(outbox_batch_size=4)
    b = make_dispatcher(outbox_batch_size=4)

    claimed = await asyncio.gather(a.run_until_idle(), b.run_until_idle())

    assert sum(claimed) == 30
    assert all(n > 0 for n in claimed), f"both workers should have done work: {claimed}"
    messages = await mailpit.wait_for(30)
    assert len(messages) == 30
    assert len({m["MessageID"] for m in messages}) == 30
    assert {(m["status"], m["attempts"]) for m in await outbox(engine, event_id)} == {("sent", 1)}


async def test_stale_claim_cannot_overwrite_newer_claim(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    smtp: SmtpSender,
    make_dispatcher: MakeDispatcher,
) -> None:
    """Fencing: worker A's lease expires and B re-claims the row. While B is still sending,
    A wakes up and reports. A's stale token (attempts=1) must not touch the row: otherwise
    A could flip it back to 'pending' and a third worker would send it a second time."""
    event_id = await _event_with_registrations(admin, client, clock, 1)
    a = make_dispatcher()
    [stale] = await a.claim()
    clock.advance(timedelta(seconds=61))
    b = make_dispatcher()
    [fresh] = await b.claim()
    assert (stale.id, stale.attempts, fresh.attempts) == (fresh.id, 1, 2)

    # B holds the claim (status 'sending'); A's late reports are rejected.
    assert await a.mark_failed_attempt(stale, "late failure report") is False
    assert await a.release(stale) is False
    assert await a.mark_sent(stale) is False
    [row] = await outbox(engine, event_id)
    assert (row["status"], row["attempts"]) == ("sending", 2)
    assert await make_dispatcher().run_until_idle() == 0  # nobody else can grab it

    assert await b.deliver(fresh) is True
    [row] = await outbox(engine, event_id)
    assert (row["status"], row["attempts"]) == ("sent", 2)


async def test_concurrent_claims_are_disjoint(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    make_dispatcher: MakeDispatcher,
) -> None:
    """10 dispatchers claim at the same instant (gated: a SHARE table lock blocks every
    claim UPDATE until all 10 are proven waiting in pg_locks). Every row is claimed by
    exactly one of them (FOR UPDATE SKIP LOCKED)."""
    await _event_with_registrations(admin, client, clock, 30)
    dispatchers = [make_dispatcher(outbox_batch_size=3) for _ in range(10)]

    async with engine.connect() as gate:
        tx = await gate.begin()
        await gate.execute(text("LOCK TABLE email_outbox IN SHARE MODE"))
        tasks = [asyncio.create_task(d.claim()) for d in dispatchers]
        await wait_for_lock_waiters(engine, 10)
        await tx.commit()
    batches = await asyncio.gather(*tasks)

    ids = [c.id for batch in batches for c in batch]
    assert len(ids) == 30, f"claimed {len(ids)} rows in total"
    assert len(set(ids)) == 30, "a row was claimed by two dispatchers"
    assert {c.attempts for batch in batches for c in batch} == {1}


async def test_graceful_stop_releases_unsent_rows(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    smtp: SmtpSender,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await _event_with_registrations(admin, client, clock, 5)
    stop = asyncio.Event()

    class StopAfterFirst:
        async def send(self, message: EmailMessage) -> None:
            await smtp.send(message)
            stop.set()  # SIGTERM arrives while the first message is in flight

    assert await make_dispatcher(StopAfterFirst()).run_once(stop) == 5
    rows = await outbox(engine, event_id)
    assert sorted(r["status"] for r in rows) == ["pending"] * 4 + ["sent"]

    # Released rows are immediately claimable: no waiting for a lease to expire.
    assert await make_dispatcher().run_until_idle() == 4
    messages = await mailpit.wait_for(5)
    assert len(messages) == len({m["MessageID"] for m in messages}) == 5


async def test_message_headers(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await _event_with_registrations(admin, client, clock, 1)
    await make_dispatcher().run_until_idle()
    [message] = await mailpit.wait_for(1)
    [row] = await outbox(engine, event_id)
    assert message["MessageID"] == message_id(row["dedupe_key"]).strip("<>")
    assert message["From"]["Address"] == "no-reply@eventreg.example.com"
    assert message_id("ticket:x") == message_id("ticket:x") != message_id("ticket:y")
    assert uuid.UUID(str(row["registration_id"]))


async def test_enqueue_reports_whether_a_row_was_written(
    app: object, admin: AsyncClient, clock: FixedClock
) -> None:
    from app.emails.outbox import enqueue
    from app.emails.templates import Rendered
    from app.models import EmailKind

    event_id = uuid.UUID(await create_event(admin, clock, capacity=5))
    sm = app.state.sessionmaker  # type: ignore[attr-defined]
    results = []
    for _ in range(2):
        async with sm() as session, session.begin():
            results.append(
                await enqueue(
                    session,
                    kind=EmailKind.ticket,
                    key="ticket:same",
                    event_id=event_id,
                    registration_id=None,
                    to_email="a@example.com",
                    email=Rendered("s", "b"),
                    now=clock.now(),
                )
            )
    assert results == [True, False]
