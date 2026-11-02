"""Stateless JWT verification (signature + expiry only).

This is deliberately NOT a replacement for the monolith's session check: the
`auth_session` table (server-side revocation) stays authoritative and is still
consulted by the backend on every authenticated request. A gateway that
verifies only the signature can reject garbage/expired tokens early, and can
derive the tenant from the TOKEN (never from client input), but it cannot know
that a still-valid token was revoked by logout.
"""

import uuid
from dataclasses import dataclass

from jose import JWTError, jwt

# Headers that carry trusted identity between gateway and services. A client
# must never be able to set these: the gateway strips them on ingress and only
# re-adds them from a verified token.
INTERNAL_IDENTITY_HEADERS = ("x-tenant-id", "x-user-id", "x-user-role", "x-internal-auth")


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: str | None
    jti: uuid.UUID | None


def extract_token(cookies: dict[str, str], authorization: str | None, cookie_name: str) -> str | None:
    cookie = cookies.get(cookie_name)
    if cookie:
        return cookie
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip() or None
    return None


def verify_access_token(token: str, secret: str, algorithm: str = "HS256") -> TokenClaims | None:
    try:
        claims = jwt.decode(token, secret, algorithms=[algorithm])
        tenant_raw = claims.get("tenant_id")
        jti_raw = claims.get("jti")
        return TokenClaims(
            user_id=uuid.UUID(claims["sub"]),
            tenant_id=uuid.UUID(tenant_raw) if tenant_raw else None,
            role=claims.get("role"),
            jti=uuid.UUID(jti_raw) if jti_raw else None,
        )
    except (JWTError, KeyError, ValueError):
        return None
