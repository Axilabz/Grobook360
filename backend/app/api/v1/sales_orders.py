"""Sales Order endpoints (PROMPT-013).

Mirrors `sales_estimates.py`'s router shape exactly: thin router,
permission-code authorization, tenant context resolved server-side only.
Create and edit are NOT financial-idempotency-gated the same way
create/convert are — only truly duplicate-submission-sensitive operations
(create, and the estimate-conversion endpoint) require an Idempotency-Key,
matching the established PROMPT-002/010/012 pattern.
"""

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.error_codes import REG_MISSING_FIELD
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import (
    DELIVERY_CHALLAN_CREATE,
    SALES_ORDER_CANCEL,
    SALES_ORDER_CONFIRM,
    SALES_ORDER_CREATE,
    SALES_ORDER_EDIT,
    SALES_ORDER_VIEW,
)
from app.db.session import get_db_session
from app.models.sales_order import SalesOrder
from app.models.sales_order_line import SalesOrderLine
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.delivery_challan import DeliveryEligibility, DeliveryEligibilityLine
from app.schemas.envelopes import Pagination
from app.schemas.sales_estimate import UnitRef
from app.schemas.sales_order import (
    CreateSalesOrderRequest,
    SalesOrderActionRequest,
    SalesOrderDetail,
    SalesOrderLineItem,
    SalesOrderListItem,
    UpdateSalesOrderRequest,
)
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.sales.delivery_challan_service import DeliveryChallanService
from app.services.sales.sales_order_service import SalesOrderService

router = APIRouter(prefix="/sales/orders", tags=["sales-orders"])


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


async def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise BadRequestError("Idempotency-Key header is required for this operation", code=REG_MISSING_FIELD)
    return idempotency_key


def _to_unit_ref(unit: UnitOfMeasure) -> UnitRef:
    return UnitRef(id=str(unit.id), code=unit.code, name=unit.name)


def _to_list_item(order: SalesOrder, customer_name: str) -> SalesOrderListItem:
    return SalesOrderListItem(
        id=str(order.id),
        order_number=order.order_number,
        order_date=order.order_date.isoformat(),
        customer_id=str(order.customer_id),
        customer_name=customer_name,
        status=order.status,
        source_estimate_id=str(order.source_estimate_id) if order.source_estimate_id else None,
        grand_total=str(order.grand_total),
        created_by=str(order.created_by) if order.created_by else None,
        created_at=order.created_at.isoformat(),
        updated_at=order.updated_at.isoformat(),
        row_version=order.row_version,
    )


def _to_line_item(line: SalesOrderLine, uom: UnitOfMeasure) -> SalesOrderLineItem:
    return SalesOrderLineItem(
        id=str(line.id),
        line_no=line.line_no,
        product_id=str(line.product_id) if line.product_id else None,
        description=line.description,
        hsn_code=line.hsn_code,
        quantity=str(line.quantity),
        uom=_to_unit_ref(uom),
        unit_price=str(line.unit_price),
        discount_amount=str(line.discount_amount),
        taxable_amount=str(line.taxable_amount),
        gst_rate=str(line.gst_rate),
        cgst_amount=str(line.cgst_amount),
        sgst_amount=str(line.sgst_amount),
        igst_amount=str(line.igst_amount),
        line_total=str(line.line_total),
    )


def _to_detail(
    order: SalesOrder, customer_name: str, lines: list[tuple[SalesOrderLine, UnitOfMeasure]]
) -> SalesOrderDetail:
    return SalesOrderDetail(
        **_to_list_item(order, customer_name).model_dump(),
        customer_gstin=order.customer_gstin,
        billing_address=order.billing_address,
        shipping_address=order.shipping_address,
        place_of_supply_state_code=order.place_of_supply_state_code,
        subtotal=str(order.subtotal),
        discount_total=str(order.discount_total),
        taxable_total=str(order.taxable_total),
        cgst_total=str(order.cgst_total),
        sgst_total=str(order.sgst_total),
        igst_total=str(order.igst_total),
        tax_total=str(order.tax_total),
        notes=order.notes,
        lines=[_to_line_item(line, uom) for line, uom in lines],
    )


@router.get("")
async def list_orders(
    request: Request,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    from_estimate: bool | None = None,
    context: AuthenticatedContext = Depends(require_permission(SALES_ORDER_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)

    service = SalesOrderService(session)
    result = await service.list_orders(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        search=search,
        status_filter=status,
        customer_id=customer_id,
        date_from=date_from,
        date_to=date_to,
        from_estimate_only=from_estimate,
    )

    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(o, name).model_dump() for o, name in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/{order_id}")
async def get_order(
    order_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(SALES_ORDER_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = SalesOrderService(session)
    order, customer_name, lines = await service.get_order(tenant_id=tenant_id, order_id=order_id)
    return {"data": _to_detail(order, customer_name, lines).model_dump(), "meta": _meta()}


async def _idempotent_post(
    *, session: AsyncSession, idempotency_key: str, endpoint: str, tenant_id: uuid.UUID, request_payload: dict, execute
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


@router.post("", status_code=201)
async def create_order(
    request: Request,
    payload: CreateSalesOrderRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(SALES_ORDER_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = SalesOrderService(session)
        order, customer_name, lines = await service.create_order(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            customer_id=uuid.UUID(payload.customer_id),
            order_date=payload.order_date,
            shipping_address=payload.shipping_address,
            notes=payload.notes,
            line_inputs=payload.lines,
            ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": _to_detail(order, customer_name, lines).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/sales/orders",
        tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"),
        execute=_execute,
    )


@router.patch("/{order_id}")
async def update_order(
    request: Request,
    order_id: uuid.UUID,
    payload: UpdateSalesOrderRequest,
    context: AuthenticatedContext = Depends(require_permission(SALES_ORDER_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = SalesOrderService(session)
    order, customer_name, lines = await service.update_order(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        order_id=order_id,
        expected_row_version=payload.expected_row_version,
        customer_id=uuid.UUID(payload.customer_id) if payload.customer_id else None,
        order_date=payload.order_date,
        shipping_address=payload.shipping_address,
        notes=payload.notes,
        line_inputs=payload.lines,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_detail(order, customer_name, lines).model_dump(), "meta": _meta()}


@router.post("/{order_id}/confirm")
async def confirm_order(
    request: Request,
    order_id: uuid.UUID,
    payload: SalesOrderActionRequest,
    context: AuthenticatedContext = Depends(require_permission(SALES_ORDER_CONFIRM)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = SalesOrderService(session)
    order = await service.confirm_order(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        order_id=order_id,
        expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    _, customer_name, lines = await service.get_order(tenant_id=tenant_id, order_id=order.id)
    return {"data": _to_detail(order, customer_name, lines).model_dump(), "meta": _meta()}


@router.post("/{order_id}/cancel")
async def cancel_order(
    request: Request,
    order_id: uuid.UUID,
    payload: SalesOrderActionRequest,
    context: AuthenticatedContext = Depends(require_permission(SALES_ORDER_CANCEL)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = SalesOrderService(session)
    order = await service.cancel_order(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        order_id=order_id,
        expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    _, customer_name, lines = await service.get_order(tenant_id=tenant_id, order_id=order.id)
    return {"data": _to_detail(order, customer_name, lines).model_dump(), "meta": _meta()}


@router.get("/{order_id}/delivery-eligibility")
async def get_delivery_eligibility(
    order_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(DELIVERY_CHALLAN_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-014 §31's suggested endpoint, added here (not duplicated)
    since it's fundamentally a Sales Order query — how much of THIS order
    remains undelivered per line (§12 steps 4-7)."""
    tenant_id = _require_tenant(context)
    service = DeliveryChallanService(session)
    order, customer_name, eligibility_lines = await service.get_delivery_eligibility(
        tenant_id=tenant_id, sales_order_id=order_id
    )
    result = DeliveryEligibility(
        sales_order_id=str(order.id),
        sales_order_number=order.order_number,
        sales_order_status=order.status,
        customer_id=str(order.customer_id),
        customer_name=customer_name,
        billing_address=order.billing_address,
        shipping_address=order.shipping_address,
        place_of_supply_state_code=order.place_of_supply_state_code,
        lines=[
            DeliveryEligibilityLine(
                sales_order_line_id=str(line.sales_order_line.id),
                product_id=str(line.sales_order_line.product_id) if line.sales_order_line.product_id else None,
                description=line.sales_order_line.description,
                hsn_code=line.sales_order_line.hsn_code,
                uom=_to_unit_ref(line.uom),
                ordered_quantity=str(line.sales_order_line.quantity),
                delivered_quantity=str(line.delivered_quantity),
                remaining_quantity=str(line.remaining_quantity),
            )
            for line in eligibility_lines
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}
