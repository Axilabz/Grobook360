"""Inventory / Stock Ledger endpoints (PROMPT-010).

Mirrors the established router shape: permission-code authorization,
tenant context resolved server-side only. Opening stock, stock-in,
stock-out and adjustments are state-mutating "financial" operations (they
move inventory) and require an Idempotency-Key header, exactly like
sign-up (PROMPT-002) — protects against network-retry duplicate posting
(§15/§41/§42).
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.error_codes import REG_MISSING_FIELD
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import (
    INVENTORY_ADJUST,
    INVENTORY_OPENING_STOCK,
    INVENTORY_STOCK_IN,
    INVENTORY_STOCK_OUT,
    INVENTORY_VIEW,
)
from app.db.session import get_db_session
from app.models.product import Product
from app.models.stock_ledger_entry import StockLedgerEntry
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.envelopes import Pagination
from app.schemas.inventory import (
    AdjustmentRequest,
    AvailabilityResponse,
    InventoryListItem,
    OpeningStockRequest,
    StockInRequest,
    StockMovementItem,
    StockOutRequest,
    UnitRef,
)
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.inventory.inventory_service import InventoryService

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


def _to_unit_ref(unit: UnitOfMeasure) -> UnitRef:
    return UnitRef(id=str(unit.id), code=unit.code, name=unit.name)


def _to_list_item(product: Product, uom: UnitOfMeasure, last_movement_at) -> InventoryListItem:
    is_low = bool(product.reorder_level > 0 and product.stock_qty_cache <= product.reorder_level)
    return InventoryListItem(
        product_id=str(product.id),
        sku=product.sku,
        name=product.name,
        base_uom=_to_unit_ref(uom),
        current_stock=str(product.stock_qty_cache),
        reorder_level=str(product.reorder_level),
        is_low_stock=is_low,
        product_status=product.status,
        last_movement_at=last_movement_at.isoformat() if last_movement_at else None,
    )


def _to_movement_item(entry: StockLedgerEntry, uom: UnitOfMeasure) -> StockMovementItem:
    return StockMovementItem(
        id=str(entry.id),
        movement_type=entry.movement_type,
        quantity=str(entry.quantity),
        uom=_to_unit_ref(uom),
        base_quantity=str(entry.base_quantity),
        source_type=entry.source_type,
        source_id=str(entry.source_id),
        occurred_at=entry.occurred_at.isoformat(),
        created_by=str(entry.created_by) if entry.created_by else None,
    )


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    # Platform Administrator has no tenant_id — Inventory is "No" access for
    # Platform Admin (FRD Table 7), so this router is structurally
    # unreachable for platform accounts regardless.
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


async def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise BadRequestError(
            "Idempotency-Key header is required for this operation", code=REG_MISSING_FIELD
        )
    return idempotency_key


@router.get("")
async def list_inventory(
    request: Request,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    stock_status: str | None = None,
    context: AuthenticatedContext = Depends(require_permission(INVENTORY_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)

    service = InventoryService(session)
    result = await service.list_inventory(
        tenant_id=tenant_id, page=page, page_size=page_size, search=search, stock_status=stock_status
    )

    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(p, u, lm).model_dump() for p, u, lm in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/availability/{product_id}")
async def get_availability(
    product_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(INVENTORY_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = InventoryService(session)
    product, uom = await service.get_availability(tenant_id=tenant_id, product_id=product_id)
    body = AvailabilityResponse(
        product_id=str(product.id), available_quantity=str(product.stock_qty_cache), base_uom=_to_unit_ref(uom)
    )
    return {"data": body.model_dump(), "meta": _meta()}


@router.get("/{product_id}")
async def get_stock_detail(
    product_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(INVENTORY_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = InventoryService(session)
    product, uom = await service.get_availability(tenant_id=tenant_id, product_id=product_id)
    return {"data": _to_list_item(product, uom, None).model_dump(), "meta": _meta()}


@router.get("/{product_id}/movements")
async def list_movements(
    product_id: uuid.UUID,
    page: int = 1,
    page_size: int = 25,
    movement_type: str | None = None,
    context: AuthenticatedContext = Depends(require_permission(INVENTORY_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)

    service = InventoryService(session)
    items, total_items = await service.list_movements(
        tenant_id=tenant_id, product_id=product_id, page=page, page_size=page_size, movement_type=movement_type
    )

    total_pages = (total_items + page_size - 1) // page_size if total_items else 0
    data = []
    for entry, uom, running_balance in items:
        item = _to_movement_item(entry, uom).model_dump()
        item["running_balance"] = str(running_balance)
        data.append(item)

    return {
        "data": data,
        "pagination": Pagination(page=page, page_size=page_size, total_items=total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


async def _idempotent_post(
    *,
    session: AsyncSession,
    idempotency_key: str,
    endpoint: str,
    tenant_id: uuid.UUID,
    request_payload: dict,
    execute,
) -> dict:
    idempotency = IdempotencyService(session)
    check_result = await idempotency.check(idempotency_key=idempotency_key, endpoint=endpoint, payload=request_payload)
    if check_result.existing_response is not None:
        _, body = check_result.existing_response
        return body

    response_body = await execute()

    await idempotency.store(
        idempotency_key=idempotency_key,
        endpoint=endpoint,
        payload=request_payload,
        tenant_id=tenant_id,
        response_status=201,
        response_body=response_body,
    )
    await session.commit()
    return response_body


@router.post("/opening-stock", status_code=201)
async def create_opening_stock(
    request: Request,
    payload: OpeningStockRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(INVENTORY_OPENING_STOCK)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)
    client_ip = request.client.host if request.client else "unknown"
    service = InventoryService(session)

    async def _execute() -> dict:
        entry = await service.record_opening_stock(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            product_id=uuid.UUID(payload.product_id),
            quantity=payload.quantity,
            uom_id=uuid.UUID(payload.uom_id),
            ip_address=client_ip,
        )
        uom = await service.get_uom_or_raise(tenant_id, entry.uom_id)  # already validated; cheap re-fetch for response
        return {"data": _to_movement_item(entry, uom).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/inventory/opening-stock",
        tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"),
        execute=_execute,
    )


@router.post("/stock-in", status_code=201)
async def create_stock_in(
    request: Request,
    payload: StockInRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(INVENTORY_STOCK_IN)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)
    client_ip = request.client.host if request.client else "unknown"
    service = InventoryService(session)

    async def _execute() -> dict:
        entry = await service.record_stock_in(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            product_id=uuid.UUID(payload.product_id),
            quantity=payload.quantity,
            uom_id=uuid.UUID(payload.uom_id),
            notes=payload.notes,
            ip_address=client_ip,
        )
        uom = await service.get_uom_or_raise(tenant_id, entry.uom_id)
        return {"data": _to_movement_item(entry, uom).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/inventory/stock-in",
        tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"),
        execute=_execute,
    )


@router.post("/stock-out", status_code=201)
async def create_stock_out(
    request: Request,
    payload: StockOutRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(INVENTORY_STOCK_OUT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)
    client_ip = request.client.host if request.client else "unknown"
    service = InventoryService(session)

    async def _execute() -> dict:
        entry = await service.record_stock_out(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            product_id=uuid.UUID(payload.product_id),
            quantity=payload.quantity,
            uom_id=uuid.UUID(payload.uom_id),
            notes=payload.notes,
            ip_address=client_ip,
        )
        uom = await service.get_uom_or_raise(tenant_id, entry.uom_id)
        return {"data": _to_movement_item(entry, uom).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/inventory/stock-out",
        tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"),
        execute=_execute,
    )


@router.post("/adjustments", status_code=201)
async def create_adjustment(
    request: Request,
    payload: AdjustmentRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(INVENTORY_ADJUST)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)
    client_ip = request.client.host if request.client else "unknown"
    service = InventoryService(session)

    async def _execute() -> dict:
        entry, adjustment = await service.record_adjustment(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            product_id=uuid.UUID(payload.product_id),
            quantity=payload.quantity,
            uom_id=uuid.UUID(payload.uom_id),
            direction=payload.direction,
            reason=payload.reason,
            ip_address=client_ip,
        )
        uom = await service.get_uom_or_raise(tenant_id, entry.uom_id)
        body = _to_movement_item(entry, uom).model_dump()
        body["adjustment_number"] = adjustment.adjustment_number
        body["reason"] = adjustment.reason
        return {"data": body, "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/inventory/adjustments",
        tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"),
        execute=_execute,
    )
