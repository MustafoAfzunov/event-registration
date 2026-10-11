"""SMTP delivery. The only place that talks to the mail server; used only by the worker."""

import hashlib
from email.message import EmailMessage
from email.utils import formatdate
from typing import Protocol

import aiosmtplib

MESSAGE_ID_DOMAIN = "eventreg.example.com"


class Sender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


def message_id(dedupe_key: str) -> str:
    """Deterministic Message-ID per outbox row: if the at-least-once window ever produces a
    second copy, it is recognisably the same message (DECISIONS D-007)."""
    digest = hashlib.sha256(dedupe_key.encode()).hexdigest()[:40]
    return f"<{digest}@{MESSAGE_ID_DOMAIN}>"


def build_message(
    *, mail_from: str, to: str, subject: str, body: str, dedupe_key: str
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = mail_from
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(usegmt=True)
    message["Message-ID"] = message_id(dedupe_key)
    message.set_content(body)
    return message


class SmtpSender:
    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    async def send(self, message: EmailMessage) -> None:
        # Mailpit speaks plain SMTP; a real provider would need TLS + auth settings here.
        await aiosmtplib.send(
            message,
            hostname=self.host,
            port=self.port,
            timeout=self.timeout,
            start_tls=False,
            use_tls=False,
        )
