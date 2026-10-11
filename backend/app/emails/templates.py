"""Plain-text email bodies. Rendered at enqueue time and stored in email_outbox, so what was
sent is auditable and tests can assert on it (ARCHITECTURE 4.5). Never log these bodies:
they contain ticket codes and manage links."""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.codes import format_ticket_code


@dataclass(frozen=True)
class Rendered:
    subject: str
    body: str


def _when(starts_at: datetime) -> str:
    return starts_at.astimezone(UTC).strftime("%a, %d %b %Y %H:%M UTC")


def _manage(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/r/{token}"


def ticket(title: str, starts_at: datetime, code: str, base_url: str, token: str) -> Rendered:
    return Rendered(
        subject=f"Your ticket for {title}",
        body=(
            f'You\'re registered for "{title}" on {_when(starts_at)}.\n\n'
            f"Your ticket code: {format_ticket_code(code)}\n"
            "Show this code at the entrance.\n\n"
            f"View or cancel your registration: {_manage(base_url, token)}\n"
        ),
    )


def waitlisted(
    title: str, starts_at: datetime, position: int, base_url: str, token: str
) -> Rendered:
    return Rendered(
        subject=f"You're on the waitlist for {title}",
        body=(
            f'"{title}" on {_when(starts_at)} is currently full.\n\n'
            f"You are #{position} on the waitlist. If a seat frees up, it is given to the "
            "first person on the waitlist automatically and we will email you your ticket.\n\n"
            f"View or leave the waitlist: {_manage(base_url, token)}\n"
        ),
    )


def promoted(title: str, starts_at: datetime, code: str, base_url: str, token: str) -> Rendered:
    return Rendered(
        subject=f"A seat opened up: your ticket for {title}",
        body=(
            f'Good news: a seat opened up and it is yours. You\'re registered for "{title}" '
            f"on {_when(starts_at)}.\n\n"
            f"Your ticket code: {format_ticket_code(code)}\n"
            "Show this code at the entrance.\n\n"
            f"View or cancel your registration: {_manage(base_url, token)}\n"
        ),
    )


def cancelled(title: str, starts_at: datetime) -> Rendered:
    return Rendered(
        subject=f"Registration cancelled: {title}",
        body=(
            f'Your registration for "{title}" on {_when(starts_at)} has been cancelled.\n'
            "You can register again on the event page while registration is open.\n"
        ),
    )
