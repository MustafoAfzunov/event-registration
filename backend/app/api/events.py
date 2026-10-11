import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import AppSettings, Now, SessionMaker
from app.models import RegistrationStatus
from app.schemas import EventOut, RegisterIn, RegisterOut
from app.services import events, registration

router = APIRouter(prefix="/api/events", tags=["public"])


@router.get("")
async def list_events(sm: SessionMaker, now: Now) -> list[EventOut]:
    return await events.list_public(sm, now)


@router.get("/{event_id}")
async def get_event(event_id: uuid.UUID, sm: SessionMaker) -> EventOut:
    return await events.get_event(sm, event_id)


def _message(result: registration.RegisterResult) -> str:
    reg = result.registration
    if not result.created:
        return f"You're already registered ({reg.status.value}). Check {reg.email} for details."
    if reg.status == RegistrationStatus.confirmed:
        return f"You're in! Your ticket was sent to {reg.email}."
    return (
        f"The event is full. You're #{result.waitlist_position} on the waitlist; "
        f"we'll email {reg.email} if a seat frees up."
    )


@router.post("/{event_id}/registrations", status_code=status.HTTP_201_CREATED)
async def register(
    event_id: uuid.UUID,
    body: RegisterIn,
    sm: SessionMaker,
    now: Now,
    settings: AppSettings,
    response: Response,
) -> RegisterOut:
    result = await registration.register(sm, event_id, body.email, now, settings)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    # Deliberately no ticket code / manage token here: they go by email only (D-012).
    return RegisterOut(
        created=result.created,
        status=result.registration.status,
        waitlist_position=result.waitlist_position,
        email=result.registration.email,
        message=_message(result),
    )
