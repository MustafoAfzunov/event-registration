"""Minimal SSE client for tests, over a REAL HTTP connection (httpx's in-process ASGI
transport buffers whole responses, so it cannot test streams)."""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class Frame:
    event: str
    data: dict[str, Any]


@dataclass
class SSEStream:
    response: httpx.Response
    frames: "asyncio.Queue[Frame]" = field(default_factory=asyncio.Queue)
    comments: list[str] = field(default_factory=list)
    retry_ms: int | None = None

    @property
    def pid(self) -> str:
        return self.response.headers.get("x-backend-pid", "?")

    async def next(self, within: float = 5.0) -> Frame:
        try:
            return await asyncio.wait_for(self.frames.get(), within)
        except TimeoutError:
            raise AssertionError(f"no SSE frame within {within}s") from None

    async def assert_silent(self, within: float) -> None:
        """No data frame arrives during `within` seconds (keepalives are fine)."""
        try:
            frame = await asyncio.wait_for(self.frames.get(), within)
        except TimeoutError:
            return
        raise AssertionError(f"unexpected frame: {frame}")


async def _read(stream: SSEStream) -> None:
    event, data = "message", []
    async for line in stream.response.aiter_lines():
        if line.startswith(":"):
            stream.comments.append(line)
        elif line.startswith("retry:"):
            stream.retry_ms = int(line.split(":", 1)[1])
        elif line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data.append(line.split(":", 1)[1].strip())
        elif line == "" and data:
            await stream.frames.put(Frame(event, json.loads("\n".join(data))))
            event, data = "message", []


@asynccontextmanager
async def open_stream(
    base_url: str, path: str, cookies: httpx.Cookies | None = None
) -> AsyncIterator[SSEStream]:
    # One client per stream => its own TCP connection => the kernel picks a worker for it.
    async with (
        httpx.AsyncClient(
            base_url=base_url, cookies=cookies, timeout=httpx.Timeout(10, read=None)
        ) as client,
        client.stream("GET", path, headers={"Accept": "text/event-stream"}) as response,
    ):
        assert response.status_code == 200, await response.aread()
        assert response.headers["content-type"].startswith("text/event-stream")
        stream = SSEStream(response)
        reader = asyncio.create_task(_read(stream))
        try:
            yield stream
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, httpx.HTTPError):
                await reader
