import uuid

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import AppSettings, Now, SessionMaker
from app.errors import DomainError
from app.schemas import EventCreate, EventOut, EventUpdate, EventUpdateOut, LoginIn
from app.security import (
    clear_session_cookie,
    password_matches,
    require_organizer,
    set_session_cookie,
)
from app.services import events

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
