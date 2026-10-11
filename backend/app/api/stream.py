"""Live update streams (SSE).

GET /api/events/{id}/stream        public:    event `availability` (seats left, waitlist)
GET /api/admin/events/{id}/stream  organizer: event `stats` (same body as /stats + event_id)
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import AppSettings, SessionMaker
from app.clock import Clock
from app.live.broker import Broker
from app.live.sse import stream_snapshots
from app.schemas import EmailCounts, LiveAvailabilityOut, LiveStatsOut
from app.security import organizer_session_expires_at, require_organizer
from app.services import events, stats

public = APIRouter(prefix="/api/events", tags=["live"])
organizer = APIRouter(
    prefix="/api/admin/events", tags=["live"], dependencies=[Depends(require_organizer)]
)


def _broker(request: Request) -> Broker:
    broker: Broker = request.app.state.broker
    return broker


@public.get("/{event_id}/stream", response_class=StreamingResponse)
async def public_stream(
    event_id: uuid.UUID, request: Request, sm: SessionMaker, settings: AppSettings
) -> StreamingResponse:
    async def snapshot() -> str:
        e = await events.get_event(sm, event_id)
        return LiveAvailabilityOut(
            event_id=e.id,
            status=e.status,
            starts_at=e.starts_at,
            capacity=e.capacity,
            seats_left=e.seats_left,
            waitlist_count=e.waitlist_count,
        ).model_dump_json()

    first = await snapshot()  # 404 here is still a normal JSON error
    return await stream_snapshots(
        request=request,
        broker=_broker(request),
        event_id=event_id,
        event_name="availability",
        snapshot=snapshot,
        first=first,
        keepalive_seconds=settings.sse_keepalive_seconds,
    )


@organizer.get("/{event_id}/stream", response_class=StreamingResponse)
async def organizer_stream(
    event_id: uuid.UUID, request: Request, sm: SessionMaker, settings: AppSettings
) -> StreamingResponse:
    async def snapshot() -> str:
        s = await stats.event_stats(sm, event_id)
        return LiveStatsOut(
            event_id=event_id,
            capacity=s.capacity,
            confirmed=s.confirmed,
            checked_in=s.checked_in,
            registered=s.registered,
            waitlisted=s.waitlisted,
            cancelled=s.cancelled,
            seats_left=s.seats_left,
            emails=EmailCounts(**s.emails),
        ).model_dump_json()

    first = await snapshot()
    clock: Clock = request.app.state.clock

    def now() -> datetime:
        return clock.now()

    return await stream_snapshots(
        request=request,
        broker=_broker(request),
        event_id=event_id,
        event_name="stats",
        snapshot=snapshot,
        first=first,
        keepalive_seconds=settings.sse_keepalive_seconds,
        expires_at=organizer_session_expires_at(request),
        clock_now=now,
    )
