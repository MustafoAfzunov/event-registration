import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.config import Settings, get_settings
from app.db import make_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # The engine is created eagerly (it connects lazily) so the app works even when the
    # ASGI lifespan is not run, e.g. under httpx.ASGITransport in tests.
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(title="Event Registration API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.include_router(health.router)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
