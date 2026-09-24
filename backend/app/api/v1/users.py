"""Tenant User Management endpoints (PROMPT-005, authorization migrated to
permission codes by PROMPT-006).

Authorization is now permission-code-based (require_permission), backed by
the real role_permission catalogue PROMPT-006 populates — completing the
migration flagged in PROMPT-005-NOTES.md ("migrate to require_permission
once PROMPT-006 lands"). The actual access pattern is unchanged: Owner has
users.create/update/activate/deactivate; Owner+Manager have users.view;
Salesperson has nothing (its role_permission set is empty).
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.exceptions import AuthorizationError
from app.core.permissions import USERS_ACTIVATE, USERS_CREATE, USERS_DEACTIVATE, USERS_UPDATE, USERS_VIEW
from app.db.session import get_db_session
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.envelopes import Pagination
from app.schemas.user_management import (
    ActivateDeactivateRequest,
    CreateUserRequest,
    UpdateUserRequest,
    UserDetail,
    UserListItem,
)
from app.services.user_management.user_service import UserManagementService

router = APIRouter(prefix="/users", tags=["users"])


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


def _to_list_item(user: User, role_name: str | None) -> UserListItem:
    return UserListItem(
        id=str(user.id),
        name=user.name,
        phone=user.phone,
        email=user.email,
        role=role_name,
        status=user.status,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
        row_version=user.row_version,
    )


def _to_detail(user: User, role_name: str | None) -> UserDetail:
    return UserDetail(**_to_list_item(user, role_name).model_dump())


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    # Platform Administrator has no tenant_id — this router is tenant-scoped
    # user management only, structurally unreachable for platform accounts.
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


@router.get("")
async def list_users(
    request: Request,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    role: str | None = None,
    status: str | None = None,
    context: AuthenticatedContext = Depends(require_permission(USERS_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)

    service = UserManagementService(session)
    result = await service.list_users(
        tenant_id=tenant_id, page=page, page_size=page_size, search=search, role_filter=role, status_filter=status
    )

    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(u, r).model_dump() for u, r in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(USERS_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = UserManagementService(session)
    user, role_name = await service.get_user(tenant_id=tenant_id, user_id=user_id)
    return {"data": _to_detail(user, role_name).model_dump(), "meta": _meta()}


@router.post("", status_code=201)
async def create_user(
    request: Request,
    payload: CreateUserRequest,
    context: AuthenticatedContext = Depends(require_permission(USERS_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = UserManagementService(session)
    user, role_name = await service.create_user(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
        role=payload.role,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_detail(user, role_name).model_dump(), "meta": _meta()}


@router.patch("/{user_id}")
async def update_user(
    request: Request,
    user_id: uuid.UUID,
    payload: UpdateUserRequest,
    context: AuthenticatedContext = Depends(require_permission(USERS_UPDATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = UserManagementService(session)
    user, role_name = await service.update_user(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        user_id=user_id,
        name=payload.name,
        email=payload.email,
        role=payload.role,
        expected_row_version=payload.expected_row_version,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_detail(user, role_name).model_dump(), "meta": _meta()}


@router.post("/{user_id}/activate")
async def activate_user(
    request: Request,
    user_id: uuid.UUID,
    payload: ActivateDeactivateRequest,
    context: AuthenticatedContext = Depends(require_permission(USERS_ACTIVATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = UserManagementService(session)
    user, role_name = await service.activate_user(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        user_id=user_id,
        expected_row_version=payload.expected_row_version,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_detail(user, role_name).model_dump(), "meta": _meta()}


@router.post("/{user_id}/deactivate")
async def deactivate_user(
    request: Request,
    user_id: uuid.UUID,
    payload: ActivateDeactivateRequest,
    context: AuthenticatedContext = Depends(require_permission(USERS_DEACTIVATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = UserManagementService(session)
    user, role_name = await service.deactivate_user(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        user_id=user_id,
        expected_row_version=payload.expected_row_version,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_detail(user, role_name).model_dump(), "meta": _meta()}
