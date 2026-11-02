"""Standard error envelope shared by the gateway and every service.

Shape is identical to the monolith's (app.core.error_handlers) so the
frontend sees ONE error contract regardless of which process answered:
    {"error": {"code", "message", "details": []}, "meta": {"correlation_id"}}
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from shared.middleware.correlation import get_correlation_id

logger = logging.getLogger("shared.errors")

_CODE_MAP = {
    401: "AUTHENTICATION_ERROR",
    403: "AUTHORIZATION_ERROR",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    429: "RATE_LIMITED",
}


class ServiceError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        self.headers = headers


def error_envelope(code: str, message: str, details: list | None = None) -> dict:
    return {
        "error": {"code": code, "message": message, "details": details or []},
        "meta": {"correlation_id": get_correlation_id()},
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def _service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            error_envelope(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "code": e["type"], "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(error_envelope("VALIDATION_ERROR", "Request validation failed", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            error_envelope(_CODE_MAP.get(exc.status_code, "HTTP_ERROR"), message), status_code=exc.status_code
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception", exc_info=True)
        return JSONResponse(error_envelope("INTERNAL_ERROR", "An unexpected error occurred"), status_code=500)
