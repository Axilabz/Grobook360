"""Centralized application exception hierarchy.

Separates the error categories required by PROMPT-001 S8: validation, authentication,
authorization, not-found, duplicate/conflict, concurrency, external-service and
unexpected system errors. Each maps to a stable error code and HTTP status; handlers
in app.core.error_handlers translate these into the standard error envelope and never
leak stack traces, secrets or internal details to the client.
"""

from typing import Any


class AppError(Exception):
    """Base class for all deliberately-raised application errors."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str,
        details: list[dict[str, Any]] | None = None,
        code: str | None = None,
    ) -> None:
        self.message = message
        self.details = details or []
        if code is not None:
            self.error_code = code
        super().__init__(message)


class ValidationAppError(AppError):
    status_code = 422
    error_code = "VALIDATION_ERROR"


class BadRequestError(AppError):
    status_code = 400
    error_code = "BAD_REQUEST"


class AuthenticationError(AppError):
    status_code = 401
    error_code = "AUTHENTICATION_ERROR"


class AuthorizationError(AppError):
    status_code = 403
    error_code = "AUTHORIZATION_ERROR"


class NotFoundError(AppError):
    status_code = 404
    error_code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    error_code = "CONFLICT"


class ConcurrencyConflictError(AppError):
    status_code = 412
    error_code = "CONCURRENCY_CONFLICT"


class RateLimitedError(AppError):
    status_code = 429
    error_code = "RATE_LIMITED"


class ExternalServiceError(AppError):
    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"


class ServiceUnavailableError(AppError):
    status_code = 503
    error_code = "SERVICE_UNAVAILABLE"
