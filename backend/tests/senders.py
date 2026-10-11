"""Fault-injecting SMTP senders for dispatcher tests. They wrap the REAL SmtpSender (Mailpit);
failures are either real network failures (closed port) or simulated process death."""

from email.message import EmailMessage

from app.emails.smtp import Sender, SmtpSender

# Port 1 on localhost: nothing listens, so connecting fails for real (ConnectionRefused).
DEAD_SMTP = SmtpSender("127.0.0.1", 1, timeout=2)


class SimulatedCrash(BaseException):
    """Stands in for the worker process dying (kill -9, OOM, power loss). It derives from
    BaseException, so the dispatcher's `except Exception` does not handle it, exactly like
    a real crash: nothing after this point runs."""


class CrashBeforeSend:
    """Delivers `succeed` messages, then 'dies' just before handing the next one to SMTP."""

    def __init__(self, inner: Sender, succeed: int) -> None:
        self.inner = inner
        self.left = succeed

    async def send(self, message: EmailMessage) -> None:
        if self.left == 0:
            raise SimulatedCrash
        self.left -= 1
        await self.inner.send(message)


class CrashAfterSmtpAccept:
    """SMTP server accepts the message, then the worker 'dies' before recording it as sent:
    the one window in which at-least-once delivery produces a duplicate."""

    def __init__(self, inner: Sender) -> None:
        self.inner = inner

    async def send(self, message: EmailMessage) -> None:
        await self.inner.send(message)
        raise SimulatedCrash


class FailFirst:
    """First `failures` attempts hit a dead SMTP port (real error), then deliver for real."""

    def __init__(self, inner: Sender, failures: int) -> None:
        self.inner = inner
        self.failures_left = failures

    async def send(self, message: EmailMessage) -> None:
        if self.failures_left:
            self.failures_left -= 1
            await DEAD_SMTP.send(message)
        await self.inner.send(message)
