"""Test fixtures. Tests run against a REAL Postgres database (DECISIONS D-019), never SQLite
or mocks, because locking and constraint behaviour is what we need to prove.

The test DB URL comes from TEST_DATABASE_URL and must point at a database whose name ends
in "_test"; the suite downgrades/upgrades and truncates it freely."""

import os
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from app.clock import FixedClock
from app.config import Settings
from app.db import make_engine
from app.emails.dispatcher import Dispatcher
from app.emails.smtp import Sender, SmtpSender
from app.main import create_app
from app.scheduler import Scheduler
from tests.live_server import LiveServer, run_server, server_env
from tests.mailpit import Mailpit

BACKEND_DIR = Path(__file__).resolve().parents[1]
TABLES = ("email_outbox", "registrations", "events")
ORGANIZER_PASSWORD = "test-organizer-password"


def make_settings(database_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": database_url,
        "organizer_password": ORGANIZER_PASSWORD,
        "session_secret": "test-session-secret-0123456789abcdef",
        "public_base_url": "http://app.test",
        # Enough connections that N parallel requests really hold N connections at once.
        "db_pool_size": 40,
        "db_max_overflow": 10,
    }
    values.update(overrides)
    return Settings(**values)


def _test_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.exit("TEST_DATABASE_URL is not set (run tests via `make test`)", returncode=2)
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        pytest.exit(f"Refusing to run tests against non-test database {database!r}", returncode=2)
    return url


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def test_db_url() -> str:
    return _test_db_url()


@pytest.fixture(scope="session", autouse=True)
def migrated_db(test_db_url: str) -> Iterator[None]:
    cfg = alembic_config(test_db_url)
    # Start from a clean slate even if a previous run died half-way.
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
async def engine(test_db_url: str) -> AsyncIterator[AsyncEngine]:
    eng = make_engine(test_db_url)
    async with eng.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
        await conn.execute(text("ALTER SEQUENCE registration_queue_seq RESTART"))
    yield eng
    await eng.dispose()


@pytest.fixture
def clock() -> FixedClock:
    """Frozen at real 'now'; tests move it with clock.advance()/set()."""
    return FixedClock(datetime.now(UTC))


@pytest.fixture
async def app(engine: AsyncEngine, test_db_url: str, clock: FixedClock) -> AsyncIterator[FastAPI]:
    # Depends on `engine` so tables are truncated before the app touches them.
    application = create_app(make_settings(test_db_url), clock=clock)
    yield application
    await application.state.engine.dispose()


def _client(application: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Anonymous client (participant)."""
    async with _client(app) as c:
        yield c


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Logged-in organizer client (own cookie jar)."""
    async with _client(app) as c:
        response = await c.post("/api/admin/login", json={"password": ORGANIZER_PASSWORD})
        assert response.status_code == 204, response.text
        yield c


SMTP_HOST = os.environ.get("TEST_SMTP_HOST", "mailpit-test")
SMTP_PORT = int(os.environ.get("TEST_SMTP_PORT", "1025"))


@pytest.fixture
async def mailpit() -> AsyncIterator[Mailpit]:
    """The test Mailpit, emptied before each test that uses it."""
    client = Mailpit()
    await client.clear()
    yield client
    await client.close()


@pytest.fixture
def smtp() -> SmtpSender:
    return SmtpSender(SMTP_HOST, SMTP_PORT, timeout=5)


@pytest.fixture
def make_dispatcher(app: FastAPI, clock: FixedClock, smtp: SmtpSender) -> Callable[..., Dispatcher]:
    """Build a dispatcher sharing the app's DB and clock. Each call = a fresh 'worker'."""

    def build(sender: Sender | None = None, **overrides: Any) -> Dispatcher:
        settings = app.state.settings.model_copy(
            update={"outbox_lease_seconds": 60, "smtp_timeout_seconds": 5, **overrides}
        )
        return Dispatcher(app.state.sessionmaker, sender or smtp, clock, settings)

    return build


@pytest.fixture(scope="module")
def live_servers(
    test_db_url: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[dict[str, LiveServer]]:
    """Three real backends sharing the test DB, started once per test module:
    'a' and 'b' are separate single-worker processes (deterministic cross-process checks);
    'multi' is `uvicorn --workers 2`, exactly like the compose backend."""
    env = server_env(test_db_url, ORGANIZER_PASSWORD)
    logs = tmp_path_factory.mktemp("uvicorn")
    with (
        run_server(env, 1, logs / "a.log") as a,
        run_server(env, 1, logs / "b.log") as b,
        run_server(env, 2, logs / "multi.log") as multi,
    ):
        yield {"a": a, "b": b, "multi": multi}


@pytest.fixture
def make_scheduler(app: FastAPI, clock: FixedClock) -> Callable[..., Scheduler]:
    """A reminder scheduler sharing the app's DB and clock. Each call = a fresh instance."""

    def build(**overrides: Any) -> Scheduler:
        settings = app.state.settings.model_copy(update=overrides)
        return Scheduler(app.state.sessionmaker, clock, settings)

    return build
