"""Live updates over SSE against REAL uvicorn processes (see live_servers fixture).

Mutations are made by the test process's own in-process app (or by another server), so an
update can only reach a stream through Postgres LISTEN/NOTIFY, never through shared memory."""

import asyncio
import uuid
from collections.abc import Callable
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any

import httpx
import psycopg
import pytest
from httpx import AsyncClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from app.emails.dispatcher import Dispatcher
from app.live.broker import Broker
from app.services import registration as registration_service
from tests.conftest import ORGANIZER_PASSWORD
from tests.helpers import cancel, create_event, register, registrations, token_for
from tests.live_server import LiveServer, run_server, server_env
from tests.mailpit import Mailpit
from tests.sse import SSEStream, open_stream

Servers = dict[str, LiveServer]


async def organizer_cookies(server: LiveServer) -> httpx.Cookies:
    async with httpx.AsyncClient(base_url=server.url) as c:
        r = await c.post("/api/admin/login", json={"password": ORGANIZER_PASSWORD})
        assert r.status_code == 204
        return c.cookies


def public_path(event_id: str) -> str:
    return f"/api/events/{event_id}/stream"


def organizer_path(event_id: str) -> str:
    return f"/api/admin/events/{event_id}/stream"


async def checkin(admin: AsyncClient, event_id: str, code: str) -> None:
    r = await admin.post(f"/api/admin/events/{event_id}/checkin", json={"code": code})
    assert r.status_code == 200, r.text


async def next_all(streams: list[SSEStream]) -> list[dict[str, Any]]:
    frames = await asyncio.gather(*[s.next() for s in streams])
    return [f.data for f in frames]


def pick(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: data[k] for k in keys}


ORG_KEYS = ("confirmed", "checked_in", "registered", "waitlisted", "cancelled", "seats_left")
PUB_KEYS = ("seats_left", "waitlist_count")


async def test_public_stream_sends_snapshot_on_connect(
    live_servers: Servers, client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=3)
    await register(client, event_id, "a@example.com")
    event = (await client.get(f"/api/events/{event_id}")).json()

    async with open_stream(live_servers["a"].url, public_path(event_id)) as stream:
        first = await stream.next()

    assert stream.retry_ms == 3000  # reconnect hint for EventSource
    assert first.event == "availability"
    # Exactly these keys: no emails, no attendance numbers on the public stream.
    assert first.data == {
        "event_id": event_id,
        "status": "scheduled",
        "starts_at": event["starts_at"],
        "capacity": 3,
        "seats_left": 2,
        "waitlist_count": 0,
    }


async def test_organizer_stream_sends_snapshot_on_connect(
    live_servers: Servers, client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=3)
    await register(client, event_id, "a@example.com")
    stats = (await admin.get(f"/api/admin/events/{event_id}/stats")).json()
    cookies = await organizer_cookies(live_servers["a"])

    async with open_stream(live_servers["a"].url, organizer_path(event_id), cookies) as stream:
        first = await stream.next()

    assert first.event == "stats"
    assert first.data == {**stats, "event_id": event_id}


async def test_two_clients_receive_registration_cancellation_and_checkin(
    live_servers: Servers,
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
) -> None:
    """Organizer streams on two different backend processes, public streams on both too.
    Every change, made by a third process (this test's app), reaches all four."""
    a, b = live_servers["a"], live_servers["b"]
    assert a.pids != b.pids
    event_id = await create_event(admin, clock, capacity=2)
    cookies = await organizer_cookies(a)

    async with AsyncExitStack() as stack:
        org = [
            await stack.enter_async_context(open_stream(srv.url, organizer_path(event_id), cookies))
            for srv in (a, b)
        ]
        pub = [
            await stack.enter_async_context(open_stream(srv.url, public_path(event_id)))
            for srv in (a, b)
        ]
        await next_all(org + pub)  # initial snapshots

        async def expect(org_expected: dict[str, int], pub_expected: dict[str, int] | None) -> None:
            org_frames = await next_all(org)
            assert [pick(f, *ORG_KEYS) for f in org_frames] == [org_expected] * 2
            api = (await admin.get(f"/api/admin/events/{event_id}/stats")).json()
            assert pick(api, *ORG_KEYS) == org_expected
            if pub_expected is None:
                for stream in pub:
                    await stream.assert_silent(1.0)  # public view unchanged -> no frame
            else:
                assert [pick(f, *PUB_KEYS) for f in await next_all(pub)] == [pub_expected] * 2

        org_state = dict.fromkeys(ORG_KEYS, 0)

        def state(**changes: int) -> dict[str, int]:
            org_state.update(changes)
            return dict(org_state)

        # Registration
        await register(client, event_id, "first@example.com")
        await expect(
            state(confirmed=1, registered=1, seats_left=1), {"seats_left": 1, "waitlist_count": 0}
        )
        await register(client, event_id, "second@example.com")
        await expect(
            state(confirmed=2, registered=2, seats_left=0), {"seats_left": 0, "waitlist_count": 0}
        )
        await register(client, event_id, "third@example.com")  # full -> waitlist
        await expect(state(waitlisted=1), {"seats_left": 0, "waitlist_count": 1})

        # Cancellation (with automatic promotion of the waitlisted person)
        await cancel(client, await token_for(engine, event_id, "first@example.com"))
        await expect(state(waitlisted=0, cancelled=1), {"seats_left": 0, "waitlist_count": 0})

        # Check-in: organizer counters move; the public view (seats/waitlist) does not.
        code = next(
            r["ticket_code"]
            for r in await registrations(engine, event_id)
            if r["email"] == "second@example.com"
        )
        await checkin(admin, event_id, str(code))
        await expect(state(confirmed=1, checked_in=1), None)


async def test_update_reaches_every_worker_of_a_multi_worker_server(
    live_servers: Servers, client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    """`uvicorn --workers 2` (as in compose): streams are opened on separate connections
    until both worker processes hold some; a write handled by ONE of the workers (or by
    another process) must reach the streams on BOTH."""
    multi = live_servers["multi"]
    event_id = await create_event(admin, clock, capacity=50)

    async with AsyncExitStack() as stack:
        streams: list[SSEStream] = []
        for _ in range(30):
            streams.append(
                await stack.enter_async_context(open_stream(multi.url, public_path(event_id)))
            )
            if {s.pid for s in streams} == set(multi.pids) and len(streams) >= 4:
                break
        assert {s.pid for s in streams} == set(multi.pids), (
            "streams did not spread over both workers"
        )
        await next_all(streams)

        # Write through the multi-worker server itself (one of its workers handles it)...
        async with httpx.AsyncClient(base_url=multi.url) as http:
            r = await http.post(
                f"/api/events/{event_id}/registrations", json={"email": "w1@example.com"}
            )
            assert r.status_code == 201
            writer_pid = r.headers["x-backend-pid"]
        frames = await next_all(streams)
        assert {f["seats_left"] for f in frames} == {49}
        assert any(s.pid != writer_pid for s in streams)  # some stream is on the other worker

        # ...and through a completely different process.
        await register(client, event_id, "w2@example.com")
        assert {f["seats_left"] for f in await next_all(streams)} == {48}


async def test_other_events_do_not_leak_into_a_stream(
    live_servers: Servers, client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    mine = await create_event(admin, clock, capacity=10, title="Mine")
    other = await create_event(admin, clock, capacity=10, title="Other")
    cookies = await organizer_cookies(live_servers["a"])

    async with (
        open_stream(live_servers["a"].url, organizer_path(mine), cookies) as org,
        open_stream(live_servers["b"].url, public_path(mine)) as pub,
    ):
        await next_all([org, pub])
        for i in range(5):
            await register(client, other, f"other{i}@example.com")
        await org.assert_silent(1.0)
        await pub.assert_silent(0.1)

        await register(client, mine, "me@example.com")
        o, p = await next_all([org, pub])
        assert (o["event_id"], o["registered"]) == (mine, 1)
        assert (p["event_id"], p["seats_left"]) == (mine, 9)
        await org.assert_silent(1.0)  # exactly one frame for one change


async def test_broker_routes_signals_by_event_id(
    test_db_url: str, client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    """Below the wire: a subscriber is not even woken for another event's changes (the
    wire test alone could not tell, since an unchanged snapshot is never re-sent)."""
    mine = await create_event(admin, clock, capacity=10)
    other = await create_event(admin, clock, capacity=10)
    broker = Broker(test_db_url)
    sub_mine, sub_other = broker.subscribe(uuid.UUID(mine)), broker.subscribe(uuid.UUID(other))
    try:
        await asyncio.wait_for(broker.connected.wait(), 10)
        await sub_mine.wait(0.5)  # consume the initial resync wake-up
        await sub_other.wait(0.5)

        await register(client, other, "x@example.com")
        assert await sub_other.wait(5) is True
        assert await sub_mine.wait(0.5) is False

        await register(client, mine, "y@example.com")
        assert await sub_mine.wait(5) is True
        assert await sub_other.wait(0.5) is False
    finally:
        sub_mine.close()
        sub_other.close()
        assert broker.subscriber_count() == 0
        await broker.stop()


async def test_reconnect_gets_current_snapshot(
    live_servers: Servers, client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    cookies = await organizer_cookies(live_servers["a"])
    async with open_stream(live_servers["a"].url, organizer_path(event_id), cookies) as s:
        assert (await s.next()).data["registered"] == 0

    # Changes while the client is disconnected (network blip, laptop asleep, tab reload).
    for i in range(3):
        await register(client, event_id, f"while-away{i}@example.com")

    # Reconnect (possibly to another backend process): first frame = current state.
    for server in (live_servers["a"], live_servers["b"]):
        async with open_stream(server.url, organizer_path(event_id), cookies) as s:
            first = (await s.next()).data
        assert pick(first, "registered", "seats_left") == {"registered": 3, "seats_left": 2}
    async with open_stream(live_servers["b"].url, public_path(event_id)) as s:
        assert (await s.next()).data["seats_left"] == 2


async def test_listener_connection_loss_is_healed_and_resynced(
    live_servers: Servers,
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
) -> None:
    """Kill every backend's LISTEN connection in Postgres, then change data right away
    (while nobody listens). The broker reconnects and resyncs: the change still arrives."""
    event_id = await create_event(admin, clock, capacity=10)
    async with open_stream(live_servers["a"].url, public_path(event_id)) as stream:
        await stream.next()
        async with engine.connect() as conn:
            killed = await conn.scalar(
                text(
                    "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND query = 'LISTEN event_changed'"
                )
            )
        assert killed and killed >= 1

        await register(client, event_id, "during-outage@example.com")
        assert (await stream.next(within=10)).data["seats_left"] == 9

        await register(client, event_id, "after-recovery@example.com")  # listener is back
        assert (await stream.next(within=5)).data["seats_left"] == 8


async def test_notification_only_on_commit(
    test_db_url: str,
    client: AsyncClient,
    admin: AsyncClient,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    conninfo = (
        make_url(test_db_url).set(drivername="postgresql").render_as_string(hide_password=False)
    )
    async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as listener:
        await listener.execute("LISTEN event_changed")

        async def next_note(within: float) -> str | None:
            gen = listener.notifies(timeout=within, stop_after=1)
            async for note in gen:
                return note.payload
            return None

        real_notify = registration_service.notify_event_changed

        async def notify_then_fail(*args: Any, **kwargs: Any) -> None:
            await real_notify(*args, **kwargs)
            raise RuntimeError("fail after notify")

        monkeypatch.setattr(registration_service, "notify_event_changed", notify_then_fail)
        with pytest.raises(RuntimeError):
            await register(client, event_id, "rolled-back@example.com")
        assert await next_note(1.0) is None  # rolled back -> never delivered

        monkeypatch.setattr(registration_service, "notify_event_changed", real_notify)
        assert (await register(client, event_id, "committed@example.com")).status_code == 201
        assert await next_note(5.0) == event_id


async def test_email_delivery_updates_organizer_stream(
    live_servers: Servers,
    client: AsyncClient,
    admin: AsyncClient,
    clock: FixedClock,
    mailpit: Mailpit,
    make_dispatcher: Callable[..., Dispatcher],
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    cookies = await organizer_cookies(live_servers["a"])
    async with open_stream(live_servers["a"].url, organizer_path(event_id), cookies) as s:
        await s.next()
        await register(client, event_id, "mail@example.com")
        assert (await s.next()).data["emails"]["pending"] == 1
        await make_dispatcher().run_until_idle()  # the worker's completion also notifies
        emails = (await s.next()).data["emails"]
        assert (emails["pending"], emails["sent"]) == (0, 1)


async def test_keepalive_comments_on_idle_stream(
    live_servers: Servers, admin: AsyncClient, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    async with open_stream(live_servers["a"].url, public_path(event_id)) as s:
        await s.next()
        await asyncio.sleep(2.5)  # SSE_KEEPALIVE_SECONDS=1 on test servers
    assert s.comments.count(": keepalive") >= 2


async def test_stream_errors_are_json_before_streaming(
    live_servers: Servers, admin: AsyncClient, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    async with httpx.AsyncClient(base_url=live_servers["a"].url) as http:
        r = await http.get(organizer_path(event_id))
        assert (r.status_code, r.json()["error"]["code"]) == (401, "unauthorized")
        missing = str(uuid.uuid4())
        r = await http.get(public_path(missing))
        assert (r.status_code, r.json()["error"]["code"]) == (404, "event_not_found")
    cookies = await organizer_cookies(live_servers["a"])
    async with httpx.AsyncClient(base_url=live_servers["a"].url, cookies=cookies) as http:
        r = await http.get(organizer_path(missing))
        assert (r.status_code, r.json()["error"]["code"]) == (404, "event_not_found")


async def test_organizer_stream_ends_when_login_expires(
    test_db_url: str, admin: AsyncClient, clock: FixedClock, tmp_path: Any
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    env = server_env(test_db_url, ORGANIZER_PASSWORD, SESSION_MAX_AGE_SECONDS="2")
    with run_server(env, 1, tmp_path / "short.log") as server:
        cookies = await organizer_cookies(server)
        async with open_stream(server.url, organizer_path(event_id), cookies) as s:
            await s.next()
            ended = await s.next(within=6)
    assert ended.event == "session_expired"


async def test_stream_releases_subscription_when_client_goes_away(test_db_url: str) -> None:
    """The SSE body generator always unsubscribes (finally), so closed tabs don't leak
    subscribers in a long-running worker."""
    from starlette.requests import Request

    from app.live.sse import stream_snapshots

    broker = Broker(test_db_url)

    async def receive() -> dict[str, str]:
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []}, receive)

    async def snapshot() -> str:
        return "{}"

    response = await stream_snapshots(
        request=request, broker=broker, event_id=uuid.uuid4(), event_name="x",
        snapshot=snapshot, first="{}", keepalive_seconds=0.05,
    )  # fmt: skip
    body = response.body_iterator
    assert broker.subscriber_count() == 1
    assert "event: x" in str(await body.__anext__())
    await body.aclose()  # what Starlette does when the client disconnects
    assert broker.subscriber_count() == 0
    await broker.stop()


async def test_reschedule_and_event_cancel_reach_public_stream(
    live_servers: Servers, client: AsyncClient, admin: AsyncClient, clock: FixedClock
) -> None:
    event_id = await create_event(admin, clock, capacity=5)
    async with open_stream(live_servers["b"].url, public_path(event_id)) as s:
        await s.next()
        new = (clock.now() + timedelta(days=10)).replace(microsecond=0)
        r = await admin.post(
            f"/api/admin/events/{event_id}/reschedule", json={"starts_at": new.isoformat()}
        )
        assert r.status_code == 200
        assert (await s.next()).data["starts_at"] == new.isoformat().replace("+00:00", "Z")
        await admin.post(f"/api/admin/events/{event_id}/cancel")
        assert (await s.next()).data["status"] == "cancelled"
