"""Role-permission seeding and read access (PROMPT-006).

seed_role_permissions() is called whenever a tenant's Role row is first
created (sign-up for OWNER — app.services.signup.signup_service; first
assignment for MANAGER/SALESPERSON — app.services.user_management.user_service)
so a brand-new role always starts with its approved default permission set.
Pre-existing roles (created before this prompt) are backfilled once by
migration 0007.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import ALL_PERMISSIONS, ROLE_DEFAULT_PERMISSIONS
from app.models.permission import Permission
from app.models.role_permission import RolePermission


async def get_or_create_permission(session: AsyncSession, code: str) -> Permission:
    result = await session.execute(select(Permission).where(Permission.code == code))
    permission = result.scalar_one_or_none()
    if permission is None:
        permission = Permission(code=code, description=ALL_PERMISSIONS.get(code, ""))
        session.add(permission)
        await session.flush()
    return permission


async def seed_role_permissions(session: AsyncSession, *, tenant_id: uuid.UUID, role_id: uuid.UUID, role_name: str) -> None:
    default_codes = ROLE_DEFAULT_PERMISSIONS.get(role_name, frozenset())
    for code in default_codes:
        permission = await get_or_create_permission(session, code)
        existing = await session.execute(
            select(RolePermission).where(RolePermission.role_id == role_id, RolePermission.permission_id == permission.id)
        )
        if existing.scalar_one_or_none() is None:
            session.add(RolePermission(tenant_id=tenant_id, role_id=role_id, permission_id=permission.id))
    await session.flush()
