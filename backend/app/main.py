import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import admin, events, health, registrations, stream
from app.clock import Clock, SystemClock
from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.errors import install_error_handlers
from app.live.broker import Broker


class WorkerPidHeader:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.header = (b"x-backend-pid", str(os.getpid()).encode())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_pid(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), self.header]
            await send(message)

        await self.app(scope, receive, send_with_pid)


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()
    # The engine is created eagerly (it connects lazily) so the app works even when the
    # ASGI lifespan is not run, e.g. under httpx.ASGITransport in tests.
    engine = make_engine(settings.database_url, settings.db_pool_size, settings.db_max_overflow)

    broker = Broker(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await broker.stop()
        await engine.dispose()

    app = FastAPI(title="Event Registration API", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.clock = clock or SystemClock()
    app.state.broker = broker
    install_error_handlers(app)

    if settings.app_env != "production":
        # Which worker process answered; lets tests prove cross-worker fan-out. Pure ASGI
        # (not BaseHTTPMiddleware), so streaming responses and disconnects are unaffected.
        app.add_middleware(WorkerPidHeader)

    app.include_router(health.router)
    app.include_router(admin.public)
    app.include_router(admin.router)
    app.include_router(events.router)
    app.include_router(registrations.router)
    app.include_router(stream.public)
    app.include_router(stream.organizer)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def __getattr__(name: str) -> FastAPI:
    # `uvicorn app.main:app` builds the app lazily, so importing app.main (e.g. in tests)
    # does not require production settings to be present in the environment.
    if name == "app":
        return create_app()
    raise AttributeError(name)
