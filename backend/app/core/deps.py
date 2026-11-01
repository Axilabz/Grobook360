"""Authentication/authorization dependency contracts.

Completes PROMPT-001's scaffold (PROMPT-003): resolves the authenticated user
from either the httpOnly session cookie (browser transport — see
PROMPT-003-NOTES.md for why cookie over localStorage) or a Bearer header (API
clients), decodes+verifies the JWT, and checks the token's jti against
app.models.auth_session so a revoked/logged-out token is rejected even though
the JWT itself would still decode successfully before its natural expiry.
"""

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.error_codes import AUTH_SESSION_INVALID, AUTH_UNAUTHENTICATED
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import decode_access_token
from app.db.session import get_db_session
from app.db.tenant_context import set_tenant_context
from app.services.audit.audit_service import AuditService
from app.services.auth.permission_resolution import resolve_permissions_by_role_name
from app.services.auth.session_service import SessionService


@dataclass(frozen=True)
class AuthenticatedContext:
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: str | None
    permissions: frozenset[str]


def _extract_token(request: Request, authorization: str | None) -> str | None:
    settings = get_settings()
    cookie_token = request.cookies.get(settings.auth_cookie_name)
    if cookie_token:
        return cookie_token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1]
    return None


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> AuthenticatedContext:
    """Resolve the authenticated user/tenant context server-side.

    Tenant context here is NEVER taken from the request body or query string
    (PROMPT-001 S5) — only from the verified, non-revoked token.
    """
    token = _extract_token(request, authorization)
    if token is None:
        raise AuthenticationError("Not authenticated", code=AUTH_UNAUTHENTICATED)

    claims = decode_access_token(token)
    if claims is None:
        raise AuthenticationError("Invalid or expired session", code=AUTH_SESSION_INVALID)

    jti = uuid.UUID(claims["jti"]) if claims.get("jti") else None
    if jti is None:
        raise AuthenticationError("Invalid session token", code=AUTH_SESSION_INVALID)

    session_service = SessionService(session)
    active = await session_service.get_active(jti)
    if active is None:
        raise AuthenticationError("Session has been signed out or expired", code=AUTH_SESSION_INVALID)

    await session_service.touch(active)

    tenant_id = uuid.UUID(claims["tenant_id"]) if claims.get("tenant_id") else None
    role = claims.get("role")
    permissions = await resolve_permissions_by_role_name(session, tenant_id=tenant_id, role_name=role)
    context = AuthenticatedContext(
        user_id=uuid.UUID(claims["sub"]),
        tenant_id=tenant_id,
        role=role,
        permissions=permissions,
    )

    # Second line of defense: propagate tenant context into the DB session for RLS.
    await set_tenant_context(session, context.tenant_id)

    return context


def require_permission(permission_code: str):
    """Dependency factory enforcing a single required permission (API Contract S15).

    RBAC Alignment Phase: a denied check is now also audited (append-only
    audit_log, via the existing AuditService — no new audit infrastructure)
    before the 403 is raised, mirroring the LOGIN_FAILED-audit-then-raise
    convention already used in app/api/v1/auth.py. The audit insert is
    committed on its own, independent of whatever the rest of the request's
    session was doing, since the request is about to be rejected and the
    session otherwise closes without committing.
    """

    async def _check(
        request: Request,
        context: AuthenticatedContext = Depends(get_current_user),
        session: AsyncSession = Depends(get_db_session),
    ) -> AuthenticatedContext:
        if permission_code not in context.permissions:
            if context.tenant_id is not None:
                await AuditService(session).record(
                    tenant_id=context.tenant_id,
                    actor_user_id=context.user_id,
                    action="PERMISSION_DENIED",
                    entity_type="authorization",
                    entity_id=None,
                    after={"permission_code": permission_code, "path": request.url.path, "method": request.method},
                )
                await session.commit()
            raise AuthorizationError(f"Missing required permission: {permission_code}")
        return context

    return _check


def require_role(*allowed_roles: str):
    """Dependency factory enforcing role membership directly (PROMPT-005).

    Superseded by require_permission() for endpoints whose permission codes
    exist in the catalogue (PROMPT-006 populated role_permission for the
    users.*/roles.*/permissions.* surface — see app.core.permissions and
    PROMPT-006-NOTES.md). Kept available for any future platform-scope check
    that isn't naturally expressed as a tenant permission code.
    """

    async def _check(context: AuthenticatedContext = Depends(get_current_user)) -> AuthenticatedContext:
        if context.role not in allowed_roles:
            raise AuthorizationError("You do not have permission to perform this action.")
        return context

    return _check
