"""Server-side session issuance/validation/revocation (PROMPT-003 S12/S21/S22).

Backs PROMPT-001's stateless JWT with a minimal revocation record so logout is
real: the token remains cryptographically valid until its exp claim, but
get_current_user additionally checks this table and rejects a revoked jti.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.base import utcnow
from app.models.auth_session import AuthSession


class SessionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
        extra_claims: dict,
        ip_address: str | None,
        device_info: str | None,
    ) -> tuple[str, AuthSession]:
        token, jti, expires_at = create_access_token(subject=str(user_id), extra_claims=extra_claims)

        record = AuthSession(
            tenant_id=tenant_id,
            user_id=user_id,
            token_jti=jti,
            issued_at=utcnow(),
            expires_at=expires_at,
            last_activity_at=utcnow(),
            ip_address=ip_address,
            device_info=device_info,
        )
        self._session.add(record)
        await self._session.flush()
        return token, record

    async def get_active(self, jti: uuid.UUID) -> AuthSession | None:
        result = await self._session.execute(select(AuthSession).where(AuthSession.token_jti == jti))
        record = result.scalar_one_or_none()
        if record is None:
            return None
        if record.revoked_at is not None:
            return None
        if record.expires_at <= datetime.now(timezone.utc):
            return None
        return record

    async def revoke(self, jti: uuid.UUID) -> bool:
        result = await self._session.execute(select(AuthSession).where(AuthSession.token_jti == jti))
        record = result.scalar_one_or_none()
        if record is None or record.revoked_at is not None:
            return False
        record.revoked_at = utcnow()
        await self._session.flush()
        return True

    async def touch(self, record: AuthSession) -> None:
        record.last_activity_at = utcnow()
        await self._session.flush()
