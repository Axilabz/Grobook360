"""Read-only Role/Permission catalogue endpoints (PROMPT-006).

Not in API Contract Specification v1.0's catalogue — added per this prompt's
own instruction (S31), following the same "add what's needed, flag it"
pattern as sign-up/forgot-password. No create/update/delete: custom roles and
permissions are explicitly out of MVP scope (S12/S14).
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.error_codes import USR_NOT_FOUND
from app.core.exceptions import NotFoundError
from app.core.permissions import ROLES_VIEW, PERMISSIONS_VIEW
from app.db.session import get_db_session
from app.schemas.rbac import PermissionItem, RoleDetail, RoleSummary
from app.services.rbac.rbac_query_service import RbacQueryService

router = APIRouter(tags=["rbac"])


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/roles")
async def list_roles(
    context: AuthenticatedContext = Depends(require_permission(ROLES_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    if context.tenant_id is None:
        return {"data": [], "meta": _meta()}

    service = RbacQueryService(session)
    roles = await service.list_roles(context.tenant_id)
    data = [
        RoleSummary(id=str(role.id), name=role.name, description=role.description, permissions=codes).model_dump()
        for role, codes, _count in roles
    ]
    return {"data": data, "meta": _meta()}


@router.get("/roles/{role_id}")
async def get_role(
    role_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(ROLES_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    if context.tenant_id is None:
        raise NotFoundError("Role not found", code=USR_NOT_FOUND)

    service = RbacQueryService(session)
    result = await service.get_role(context.tenant_id, role_id)
    if result is None:
        raise NotFoundError("Role not found", code=USR_NOT_FOUND)

    role, codes, user_count = result
    detail = RoleDetail(id=str(role.id), name=role.name, description=role.description, permissions=codes, user_count=user_count)
    return {"data": detail.model_dump(), "meta": _meta()}


@router.get("/roles/{role_id}/permissions")
async def get_role_permissions(
    role_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(ROLES_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    if context.tenant_id is None:
        raise NotFoundError("Role not found", code=USR_NOT_FOUND)

    service = RbacQueryService(session)
    result = await service.get_role(context.tenant_id, role_id)
    if result is None:
        raise NotFoundError("Role not found", code=USR_NOT_FOUND)

    _role, codes, _count = result
    return {"data": codes, "meta": _meta()}


@router.get("/permissions")
async def list_permissions(
    context: AuthenticatedContext = Depends(require_permission(PERMISSIONS_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    service = RbacQueryService(session)
    permissions = await service.list_permissions()
    data = [PermissionItem(id=str(p.id), code=p.code, description=p.description).model_dump() for p in permissions]
    return {"data": data, "meta": _meta()}
