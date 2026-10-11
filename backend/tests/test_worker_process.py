"""The real worker process (`python -m app.worker`), restarted mid-batch with real signals.

SIGTERM (docker stop, deploy): graceful -> the in-flight message is finished and recorded,
  the rest of the batch is released => NO duplicates at all.
SIGKILL (crash): at-least-once -> every email is delivered; at most the single message that
  was in flight at the moment of the kill can arrive twice (same Message-ID). D-043."""

import asyncio
import os
import signal
import sys
from collections import Counter
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock
from tests.conftest import BACKEND_DIR, ORGANIZER_PASSWORD, SMTP_HOST, SMTP_PORT
from tests.helpers import create_event, outbox, register
from tests.mailpit import Mailpit

N = 20


@pytest.fixture
def worker_env(test_db_url: str, tmp_path: Path) -> dict[str, str]:
    return {
        **os.environ,
        "DATABASE_URL": test_db_url,
        "ORGANIZER_PASSWORD": ORGANIZER_PASSWORD,
        "SESSION_SECRET": "test-session-secret-0123456789abcdef",
        "SMTP_HOST": SMTP_HOST,
        "SMTP_PORT": str(SMTP_PORT),
        "SMTP_TIMEOUT_SECONDS": "0.5",
        "OUTBOX_POLL_SECONDS": "0.2",
        "OUTBOX_BATCH_SIZE": "5",
        # Throttle so a signal reliably lands in the middle of a batch.
        "OUTBOX_SEND_INTERVAL_SECONDS": "0.2",
        "OUTBOX_LEASE_SECONDS": "4",  # > 5 * (0.5 + 0.2)
        "WORKER_HEARTBEAT_FILE": str(tmp_path / "heartbeat"),
    }


@pytest.fixture
async def spawn(worker_env: dict[str, str]) -> AsyncIterator[object]:
    procs: list[asyncio.subprocess.Process] = []

    async def start() -> asyncio.subprocess.Process:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.worker",
            cwd=BACKEND_DIR,
            env=worker_env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        procs.append(proc)
        return proc

    yield start
    for proc in procs:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def _enqueue(admin: AsyncClient, client: AsyncClient, clock: FixedClock) -> str:
    event_id = await create_event(admin, clock, capacity=100)
    for i in range(N):
        await register(client, event_id, f"proc{i}@example.com")
    return event_id


async def _wait_distinct(mailpit: Mailpit, n: int, within: float) -> None:
    async with asyncio.timeout(within):
        while len({m["MessageID"] for m in await mailpit.messages()}) < n:  # noqa: ASYNC110
            await asyncio.sleep(0.1)


async def test_sigterm_mid_batch_then_restart_sends_each_email_once(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    spawn: object,
) -> None:
    event_id = await _enqueue(admin, client, clock)
    start = spawn  # type: ignore[assignment]

    worker = await start()  # type: ignore[operator]
    await _wait_distinct(mailpit, 3, within=15)
    worker.send_signal(signal.SIGTERM)
    assert await asyncio.wait_for(worker.wait(), timeout=10) == 0  # clean, prompt exit

    rows = await outbox(engine, event_id)
    statuses = Counter(r["status"] for r in rows)
    assert statuses["sending"] == 0, "graceful stop must release claimed rows"
    assert 3 <= statuses["sent"] < N, f"signal should land mid-run: {statuses}"
    # Everything in the mailbox is recorded as sent => nothing can be sent twice later.
    assert len(await mailpit.messages()) == statuses["sent"]

    worker = await start()  # type: ignore[operator]
    await _wait_distinct(mailpit, N, within=30)
    await asyncio.sleep(1)  # give any (wrong) duplicate a chance to show up
    worker.send_signal(signal.SIGTERM)
    await asyncio.wait_for(worker.wait(), timeout=10)

    messages = await mailpit.messages()
    assert len(messages) == N
    assert len({m["MessageID"] for m in messages}) == N
    assert {r["status"] for r in await outbox(engine, event_id)} == {"sent"}


async def test_sigkill_mid_batch_then_restart_delivers_all_at_most_one_duplicate(
    client: AsyncClient,
    admin: AsyncClient,
    engine: AsyncEngine,
    clock: FixedClock,
    mailpit: Mailpit,
    spawn: object,
) -> None:
    event_id = await _enqueue(admin, client, clock)
    start = spawn  # type: ignore[assignment]

    worker = await start()  # type: ignore[operator]
    await _wait_distinct(mailpit, 3, within=15)
    worker.kill()  # SIGKILL: no cleanup, claimed rows stay leased
    await worker.wait()
    assert Counter(r["status"] for r in await outbox(engine, event_id))["sending"] > 0

    worker = await start()  # type: ignore[operator]
    await _wait_distinct(mailpit, N, within=30)  # waits out the dead worker's 4s lease
    await asyncio.sleep(1)
    worker.send_signal(signal.SIGTERM)
    await asyncio.wait_for(worker.wait(), timeout=10)

    messages = await mailpit.messages()
    distinct = {m["MessageID"] for m in messages}
    assert len(distinct) == N  # every email delivered at least once
    assert len(messages) - len(distinct) <= 1  # only the in-flight one may repeat
    assert {r["status"] for r in await outbox(engine, event_id)} == {"sent"}
