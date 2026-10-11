import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import ORGANIZER_PASSWORD

ADMIN_CALLS = [
    ("GET", "/api/admin/me", None),
    ("GET", "/api/admin/events", None),
    (
        "POST",
        "/api/admin/events",
        {"title": "x", "starts_at": "2099-01-01T00:00:00Z", "capacity": 1},
    ),
    ("PATCH", f"/api/admin/events/{uuid.uuid4()}", {"capacity": 3}),
]


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_CALLS)
async def test_admin_endpoints_require_cookie(
    client: AsyncClient, method: str, path: str, body: object
) -> None:
    response = await client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_login_wrong_password_401(client: AsyncClient) -> None:
    response = await client.post("/api/admin/login", json={"password": "wrong-password"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert "set-cookie" not in response.headers
    assert (await client.get("/api/admin/me")).status_code == 401


async def test_login_sets_httponly_samesite_cookie(client: AsyncClient) -> None:
    response = await client.post("/api/admin/login", json={"password": ORGANIZER_PASSWORD})
    assert response.status_code == 204
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("eventreg_admin=")
    for attribute in ["httponly", "samesite=strict", "path=/api", "max-age=43200"]:
        assert attribute in cookie, cookie
    assert (await client.get("/api/admin/me")).json() == {"role": "organizer"}


async def test_tampered_cookie_rejected(client: AsyncClient) -> None:
    await client.post("/api/admin/login", json={"password": ORGANIZER_PASSWORD})
    value = client.cookies["eventreg_admin"]
    client.cookies.set(
        "eventreg_admin", value[:-2] + ("A" if value[-2] != "A" else "B") + value[-1], path="/api"
    )
    assert (await client.get("/api/admin/me")).status_code == 401


async def test_logout_clears_cookie(admin: AsyncClient) -> None:
    assert (await admin.get("/api/admin/me")).status_code == 200
    assert (await admin.post("/api/admin/logout")).status_code == 204
    assert (await admin.get("/api/admin/me")).status_code == 401
