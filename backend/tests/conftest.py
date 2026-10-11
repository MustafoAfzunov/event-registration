"""Test fixtures. Tests run against a REAL Postgres database (DECISIONS D-019), never SQLite
or mocks, because locking and constraint behaviour is what we need to prove.

The test DB URL comes from TEST_DATABASE_URL and must point at a database whose name ends
in "_test"; the suite downgrades/upgrades and truncates it freely."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from app.db import make_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
TABLES = ("email_outbox", "registrations", "events")


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
