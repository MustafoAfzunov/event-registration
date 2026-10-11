"""Background worker: `python -m app.worker`. Two loops in one process:
  * the outbox dispatcher (sends emails, phase 3);
  * the reminder scheduler (enqueues due reminders, phase 6).
Any number of worker processes may run at once (SKIP LOCKED + dedupe keys).

SIGTERM/SIGINT => graceful stop: the message being sent is finished and recorded, the rest
of the claimed batch is released immediately, then the process exits 0."""

import asyncio
import logging
import signal

from app.clock import SystemClock
from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.emails.dispatcher import Dispatcher
from app.emails.smtp import SmtpSender
from app.scheduler import Scheduler

logger = logging.getLogger("app.worker")


async def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url, pool_size=2, max_overflow=2)
    sender = SmtpSender(settings.smtp_host, settings.smtp_port, settings.smtp_timeout_seconds)
    sessionmaker = make_sessionmaker(engine)
    clock = SystemClock()
    dispatcher = Dispatcher(sessionmaker, sender, clock, settings)
    scheduler = Scheduler(sessionmaker, clock, settings)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    logger.info("worker started (smtp %s:%s)", settings.smtp_host, settings.smtp_port)
    try:
        await asyncio.gather(dispatcher.run(stop), scheduler.run(stop))
    finally:
        await engine.dispose()
        logger.info("worker stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(main())
