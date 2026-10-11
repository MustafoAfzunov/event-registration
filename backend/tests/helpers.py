"""Small API/DB helpers shared by tests. Participants never see their manage token in an
API response (D-012), so tests read it from the DB, as the email would deliver it."""

import uuid
from datetime import timedelta
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.clock import FixedClock


async def create_event(
    admin: AsyncClient,
    clock: FixedClock,
    capacity: int,
    starts_in: timedelta = timedelta(days=7),
    title: str = "Test event",
) -> str:
    response = await admin.post(
        "/api/admin/events",
        json={
            "title": title,
            "description": "Testing",
            "starts_at": (clock.now() + starts_in).isoformat(),
            "capacity": capacity,
        },
    )
    assert response.status_code == 201, response.text
    event_id: str = response.json()["id"]
    return event_id


async def register(client: AsyncClient, event_id: str, email: str) -> Response:
    return await client.post(f"/api/events/{event_id}/registrations", json={"email": email})


async def token_for(engine: AsyncEngine, event_id: str, email_normalized: str) -> str:
    """Manage token of the active registration (or latest one) for this email."""
    async with engine.connect() as conn:
        token = await conn.scalar(
            text(
                "SELECT manage_token FROM registrations WHERE event_id = :e "
                "AND email_normalized = :m ORDER BY (status <> 'cancelled') DESC, created_at DESC "
                "LIMIT 1"
            ),
            {"e": uuid.UUID(event_id), "m": email_normalized},
        )
    assert token is not None, f"no registration for {email_normalized}"
    return str(token)


async def cancel(client: AsyncClient, token: str) -> Response:
    return await client.post(f"/api/registrations/{token}/cancel")


async def registrations(engine: AsyncEngine, event_id: str) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, email, email_normalized, status::text AS status, queue_seq, "
                "ticket_code, created_at FROM registrations WHERE event_id = :e "
                "ORDER BY created_at, queue_seq NULLS FIRST"
            ),
            {"e": uuid.UUID(event_id)},
        )
        return [dict(r._mapping) for r in rows]


async def statuses(engine: AsyncEngine, event_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in await registrations(engine, event_id):
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


async def outbox(engine: AsyncEngine, event_id: str | None = None) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        sql = (
            "SELECT kind::text AS kind, dedupe_key, to_email, subject, body_text, "
            "registration_id, status::text AS status, attempts FROM email_outbox"
        )
        params: dict[str, Any] = {}
        if event_id:
            sql += " WHERE event_id = :e"
            params["e"] = uuid.UUID(event_id)
        rows = await conn.execute(text(sql + " ORDER BY id"), params)
        return [dict(r._mapping) for r in rows]
