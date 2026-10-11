"""Server-Sent Events plumbing shared by the public and organizer streams.

Protocol (docs/API.md): on connect -> `retry:` hint + one full snapshot; afterwards a new
snapshot whenever the data changed (identical snapshots are not re-sent); a `: keepalive`
comment every SSE_KEEPALIVE_SECONDS so proxies keep the connection open. Snapshot-based,
not delta-based: a reconnecting client just receives the current snapshot."""

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime

from fastapi import Request
from fastapi.responses import StreamingResponse

from app.live.broker import Broker

logger = logging.getLogger(__name__)

RETRY_MS = 3000
HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # tell nginx not to buffer this response
}


def frame(event: str, payload: str) -> str:
    return f"event: {event}\ndata: {payload}\n\n"


async def stream_snapshots(
    *,
    request: Request,
    broker: Broker,
    event_id: object,
    event_name: str,
    snapshot: Callable[[], Awaitable[str]],
    first: str,
    keepalive_seconds: float,
    expires_at: datetime | None = None,
    clock_now: Callable[[], datetime] | None = None,
) -> StreamingResponse:
    """`first` is the initial snapshot, computed by the caller before the response starts so
    that 401/404 are still normal JSON errors. A change committed between that snapshot and
    `subscribe()` below would otherwise be missed, so the subscription is woken once right
    away: the loop re-reads and sends a new frame if anything changed in that gap."""
    subscription = broker.subscribe(event_id)  # type: ignore[arg-type]

    async def body() -> AsyncIterator[str]:
        last = first
        try:
            yield f"retry: {RETRY_MS}\n" + frame(event_name, first)
            # Close the gap between the caller's snapshot and subscribe().
            subscription.wake()
            while True:
                if expires_at is not None and clock_now is not None and clock_now() >= expires_at:
                    yield frame("session_expired", json.dumps({"reason": "login expired"}))
                    return
                if await request.is_disconnected():
                    return
                if not await subscription.wait(keepalive_seconds):
                    yield ": keepalive\n\n"
                    continue
                current = await snapshot()
                if current != last:
                    last = current
                    yield frame(event_name, current)
        finally:
            subscription.close()

    return StreamingResponse(body(), media_type="text/event-stream", headers=HEADERS)
