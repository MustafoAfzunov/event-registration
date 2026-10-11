import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

router = APIRouter()


async def _probe_db(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def health(request: Request) -> JSONResponse:
    engine: AsyncEngine = request.app.state.engine
    timeout: float = request.app.state.settings.health_db_timeout_seconds
    try:
        async with asyncio.timeout(timeout):
            await _probe_db(engine)
    except Exception:  # any failure (refused, timeout, auth) means "db unhealthy"
        logger.warning("health check: database unreachable", exc_info=True)
        return JSONResponse({"status": "degraded", "db": "error"}, status_code=503)
    return JSONResponse({"status": "ok", "db": "ok"})


# /api/health is the documented contract (docs/API.md); /health is a convenience alias
# for container healthchecks and direct probing (DECISIONS D-021).
router.add_api_route("/api/health", health, methods=["GET"], tags=["health"])
router.add_api_route("/health", health, methods=["GET"], tags=["health"], include_in_schema=False)
