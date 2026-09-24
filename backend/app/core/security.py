"""Reusable security primitives: password hashing and JWT encode/decode.

No login/authentication endpoint is implemented here — that is PROMPT-002 per the
task boundary. This module only provides the infrastructure future auth code will
use, plus the dependency contracts (get_current_user / require_permission) that
downstream routers can rely on once PROMPT-002 fills in real session issuance.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _pwd_context.verify(plain_password, password_hash)


def generate_reset_token() -> str:
    """256-bit, URL-safe, cryptographically secure — PROMPT-004 S10.
    Never a sequential ID, timestamp, or user ID."""
    return secrets.token_urlsafe(32)


def hash_reset_token(raw_token: str) -> str:
    """SHA-256 digest of the raw token (PROMPT-004 S10: store a digest, not the
    raw value). A fast hash is appropriate here — unlike a password, the
    token's security comes entirely from its 256 bits of randomness, not from
    hash slowness, so bcrypt-style stretching would add cost with no benefit."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_access_token(
    subject: str, extra_claims: dict[str, Any] | None = None
) -> tuple[str, uuid.UUID, datetime]:
    """Returns (token, jti, expires_at). jti backs server-side revocation
    (app.models.auth_session) since the JWT itself is stateless (PROMPT-003 S12).
    """
    settings = get_settings()
    jti = uuid.uuid4()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "exp": expire, "jti": str(jti)}
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, jti, expire


def decode_access_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
