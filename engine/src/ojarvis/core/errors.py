"""Erreurs normalisées : même forme JSON pour toutes les réponses en échec."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ojarvis.core.context import current_correlation_id
from ojarvis.core.logs import get_logger

log = get_logger(__name__)


class EngineError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}


class NotFoundError(EngineError):
    status_code = 404
    code = "not_found"


class InvalidInputError(EngineError):
    status_code = 422
    code = "invalid_input"


class UnauthorizedError(EngineError):
    status_code = 401
    code = "unauthorized"


class ConflictError(EngineError):
    status_code = 409
    code = "conflict"


class UpstreamError(EngineError):
    status_code = 502
    code = "upstream_error"


class UnavailableError(EngineError):
    status_code = 503
    code = "unavailable"


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "correlation_id": current_correlation_id(),
        }
    }


_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "invalid_input",
    429: "rate_limited",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(EngineError)
    async def _engine_error(_: Request, exc: EngineError) -> JSONResponse:
        if exc.status_code >= 500:
            log.error("engine_error", code=exc.code, message=exc.message)
        return JSONResponse(error_body(exc.code, exc.message, exc.details), exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        return JSONResponse(error_body(code, str(exc.detail)), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"loc": [str(part) for part in err.get("loc", ())], "msg": err.get("msg", "")}
            for err in exc.errors()
        ]
        return JSONResponse(
            error_body("invalid_input", "Requête invalide.", {"fields": fields}), 422
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unexpected_error", error_type=type(exc).__name__)
        return JSONResponse(error_body("internal_error", "Erreur interne du moteur."), 500)
