"""Gateway-side authentication check (only active when AUTH_MODE=verify)."""

from fastapi import Request

from app.core.config import GatewaySettings
from shared.exceptions import ServiceError
from shared.security import TokenClaims, extract_token, verify_access_token

# Paths (relative to /api/v1) reachable without a session. Mirrors the
# monolith's unauthenticated endpoints; the monolith still decides for itself.
PUBLIC_PATHS = frozenset(
    {
        "auth/sign-up",
        "auth/login",
        "auth/logout",
        "auth/session-status",
        "auth/forgot-password",
        "auth/reset-password",
        "auth/reset-password/validate",
        "health",
        "health/db",
        "version",
    }
)


def is_public(relative_path: str) -> bool:
    return relative_path.strip("/") in PUBLIC_PATHS


def authenticate(request: Request, relative_path: str, settings: GatewaySettings) -> TokenClaims | None:
    """Return verified claims, None for public paths, or raise 401.

    Only called in verify mode. Tenant identity comes from the signed token,
    never from any client-supplied header/parameter.
    """
    if is_public(relative_path):
        return None
    if not settings.jwt_secret_key:
        raise ServiceError(500, "GATEWAY_MISCONFIGURED", "Gateway auth is enabled but JWT_SECRET_KEY is not set")
    token = extract_token(request.cookies, request.headers.get("authorization"), settings.auth_cookie_name)
    if token is None:
        raise ServiceError(401, "AUTH_UNAUTHENTICATED", "Not authenticated")
    claims = verify_access_token(token, settings.jwt_secret_key, settings.jwt_algorithm)
    if claims is None:
        raise ServiceError(401, "AUTH_SESSION_INVALID", "Invalid or expired session")
    return claims
