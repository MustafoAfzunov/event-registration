from fastapi import APIRouter

from app.api.deps import AppSettings, Now, SessionMaker
from app.models import RegistrationStatus
from app.schemas import CancelOut, RegistrationOut
from app.services import registration
from app.services.codes import format_ticket_code
from app.services.events import event_out
from app.services.seats import waitlist_position

router = APIRouter(prefix="/api/registrations", tags=["participant"])

_HAS_TICKET = {RegistrationStatus.confirmed, RegistrationStatus.checked_in}


@router.get("/{manage_token}")
async def get_registration(manage_token: str, sm: SessionMaker) -> RegistrationOut:
    async with sm() as session:
        reg = await registration.get_by_token(session, manage_token)
        return RegistrationOut(
            event=await event_out(session, reg.event_id),
            email=reg.email,
            status=reg.status,
            ticket_code=format_ticket_code(reg.ticket_code) if reg.status in _HAS_TICKET else None,
            waitlist_position=await waitlist_position(session, reg),
            checked_in_at=reg.checked_in_at,
        )


@router.post("/{manage_token}/cancel")
async def cancel(manage_token: str, sm: SessionMaker, now: Now, settings: AppSettings) -> CancelOut:
    reg = await registration.cancel(sm, manage_token, now, settings)
    return CancelOut(status=reg.status)
