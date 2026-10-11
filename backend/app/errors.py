"""Domain errors and the single place that turns errors into the API error envelope:
{"error": {"code", "message", "details"}} (docs/API.md, Conventions)."""

from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.timefmt import iso_utc


class DomainError(Exception):
    """A business-rule outcome with a stable, machine-readable `code`."""

    def __init__(
        self, code: str, message: str, status: int = 409, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


def not_found(code: str, message: str) -> DomainError:
    return DomainError(code, message, status=404)


def constraint_name(exc: IntegrityError) -> str | None:
    """Name of the violated constraint (psycopg diagnostics), used to tell expected
    races (e.g. the active-email unique index) from real bugs."""
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _envelope(code: str, message: str, status: int, details: dict[str, Any]) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details}}
    # Same timestamp format as normal responses (UTC, 'Z').
    return JSONResponse(
        jsonable_encoder(body, custom_encoder={datetime: iso_utc}), status_code=status
    )


async def _domain_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return _envelope(exc.code, exc.message, exc.status, exc.details)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return _envelope("validation_error", "Request validation failed.", 422, {"fields": fields})


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = {401: "unauthorized", 404: "not_found", 405: "method_not_allowed"}.get(
        exc.status_code, "http_error"
    )
    return _envelope(code, str(exc.detail), exc.status_code, {})


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
