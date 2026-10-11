"""Enqueue = INSERT into email_outbox inside the caller's business transaction, deduplicated
by a deterministic key (ARCHITECTURE 4.5, DECISIONS D-007). Never send SMTP from here."""

import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.emails.templates import Rendered
from app.models import EmailKind, EmailOutbox


def dedupe_key(kind: EmailKind, registration_id: uuid.UUID) -> str:
    return f"{kind.value}:{registration_id}"


async def enqueue(
    session: AsyncSession,
    *,
    kind: EmailKind,
    key: str,
    event_id: uuid.UUID,
    registration_id: uuid.UUID | None,
    to_email: str,
    email: Rendered,
    now: datetime,
    schedule_version: int | None = None,
) -> bool:
    """Returns True if a new row was inserted, False if this key was already enqueued."""
    stmt = (
        insert(EmailOutbox)
        .values(
            kind=kind,
            dedupe_key=key,
            event_id=event_id,
            registration_id=registration_id,
            schedule_version=schedule_version,
            to_email=to_email,
            subject=email.subject,
            body_text=email.body,
            next_attempt_at=now,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        # RETURNING, not rowcount: through the ORM session this INSERT reports rowcount=-1
        # whether or not a row was written (D-070).
        .returning(EmailOutbox.id)
    )
    result = await session.execute(stmt)
    return result.first() is not None
