"""Shared role/permission lookup, used by both login (to populate the response
body) and every authenticated request (to resolve the CURRENT permission set
for the token's tenant_id/role) — see PROMPT-003/006-NOTES.md.

Permissions are deliberately NOT embedded in the JWT itself: Owner/Manager now
hold 100+ permission codes (accumulated across every module built since
PROMPT-006), and baking that list into a token claim produces a Set-Cookie
header that exceeds the 4096-byte cookie-size limit browsers (and standard
HTTP clients) enforce — the cookie is silently dropped, and the user appears
stuck on the sign-in screen with no visible server-side error. Resolving
permissions fresh, per request, from role_permission also means a permission
or role change takes effect immediately rather than only after the user's
next login.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permission import Permission
from app.models.role import Role
from app.models.role_permission import RolePermission
from app.models.user import User
from app.models.user_role import UserRole


async def resolve_role_and_permissions(
    session: AsyncSession, *, user: User
) -> tuple[str | None, list[str]]:
    """By user (used at login, when only the user row is in hand)."""
    if user.tenant_id is None:
        return None, []

    # ONE round trip: role + its permission codes joined (was two queries).
    rows = (
        await session.execute(
            select(Role.id, Role.name, Permission.code)
            .select_from(UserRole)
            .join(Role, Role.id == UserRole.role_id)
            .outerjoin(RolePermission, RolePermission.role_id == Role.id)
            .outerjoin(Permission, Permission.id == RolePermission.permission_id)
            .where(UserRole.user_id == user.id, UserRole.tenant_id == user.tenant_id)
            .order_by(Role.created_at, Role.id)
        )
    ).all()
    if not rows:
        return None, []

    first_role_id, first_role_name = rows[0][0], rows[0][1]
    return first_role_name, [code for role_id, _name, code in rows if role_id == first_role_id and code is not None]


async def resolve_permissions_by_role_name(
    session: AsyncSession, *, tenant_id: uuid.UUID | None, role_name: str | None
) -> frozenset[str]:
    """By (tenant_id, role name) — used on every authenticated request, since
    the JWT only carries the role NAME, never the permission list itself."""
    if tenant_id is None or role_name is None:
        return frozenset()

    # ONE round trip (role + permissions joined) - this runs on every request,
    # and each extra query costs a full network RTT to the hosted database.
    perm_result = await session.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .where(Role.tenant_id == tenant_id, Role.name == role_name)
    )
    return frozenset(row[0] for row in perm_result.all())


async def _permissions_for_role_id(session: AsyncSession, role_id: uuid.UUID) -> list[str]:
    perm_result = await session.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
    )
    return [row[0] for row in perm_result.all()]
