"""Forgot-password / reset-password domain logic (PROMPT-004).

Anti-enumeration is structural here, not bolted on: request_reset() never
tells the caller whether a match was found — the route always returns the
same generic response regardless. Ambiguous email matches (>1 active user
sharing an email — the same open-decision consequence as PROMPT-002/003's
phone uniqueness) are treated identically to "not found": nothing is sent,
no error surfaces, per S24/S8.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import auth_cache
from app.core.config import get_settings
from app.core.error_codes import (
    RESET_INVALID_TOKEN,
    RESET_TOKEN_CONSUMED,
    RESET_TOKEN_EXPIRED,
    RESET_TOKEN_REVOKED,
)
from app.core.exceptions import AppError
from app.core.security import generate_reset_token, hash_password, hash_reset_token
from app.db.base import utcnow
from app.db.tenant_context import set_tenant_context
from app.models.auth_session import AuthSession
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.services.audit.audit_service import AuditService

logger = logging.getLogger("app.password_reset")


class ResetTokenError(AppError):
    status_code = 400


@dataclass(frozen=True)
class PendingReset:
    raw_token: str
    record: PasswordResetToken
    user: User


class PasswordResetService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _resolve_eligible_user(self, email: str) -> User | None:
        # Pre-tenant lookup via a narrow SECURITY DEFINER function (migration
        # 0038): returns (user_id, tenant_id) only, and nothing when the email
        # is unknown OR shared by several accounts (treated as not-found —
        # S24/S8 anti-enumeration). The user row itself is then read under
        # that tenant's RLS context.
        row = (
            await self._session.execute(
                text("SELECT user_id, tenant_id FROM public.auth_find_reset_user(:email)"), {"email": email}
            )
        ).first()
        if row is None:
            return None
        await set_tenant_context(self._session, row.tenant_id)
        user = (await self._session.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
        if user is None:
            return None
        # Disabled accounts are silently ineligible — same generic response
        # either way (S24). Password reset must never reactivate an account.
        if user.status != "ACTIVE":
            return None
        return user

    async def request_reset(self, *, email: str, ip_address: str | None) -> PendingReset | None:
        """Returns None when there is nothing to send (unknown/ambiguous/inactive
        account) — the caller must respond identically to the real-reset case."""
        user = await self._resolve_eligible_user(email)
        if user is None:
            return None

        # S19: a new request invalidates any previous unused tokens for this
        # user so an old leaked link can't remain valid indefinitely.
        existing = await self._session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.consumed_at.is_(None),
                PasswordResetToken.revoked_at.is_(None),
            )
        )
        for token_row in existing.scalars().all():
            token_row.revoked_at = utcnow()

        settings = get_settings()
        raw_token = generate_reset_token()
        record = PasswordResetToken(
            tenant_id=user.tenant_id,
            user_id=user.id,
            token_hash=hash_reset_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.password_reset_token_expire_minutes),
            request_ip=ip_address,
        )
        self._session.add(record)
        await self._session.flush()

        if user.tenant_id is not None:
            await AuditService(self._session).record(
                tenant_id=user.tenant_id,
                actor_user_id=user.id,
                action="AUTH_PASSWORD_RESET_REQUESTED",
                entity_type="user",
                entity_id=user.id,
                ip_address=ip_address,
            )

        return PendingReset(raw_token=raw_token, record=record, user=user)

    async def _audit_token_failure(self, record: PasswordResetToken, action: str, ip_address: str | None) -> None:
        if record.tenant_id is None:
            return
        await AuditService(self._session).record(
            tenant_id=record.tenant_id,
            actor_user_id=record.user_id,
            action=action,
            entity_type="password_reset_token",
            entity_id=record.id,
            ip_address=ip_address,
        )

    async def _load_valid_token(self, raw_token: str, *, ip_address: str | None = None) -> PasswordResetToken | None:
        token_hash = hash_reset_token(raw_token)
        # The token proves identity before any tenant is known; resolve it via
        # a narrow SECURITY DEFINER function (identifiers only, never the hash
        # or token), then read the record under that tenant's RLS context.
        row = (
            await self._session.execute(
                text("SELECT token_id, tenant_id FROM public.auth_find_reset_token(:h)"), {"h": token_hash}
            )
        ).first()
        if row is None:
            return None
        await set_tenant_context(self._session, row.tenant_id)
        record = (
            await self._session.execute(select(PasswordResetToken).where(PasswordResetToken.id == row.token_id))
        ).scalar_one_or_none()
        if record is None:
            return None
        if record.consumed_at is not None:
            await self._audit_token_failure(record, "AUTH_PASSWORD_RESET_TOKEN_REJECTED", ip_address)
            raise ResetTokenError("This password reset link has already been used.", code=RESET_TOKEN_CONSUMED)
        if record.revoked_at is not None:
            await self._audit_token_failure(record, "AUTH_PASSWORD_RESET_TOKEN_REJECTED", ip_address)
            raise ResetTokenError("This password reset link is no longer valid.", code=RESET_TOKEN_REVOKED)
        if record.expires_at <= datetime.now(timezone.utc):
            await self._audit_token_failure(record, "AUTH_PASSWORD_RESET_TOKEN_EXPIRED", ip_address)
            raise ResetTokenError("This password reset link has expired.", code=RESET_TOKEN_EXPIRED)
        return record

    async def validate_token(self, raw_token: str) -> bool:
        try:
            record = await self._load_valid_token(raw_token)
        except ResetTokenError:
            return False
        return record is not None

    async def reset_password(self, *, raw_token: str, new_password: str, ip_address: str | None) -> None:
        record = await self._load_valid_token(raw_token, ip_address=ip_address)
        if record is None:
            raise ResetTokenError("This password reset link is invalid.", code=RESET_INVALID_TOKEN)

        user_result = await self._session.execute(select(User).where(User.id == record.user_id))
        user = user_result.scalar_one()

        # Password reset changes ONLY the credential — never status, role, or
        # tenant (S25). No field but password_hash is touched on `user` here.
        user.password_hash = hash_password(new_password)
        record.consumed_at = utcnow()

        # S17: revoke every existing session for this user — the recommended
        # security behavior, not a silent "leave everything logged in".
        active_sessions = await self._session.execute(
            select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        )
        for session_row in active_sessions.scalars().all():
            session_row.revoked_at = utcnow()
            auth_cache.invalidate_all()

        if user.tenant_id is not None:
            await AuditService(self._session).record(
                tenant_id=user.tenant_id,
                actor_user_id=user.id,
                action="AUTH_PASSWORD_RESET_COMPLETED",
                entity_type="user",
                entity_id=user.id,
                ip_address=ip_address,
            )
