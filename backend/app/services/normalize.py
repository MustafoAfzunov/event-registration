"""Email normalization (DECISIONS D-014): trim, validate syntax (no DNS), lowercase the
whole address. Provider-specific folding (gmail dots, +tags) is deliberately NOT done."""

from email_validator import EmailNotValidError, validate_email

from app.errors import DomainError

MAX_EMAIL_LENGTH = 320


def _invalid() -> DomainError:
    return DomainError("invalid_email", "Please enter a valid email address.", status=422)


def normalize_email(raw: str) -> tuple[str, str]:
    """Return (display_email, normalized_email) or raise DomainError(invalid_email)."""
    display = raw.strip()
    # ASCII only: Python's and Postgres' lower() can disagree on non-ASCII letters, which
    # would break the lowercase CHECK constraint and the uniqueness rule (DECISIONS D-034).
    if not display or len(display) > MAX_EMAIL_LENGTH or not display.isascii():
        raise _invalid()
    try:
        validate_email(display, check_deliverability=False)
    except EmailNotValidError:
        raise _invalid() from None
    return display, display.lower()
