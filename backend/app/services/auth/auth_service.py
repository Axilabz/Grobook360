"""Sign-in authentication (PROMPT-003).

Resolves user by phone (FRD FR-SI-01: phone + password, not email/username),
verifies the password server-side, validates account status, resolves role and
effective permissions, and issues a session. Tenant context is derived only
from the resolved user row — never trusted from the request.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import AUTH_ACCOUNT_INACTIVE, AUTH_INVALID_CREDENTIALS
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import verify_password
from app.db.base import utcnow
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit.audit_service import AuditService
from app.services.auth.permission_resolution import resolve_role_and_permissions
from app.services.auth.session_service import SessionService

logger = logging.getLogger("app.auth")


@dataclass(frozen=True)
class LoginResult:
    token: str
    user: User
    tenant: Tenant | None
    role_name: str | None
    permissions: list[str]


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _resolve_user(self, phone: str) -> User | None:
        result = await self._session.execute(select(User).where(User.phone == phone))
        matches = result.scalars().all()

        if len(matches) == 0:
            return None
        if len(matches) > 1:
            # Direct consequence of API-OD-03 (phone uniqueness scope) being
            # still open — see PROMPT-003-NOTES.md. Never guess; refuse.
            logger.warning(
                "Ambiguous login identifier: multiple active accounts share this phone",
                extra={"extra_fields": {"phone_last4": phone[-4:]}},
            )
            return None
        return matches[0]

    async def _resolve_role_and_permissions(self, user: User) -> tuple[str | None, list[str]]:
        return await resolve_role_and_permissions(self._session, user=user)

    async def _audit(self, *, user: User, action: str, after: dict | None, ip_address: str | None, device_info: str | None) -> None:
        # audit_log.tenant_id is a NOT NULL FK to tenant.id. A tenant-less user
        # (platform administrator) has no tenant to attach the record to — no
        # platform-level audit sink exists yet (that belongs to FRD Module 11,
        # out of this prompt's scope). Skip rather than write a bogus tenant_id.
        if user.tenant_id is None:
            logger.info(
                "Skipping audit record for tenant-less user (no platform audit sink yet)",
                extra={"extra_fields": {"action": action, "user_id": str(user.id)}},
            )
            return
        await AuditService(self._session).record(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            action=action,
            entity_type="user",
            entity_id=user.id,
            after=after,
            ip_address=ip_address,
            device_info=device_info,
        )

    async def authenticate(
        self,
        *,
        phone: str,
        password: str,
        ip_address: str | None,
        device_info: str | None,
    ) -> LoginResult:
        user = await self._resolve_user(phone)

        if user is None or not verify_password(password, user.password_hash):
            if user is not None:
                await self._audit(
                    user=user,
                    action="LOGIN_FAILED",
                    after={"reason": "invalid_credentials"},
                    ip_address=ip_address,
                    device_info=device_info,
                )
            raise AuthenticationError("Invalid login credentials", code=AUTH_INVALID_CREDENTIALS)

        if user.status != "ACTIVE":
            await self._audit(
                user=user,
                action="LOGIN_FAILED",
                after={"reason": "account_inactive", "status": user.status},
                ip_address=ip_address,
                device_info=device_info,
            )
            raise AuthorizationError(
                "Your account is inactive. Contact your administrator.", code=AUTH_ACCOUNT_INACTIVE
            )

        role_name, permissions = await self._resolve_role_and_permissions(user)

        tenant: Tenant | None = None
        if user.tenant_id:
            tenant_result = await self._session.execute(select(Tenant).where(Tenant.id == user.tenant_id))
            tenant = tenant_result.scalar_one_or_none()

        session_service = SessionService(self._session)
        token, _record = await session_service.issue(
            user_id=user.id,
            tenant_id=user.tenant_id,
            extra_claims={
                "tenant_id": str(user.tenant_id) if user.tenant_id else None,
                "role": role_name,
                # Permissions are deliberately NOT embedded here — see
                # app.services.auth.permission_resolution's own docstring:
                # Owner/Manager's now-100+-code permission set makes the
                # resulting Set-Cookie header exceed the 4096-byte browser
                # cookie limit, causing a silently-dropped cookie and an
                # unexplained "stuck on sign-in" symptom. get_current_user()
                # resolves the current permission set fresh, per request.
            },
            ip_address=ip_address,
            device_info=device_info,
        )

        user.last_login_at = utcnow()

        await self._audit(user=user, action="LOGIN_SUCCESS", after=None, ip_address=ip_address, device_info=device_info)

        return LoginResult(token=token, user=user, tenant=tenant, role_name=role_name, permissions=permissions)
