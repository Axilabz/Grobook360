"""Read-only role/permission catalogue queries (PROMPT-006).

No create/update/delete here by design: custom roles and custom permissions
are explicitly NOT supported in this MVP (PROMPT-006 S12/S14) — this is a
read-only, system-defined catalogue.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permission import Permission
from app.models.role import Role
from app.models.role_permission import RolePermission
from app.models.user_role import UserRole


class RbacQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _permission_codes_for_role(self, role_id: uuid.UUID) -> list[str]:
        result = await self._session.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.code)
        )
        return [row[0] for row in result.all()]

    async def list_roles(self, tenant_id: uuid.UUID) -> list[tuple[Role, list[str], int]]:
        result = await self._session.execute(select(Role).where(Role.tenant_id == tenant_id).order_by(Role.name))
        roles = result.scalars().all()

        output: list[tuple[Role, list[str], int]] = []
        for role in roles:
            codes = await self._permission_codes_for_role(role.id)
            count_result = await self._session.execute(
                select(func.count(UserRole.id)).where(UserRole.role_id == role.id, UserRole.tenant_id == tenant_id)
            )
            output.append((role, codes, count_result.scalar_one()))
        return output

    async def get_role(self, tenant_id: uuid.UUID, role_id: uuid.UUID) -> tuple[Role, list[str], int] | None:
        result = await self._session.execute(select(Role).where(Role.id == role_id, Role.tenant_id == tenant_id))
        role = result.scalar_one_or_none()
        if role is None:
            return None
        codes = await self._permission_codes_for_role(role.id)
        count_result = await self._session.execute(
            select(func.count(UserRole.id)).where(UserRole.role_id == role.id, UserRole.tenant_id == tenant_id)
        )
        return role, codes, count_result.scalar_one()

    async def list_permissions(self) -> list[Permission]:
        result = await self._session.execute(select(Permission).order_by(Permission.code))
        return list(result.scalars().all())
