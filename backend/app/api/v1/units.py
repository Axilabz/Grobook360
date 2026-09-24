"""Unit of Measure endpoints (PROMPT-009).

Gated by products.view/products.create — see app/core/permissions.py's
note on why Units has no dedicated permission family of its own.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.exceptions import AuthorizationError
from app.core.permissions import PRODUCTS_CREATE, PRODUCTS_VIEW
from app.db.session import get_db_session
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.unit_of_measure import CreateUnitOfMeasureRequest, UnitOfMeasureItem
from app.services.products.unit_service import UnitOfMeasureService

router = APIRouter(prefix="/units", tags=["units"])


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


def _to_item(unit: UnitOfMeasure) -> UnitOfMeasureItem:
    return UnitOfMeasureItem(id=str(unit.id), code=unit.code, name=unit.name, precision=unit.precision)


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


@router.get("")
async def list_units(
    context: AuthenticatedContext = Depends(require_permission(PRODUCTS_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = UnitOfMeasureService(session)
    units = await service.list_units(tenant_id=tenant_id)
    return {"data": [_to_item(u).model_dump() for u in units], "meta": _meta()}


@router.post("", status_code=201)
async def create_unit(
    request: Request,
    payload: CreateUnitOfMeasureRequest,
    context: AuthenticatedContext = Depends(require_permission(PRODUCTS_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = UnitOfMeasureService(session)
    unit = await service.create_unit(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        code=payload.code,
        name=payload.name,
        precision=payload.precision,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_item(unit).model_dump(), "meta": _meta()}
