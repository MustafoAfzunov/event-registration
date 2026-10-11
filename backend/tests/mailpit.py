"""Thin client for Mailpit's HTTP API (the test Mailpit instance, see docker-compose.yml).
Emails are verified where a user would see them: in the mailbox, not just in our DB."""

import asyncio
import os
from typing import Any

import httpx

API = os.environ.get("TEST_MAILPIT_API", "http://mailpit-test:8025")


class Mailpit:
    def __init__(self, base_url: str = API) -> None:
        self.http = httpx.AsyncClient(base_url=base_url, timeout=10)

    async def close(self) -> None:
        await self.http.aclose()

    async def clear(self) -> None:
        (await self.http.delete("/api/v1/messages")).raise_for_status()

    async def messages(self) -> list[dict[str, Any]]:
        response = await self.http.get("/api/v1/messages", params={"limit": 1000})
        response.raise_for_status()
        messages: list[dict[str, Any]] = response.json()["messages"]
        return messages

    async def to(self, address: str) -> list[dict[str, Any]]:
        return [m for m in await self.messages() if any(t["Address"] == address for t in m["To"])]

    async def text(self, message: dict[str, Any]) -> str:
        response = await self.http.get(f"/api/v1/message/{message['ID']}")
        response.raise_for_status()
        body: str = response.json()["Text"]
        return body

    async def wait_for(self, count: int, within: float = 15.0) -> list[dict[str, Any]]:
        """Wait until at least `count` messages arrived, then allow a short settle time so
        that any unexpected extra (duplicate) message also shows up before we assert."""
        try:
            async with asyncio.timeout(within):
                # Polling an external system (Mailpit) is the point here.
                while len(messages := await self.messages()) < count:  # noqa: ASYNC110
                    await asyncio.sleep(0.1)
        except TimeoutError:
            raise AssertionError(f"expected {count} emails, Mailpit has {len(messages)}") from None
        await asyncio.sleep(0.5)
        return await self.messages()
