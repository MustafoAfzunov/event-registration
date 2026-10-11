"""Phase 3 requirements, verified in the mailbox (Mailpit HTTP API), not just in our DB:
  * one email per registration (ticket / waitlist notice)
  * repeat registration sends no second email
  * promotion sends exactly one email, with the ticket
  * worker restart mid-batch doesn't duplicate
  * SMTP failure retries and then sends exactly once
plus the honest at-least-once window (DECISIONS D-007, D-043)."""

from collections import Counter
from collections.abc import Callable
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from app.emails.dispatcher import Dispatcher
from app.emails.smtp import SmtpSender, message_id
from tests.helpers import cancel, create_event, outbox, register, registrations, token_for
from tests.mailpit import Mailpit
from tests.senders import CrashAfterSmtpAccept, CrashBeforeSend, FailFirst, SimulatedCrash

MakeDispatcher = Callable[..., Dispatcher]


def _fmt(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


async def test_one_email_per_registration(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=1, title="PyCon")
    await register(client, event_id, "alice@example.com")  # confirmed -> ticket
    await register(client, event_id, "bob@example.com")  # full -> waitlist notice

    await make_dispatcher().run_until_idle()
    assert len(await mailpit.wait_for(2)) == 2

    codes = {r["email"]: r["ticket_code"] for r in await registrations(engine, event_id)}
    [ticket] = await mailpit.to("alice@example.com")
    [notice] = await mailpit.to("bob@example.com")
    assert ticket["Subject"] == "Your ticket for PyCon"
    ticket_text = await mailpit.text(ticket)
    assert f"Your ticket code: {_fmt(codes['alice@example.com'])}" in ticket_text
    token = await token_for(engine, event_id, "alice@example.com")
    assert f"http://app.test/r/{token}" in ticket_text

    assert notice["Subject"] == "You're on the waitlist for PyCon"
    notice_text = await mailpit.text(notice)
    assert "#1 on the waitlist" in notice_text
    assert _fmt(codes["bob@example.com"]) not in notice_text  # no ticket while waitlisted
    assert {m["status"] for m in await outbox(engine, event_id)} == {"sent"}


async def test_repeat_registration_sends_no_second_email(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    for variant in [
        "carol@example.com",
        "Carol@Example.com",
        " CAROL@example.com ",
        "carol@example.com",
    ]:
        await register(client, event_id, variant)

    dispatcher = make_dispatcher()
    await dispatcher.run_until_idle()
    await mailpit.wait_for(1)
    await register(client, event_id, "carol@example.com")  # again, after the email went out
    await dispatcher.run_until_idle()
    await make_dispatcher().run_until_idle()  # and a second "worker"

    assert len(await mailpit.to("carol@example.com")) == 1
    assert len(await mailpit.messages()) == 1


async def test_promotion_sends_exactly_one_email_with_ticket(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=1, title="Meetup")
    await register(client, event_id, "first@example.com")
    await register(client, event_id, "second@example.com")
    await register(client, event_id, "third@example.com")
    await make_dispatcher().run_until_idle()
    await mailpit.wait_for(3)
    await mailpit.clear()

    await cancel(client, await token_for(engine, event_id, "first@example.com"))
    await make_dispatcher().run_until_idle()
    await make_dispatcher().run_until_idle()  # a second pass must not resend anything
    messages = await mailpit.wait_for(2)  # promotion to #1 in line + cancel confirmation

    [promotion] = await mailpit.to("second@example.com")
    assert promotion["Subject"] == "A seat opened up: your ticket for Meetup"
    code = {r["email"]: r["ticket_code"] for r in await registrations(engine, event_id)}[
        "second@example.com"
    ]
    assert f"Your ticket code: {_fmt(code)}" in await mailpit.text(promotion)
    assert await mailpit.to("third@example.com") == []  # still waiting, nothing new
    assert [m["Subject"] for m in await mailpit.to("first@example.com")] == [
        "Registration cancelled: Meetup"
    ]
    assert len(messages) == 2


async def test_worker_restart_mid_batch_does_not_duplicate(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    smtp: SmtpSender,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=10)
    emails = [f"guest{i}@example.com" for i in range(6)]
    for email in emails:
        await register(client, event_id, email)

    # Worker 1 claims all 6 (one batch), delivers 3, then dies before the 4th.
    crashing = make_dispatcher(CrashBeforeSend(smtp, succeed=3), outbox_lease_seconds=60)
    with pytest.raises(SimulatedCrash):
        await crashing.run_once()
    assert len(await mailpit.wait_for(3)) == 3
    assert Counter(m["status"] for m in await outbox(engine, event_id)) == {"sent": 3, "sending": 3}

    # Worker 2 restarts immediately: the dead worker's lease is still valid -> nothing sent.
    assert await make_dispatcher().run_until_idle() == 0
    assert len(await mailpit.messages()) == 3

    # After the lease expires, the 3 unsent rows are reclaimed and sent once.
    clock.advance(timedelta(seconds=61))
    assert await make_dispatcher().run_until_idle() == 3

    messages = await mailpit.wait_for(6)
    assert len(messages) == 6
    assert len({m["MessageID"] for m in messages}) == 6
    assert Counter(t["Address"] for m in messages for t in m["To"]) == Counter(emails)
    assert {m["status"] for m in await outbox(engine, event_id)} == {"sent"}


async def test_smtp_failure_retries_then_sends_once(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    smtp: SmtpSender,
    make_dispatcher: MakeDispatcher,
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    await register(client, event_id, "dave@example.com")
    dispatcher = make_dispatcher(FailFirst(smtp, failures=2), outbox_backoff_base_seconds=5)

    # Attempt 1: real connection failure -> back to pending, retry in 5s.
    assert await dispatcher.run_once() == 1
    [row] = await outbox(engine, event_id)
    assert (row["status"], row["attempts"]) == ("pending", 1)
    assert await dispatcher.run_until_idle() == 0  # not due yet: no busy retry loop

    clock.advance(timedelta(seconds=5))  # attempt 2 fails -> retry in 10s (exponential)
    assert await dispatcher.run_once() == 1
    clock.advance(timedelta(seconds=9))
    assert await dispatcher.run_until_idle() == 0
    clock.advance(timedelta(seconds=1))
    assert await dispatcher.run_once() == 1  # attempt 3 succeeds

    [message] = await mailpit.wait_for(1)
    assert [t["Address"] for t in message["To"]] == ["dave@example.com"]
    [row] = await outbox(engine, event_id)
    assert (row["status"], row["attempts"]) == ("sent", 3)
    clock.advance(timedelta(hours=2))
    assert await dispatcher.run_until_idle() == 0
    assert len(await mailpit.messages()) == 1


async def test_known_window_crash_after_smtp_accept_resends_same_message_id(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    smtp: SmtpSender,
    make_dispatcher: MakeDispatcher,
) -> None:
    """Documents the ONE case where a duplicate happens (at-least-once, D-007/D-043): the SMTP
    server accepted the message and the worker died before recording it. After the lease
    expires the message is sent again: we prefer a duplicate to a lost ticket. The copy has
    the same Message-ID, so it is identifiable as the same message."""
    event_id = await create_event(admin, clock, capacity=5)
    await register(client, event_id, "erin@example.com")
    [row] = await outbox(engine, event_id)

    with pytest.raises(SimulatedCrash):
        await make_dispatcher(CrashAfterSmtpAccept(smtp)).run_once()
    clock.advance(timedelta(seconds=61))
    await make_dispatcher().run_until_idle()

    messages = await mailpit.wait_for(2)
    assert len(messages) == 2
    expected = message_id(row["dedupe_key"]).strip("<>")
    assert {m["MessageID"] for m in messages} == {expected}
