import uuid

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import AppSettings, Now, SessionMaker
from app.errors import DomainError
from app.models import RegistrationStatus
from app.schemas import (
    CheckInIn,
    CheckInOut,
    EmailCounts,
    EventCreate,
    EventOut,
    EventUpdate,
    EventUpdateOut,
    LoginIn,
    RegistrationAdminOut,
    StatsOut,
)
from app.security import (
    clear_session_cookie,
    password_matches,
    require_organizer,
    set_session_cookie,
)
from app.services import checkin, events, stats
from app.services.codes import format_ticket_code

public = APIRouter(prefix="/api/admin", tags=["organizer"])
router = APIRouter(
    prefix="/api/admin", tags=["organizer"], dependencies=[Depends(require_organizer)]
)


@public.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def login(body: LoginIn, settings: AppSettings, response: Response) -> None:
    if not password_matches(body.password, settings):
        raise DomainError("invalid_credentials", "Wrong password.", status=401)
    set_session_cookie(response, settings)


@public.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(settings: AppSettings, response: Response) -> None:
    clear_session_cookie(response, settings)


@router.get("/me")
async def me() -> dict[str, str]:
    return {"role": "organizer"}


@router.get("/events")
async def list_events(sm: SessionMaker) -> list[EventOut]:
    return await events.list_all(sm)


@router.post("/events", status_code=status.HTTP_201_CREATED)
async def create_event(body: EventCreate, sm: SessionMaker, now: Now) -> EventOut:
    return await events.create_event(sm, body, now)


@router.patch("/events/{event_id}")
async def update_event(
    event_id: uuid.UUID, body: EventUpdate, sm: SessionMaker, now: Now, settings: AppSettings
) -> EventUpdateOut:
    result = await events.update_event(sm, event_id, body, now, settings)
    return EventUpdateOut(**result.event.model_dump(), promoted_count=result.promoted_count)


@router.post("/events/{event_id}/checkin")
async def check_in(event_id: uuid.UUID, body: CheckInIn, sm: SessionMaker, now: Now) -> CheckInOut:
    result = await checkin.check_in(sm, event_id, body.code, now)
    return CheckInOut(email=result.email, checked_in_at=result.checked_in_at)


@router.get("/events/{event_id}/stats")
async def event_stats(event_id: uuid.UUID, sm: SessionMaker) -> StatsOut:
    s = await stats.event_stats(sm, event_id)
    return StatsOut(
        capacity=s.capacity,
        confirmed=s.confirmed,
        checked_in=s.checked_in,
        registered=s.registered,
        waitlisted=s.waitlisted,
        cancelled=s.cancelled,
        seats_left=s.seats_left,
        emails=EmailCounts(**s.emails),
    )


@router.get("/events/{event_id}/registrations")
async def list_registrations(
    event_id: uuid.UUID, sm: SessionMaker, status: RegistrationStatus | None = None
) -> list[RegistrationAdminOut]:
    rows = await stats.list_registrations(sm, event_id, status)
    return [
        RegistrationAdminOut(
            id=r.id,
            email=r.email,
            status=r.status,
            ticket_code=format_ticket_code(r.ticket_code),
            waitlist_position=r.waitlist_position,
            created_at=r.created_at,
            checked_in_at=r.checked_in_at,
        )
        for r in rows
    ]
