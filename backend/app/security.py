"""Organizer authentication: shared password -> signed, httpOnly, SameSite=Strict cookie
(DECISIONS D-011). Participants never use this; they hold capability links (D-012)."""

import hmac

from fastapi import Request, Response
from itsdangerous import BadSignature, TimestampSigner

from app.config import Settings
from app.errors import DomainError

COOKIE_NAME = "eventreg_admin"
_SALT = "organizer-session"
_PAYLOAD = b"organizer"


def _signer(settings: Settings) -> TimestampSigner:
    return TimestampSigner(settings.session_secret, salt=_SALT)


def password_matches(given: str, settings: Settings) -> bool:
    return hmac.compare_digest(given.encode(), settings.organizer_password.encode())


def set_session_cookie(response: Response, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        _signer(settings).sign(_PAYLOAD).decode(),
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        path="/api",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        COOKIE_NAME, path="/api", httponly=True, samesite="strict", secure=settings.cookie_secure
    )


def is_organizer(request: Request) -> bool:
    settings: Settings = request.app.state.settings
    value = request.cookies.get(COOKIE_NAME)
    if not value:
        return False
    try:
        payload = _signer(settings).unsign(value, max_age=settings.session_max_age_seconds)
    except BadSignature:  # includes SignatureExpired
        return False
    return hmac.compare_digest(payload, _PAYLOAD)


async def require_organizer(request: Request) -> None:
    if not is_organizer(request):
        raise DomainError("unauthorized", "Organizer login required.", status=401)
