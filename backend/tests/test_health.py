import time
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.conftest import make_settings


async def _client_for(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.engine.dispose()


@pytest.fixture
async def client(test_db_url: str) -> AsyncIterator[AsyncClient]:
    async for c in _client_for(make_settings(test_db_url)):
        yield c


@pytest.fixture
async def client_without_db() -> AsyncIterator[AsyncClient]:
    # Port 1 on localhost: connection refused immediately, nothing is listening.
    settings = make_settings(
        "postgresql+psycopg://nobody:nopass@127.0.0.1:1/nothing_test",
        health_db_timeout_seconds=2.0,
    )
    async for c in _client_for(settings):
        yield c


@pytest.mark.parametrize("path", ["/api/health", "/health"])
async def test_health_ok(client: AsyncClient, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


@pytest.mark.parametrize("path", ["/api/health", "/health"])
async def test_health_reports_db_error_as_503(client_without_db: AsyncClient, path: str) -> None:
    response = await client_without_db.get(path)
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "error"}


async def test_health_db_timeout_returns_503_within_budget() -> None:
    """A DB that never answers must not hang the health check (it backs container healthchecks).
    10.255.255.1 is a non-routable address: packets are dropped, so connect() hangs."""
    settings = make_settings(
        "postgresql+psycopg://nobody:nopass@10.255.255.1:5432/nothing_test",
        health_db_timeout_seconds=0.5,
    )
    async for client in _client_for(settings):
        started = time.monotonic()
        response = await client.get("/api/health")
        elapsed = time.monotonic() - started
        assert response.status_code == 503
        assert elapsed < 2.0, f"health check took {elapsed:.2f}s with a 0.5s budget"
