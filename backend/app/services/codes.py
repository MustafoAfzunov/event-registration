"""Ticket codes and manage tokens (DECISIONS D-013, D-012).

Ticket code: 8 symbols of Crockford base32 from the OS CSPRNG (`secrets`) = 40 bits.
Uniqueness is guaranteed by the DB unique constraint plus retry on collision; the code is
not a credential (check-in requires organizer login, and codes are scoped per event)."""

import secrets

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # no I, L, O, U
CODE_LENGTH = 8
_CONFUSABLE = str.maketrans({"O": "0", "I": "1", "L": "1"})


def new_ticket_code() -> str:
    return "".join(secrets.choice(CROCKFORD) for _ in range(CODE_LENGTH))


def format_ticket_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def normalize_ticket_input(raw: str) -> str | None:
    """'abcd efgh', 'ABCD-EFGH', 'abcd-efgo' -> canonical code, or None if malformed."""
    cleaned = "".join(ch for ch in raw.upper() if ch not in " -\t").translate(_CONFUSABLE)
    if len(cleaned) != CODE_LENGTH or any(ch not in CROCKFORD for ch in cleaned):
        return None
    return cleaned


def new_manage_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits, 43 url-safe chars
