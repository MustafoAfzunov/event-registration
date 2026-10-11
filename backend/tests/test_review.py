"""Regression tests for findings in docs/REVIEW.md (phase 9). Each test reproduces a finding
and was written (and seen failing) BEFORE the fix."""

import uuid
from collections import Counter
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from app.emails.dispatcher import Dispatcher
from tests.conftest import ORGANIZER_PASSWORD
from tests.helpers import create_event, outbox, register, token_for
from tests.live_server import run_server, server_env
from tests.mailpit import Mailpit

MakeDispatcher = Callable[..., Dispatcher]


# --------------------------------------------------------------------------------------- H1
async def test_review_h1_unsendable_email_fails_alone_and_others_are_delivered(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_dispatcher: MakeDispatcher,
) -> None:
    """A row that can never be turned into an email (here: CR/LF in the Subject, which the
    email library rightly refuses) must fail on its own: it may not abort its batch, and the
    other people in that batch must still get their emails exactly once."""
    event_id = await create_event(admin, clock, capacity=10)
    async with engine.begin() as conn:  # lowest id -> first in the batch
        await conn.execute(
            text(
                "INSERT INTO email_outbox (kind, dedupe_key, event_id, to_email, subject, "
                "body_text, next_attempt_at) VALUES ('ticket', 'poison', :e, "
                "'poison@example.com', :s, 'body', :n)"
            ),
            {
                "e": uuid.UUID(event_id),
                "s": "Your ticket for Line one\nBcc: x@example.com",
                "n": clock.now(),
            },
        )
    people = [f"innocent{i}@example.com" for i in range(3)]
    for email in people:
        await register(client, event_id, email)

    dispatcher = make_dispatcher(outbox_batch_size=10)
    for _ in range(3):  # several lease cycles: nothing may stay stuck
        await dispatcher.run_until_idle()
        clock.advance(timedelta(seconds=61))

    delivered = Counter(t["Address"] for m in await mailpit.wait_for(3) for t in m["To"])
    assert delivered == Counter(people)
    rows = {r["dedupe_key"]: r for r in await outbox(engine, event_id)}
    assert (rows["poison"]["status"], rows["poison"]["attempts"]) == ("failed", 1)
    assert {r["status"] for k, r in rows.items() if k != "poison"} == {"sent"}
    async with engine.connect() as conn:
        reason = await conn.scalar(
            text("SELECT last_error FROM email_outbox WHERE dedupe_key = 'poison'")
        )
    assert reason and "unsendable" in reason


@pytest.mark.parametrize(
    "bad", ["Line one\nBcc: x@example.com", "Tab\tin title", "Bell\x07", "CR\rhere"]
)
async def test_review_h1_title_with_control_characters_rejected(
    admin: AsyncClient, clock: FixedClock, bad: str
) -> None:
    starts = (clock.now() + timedelta(days=3)).isoformat()
    r = await admin.post(
        "/api/admin/events", json={"title": bad, "starts_at": starts, "capacity": 5}
    )
    assert (r.status_code, r.json()["error"]["code"]) == (422, "validation_error")

    event_id = await create_event(admin, clock, capacity=5)
    r = await admin.patch(f"/api/admin/events/{event_id}", json={"title": bad})
    assert (r.status_code, r.json()["error"]["code"]) == (422, "validation_error")


async def test_review_h1_unexpected_error_in_one_row_does_not_block_batch(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    make_dispatcher: MakeDispatcher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any other bug while handling one row (here: preparing it explodes) leaves that row for
    a retry after its lease, but the batch continues; and a row that keeps exploding is given
    up after OUTBOX_MAX_ATTEMPTS claims instead of being retried forever."""
    event_id = await create_event(admin, clock, capacity=10)
    for i in range(3):
        await register(client, event_id, f"p{i}@example.com")
    dispatcher = make_dispatcher(outbox_batch_size=10, outbox_max_attempts=2)
    real_deliver = dispatcher.deliver

    async def flaky_deliver(item: object) -> bool:
        if getattr(item, "to_email", "") == "p0@example.com":
            raise RuntimeError("bug while handling this one row")
        return await real_deliver(item)  # type: ignore[arg-type]

    monkeypatch.setattr(dispatcher, "deliver", flaky_deliver)
    for _ in range(4):
        await dispatcher.run_until_idle()
        clock.advance(timedelta(seconds=61))

    delivered = Counter(t["Address"] for m in await mailpit.wait_for(2) for t in m["To"])
    assert delivered == Counter(["p1@example.com", "p2@example.com"])
    rows = {r["to_email"]: r for r in await outbox(engine, event_id)}
    assert rows["p0@example.com"]["status"] == "failed"  # bounded, not an endless loop


# --------------------------------------------------------------------------------------- H2
async def test_review_h2_manage_token_not_in_backend_logs(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    test_db_url: str,
    tmp_path: Path,
) -> None:
    """The manage token is the participant's credential (view + cancel). Running the real
    uvicorn command, using it must not write it to the logs; the access log line itself must
    still be there (redacted), so operators keep their logs."""
    event_id = await create_event(admin, clock, capacity=5)
    await register(client, event_id, "logged@example.com")
    token = await token_for(engine, event_id, "logged@example.com")

    log = tmp_path / "uvicorn.log"
    with run_server(server_env(test_db_url, ORGANIZER_PASSWORD), 1, log) as server:
        async with httpx.AsyncClient(base_url=server.url) as http:
            assert (await http.get(f"/api/registrations/{token}")).status_code == 200
            assert (await http.post(f"/api/registrations/{token}/cancel")).status_code == 200
            assert (await http.get(f"/api/registrations/{token}?x=1")).status_code == 200
    text_logged = log.read_text()  # read after shutdown: everything flushed

    assert token not in text_logged
    assert "/api/registrations/[redacted]" in text_logged
