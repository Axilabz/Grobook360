"""Delivery Challan endpoints (PROMPT-014).

Mirrors `sales_orders.py`'s router shape exactly. Create and confirm are
the duplicate-submission-sensitive operations (numbering allocation and
stock-out respectively) and require an Idempotency-Key, matching the
established PROMPT-002/010/012/013 pattern.
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
    DELIVERY_CHALLAN_CANCEL,
    DELIVERY_CHALLAN_CONFIRM,
    DELIVERY_CHALLAN_CREATE,
    DELIVERY_CHALLAN_EDIT,
    DELIVERY_CHALLAN_VIEW,
    SALES_INVOICE_CREATE,
)
from app.db.session import get_db_session
from app.models.delivery_challan import DeliveryChallan
from app.models.delivery_challan_line import DeliveryChallanLine
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.delivery_challan import (
    CreateDeliveryChallanRequest,
    DeliveryChallanActionRequest,
    DeliveryChallanDetail,
    DeliveryChallanLineItem,
    DeliveryChallanListItem,
    UpdateDeliveryChallanRequest,
)
from app.schemas.envelopes import Pagination
from app.schemas.sales_estimate import UnitRef
from app.schemas.sales_invoice import (
    CreateInvoiceFromChallanRequest,
    InvoiceEligibility,
    InvoiceEligibilityLine,
)
from app.api.v1.sales_invoices import _to_detail as _invoice_to_detail
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.sales.delivery_challan_service import DeliveryChallanService
from app.services.sales.sales_invoice_service import SalesInvoiceService

router = APIRouter(prefix="/sales/delivery-challans", tags=["delivery-challans"])


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


def _to_list_item(challan: DeliveryChallan, customer_name: str, so_number: str) -> DeliveryChallanListItem:
    return DeliveryChallanListItem(
        id=str(challan.id),
        challan_number=challan.challan_number,
        challan_date=challan.challan_date.isoformat(),
        source_sales_order_id=str(challan.source_sales_order_id),
        source_sales_order_number=so_number,
        customer_id=str(challan.customer_id),
        customer_name=customer_name,
        status=challan.status,
        total_quantity=str(challan.total_quantity),
        created_by=str(challan.created_by) if challan.created_by else None,
        created_at=challan.created_at.isoformat(),
        updated_at=challan.updated_at.isoformat(),
        row_version=challan.row_version,
    )


def _to_line_item(line: DeliveryChallanLine, uom: UnitOfMeasure) -> DeliveryChallanLineItem:
    return DeliveryChallanLineItem(
        id=str(line.id),
        line_no=line.line_no,
        source_sales_order_line_id=str(line.source_sales_order_line_id),
        product_id=str(line.product_id) if line.product_id else None,
        description=line.description,
        hsn_code=line.hsn_code,
        uom=_to_unit_ref(uom),
        ordered_quantity=str(line.ordered_quantity),
        previously_delivered_quantity=str(line.previously_delivered_quantity),
        current_delivery_quantity=str(line.current_delivery_quantity),
        remaining_quantity=str(line.remaining_quantity),
    )


def _to_detail(
    challan: DeliveryChallan,
    customer_name: str,
    so_number: str,
    lines: list[tuple[DeliveryChallanLine, UnitOfMeasure]],
) -> DeliveryChallanDetail:
    return DeliveryChallanDetail(
        **_to_list_item(challan, customer_name, so_number).model_dump(),
        billing_address=challan.billing_address,
        shipping_address=challan.shipping_address,
        place_of_supply_state_code=challan.place_of_supply_state_code,
        notes=challan.notes,
        lines=[_to_line_item(line, uom) for line, uom in lines],
    )


@router.get("")
async def list_challans(
    request: Request,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    sales_order_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(DELIVERY_CHALLAN_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)

    service = DeliveryChallanService(session)
    result = await service.list_challans(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        search=search,
        status_filter=status,
        customer_id=customer_id,
        sales_order_id=sales_order_id,
        date_from=date_from,
        date_to=date_to,
    )

    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(c, name, so_num).model_dump() for c, name, so_num in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/{challan_id}")
async def get_challan(
    challan_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(DELIVERY_CHALLAN_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = DeliveryChallanService(session)
    challan, customer_name, so_number, lines = await service.get_challan(tenant_id=tenant_id, challan_id=challan_id)
    return {"data": _to_detail(challan, customer_name, so_number, lines).model_dump(), "meta": _meta()}


async def _idempotent_post(
    *,
    session: AsyncSession,
    idempotency_key: str,
    endpoint: str,
    tenant_id: uuid.UUID,
    request_payload: dict,
    execute,
    response_status: int = 201,
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
        response_status=response_status,
        response_body=response_body,
    )
    await session.commit()
    return response_body


@router.post("", status_code=201)
async def create_challan(
    request: Request,
    payload: CreateDeliveryChallanRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(DELIVERY_CHALLAN_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = DeliveryChallanService(session)
        challan, customer_name, so_number, lines = await service.create_challan(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            sales_order_id=uuid.UUID(payload.sales_order_id),
            challan_date=payload.challan_date,
            shipping_address=payload.shipping_address,
            notes=payload.notes,
            line_inputs=payload.lines,
            ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": _to_detail(challan, customer_name, so_number, lines).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/sales/delivery-challans",
        tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"),
        execute=_execute,
    )


@router.patch("/{challan_id}")
async def update_challan(
    request: Request,
    challan_id: uuid.UUID,
    payload: UpdateDeliveryChallanRequest,
    context: AuthenticatedContext = Depends(require_permission(DELIVERY_CHALLAN_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = DeliveryChallanService(session)
    challan, customer_name, so_number, lines = await service.update_challan(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        challan_id=challan_id,
        expected_row_version=payload.expected_row_version,
        challan_date=payload.challan_date,
        shipping_address=payload.shipping_address,
        notes=payload.notes,
        line_inputs=payload.lines,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_detail(challan, customer_name, so_number, lines).model_dump(), "meta": _meta()}


@router.post("/{challan_id}/confirm", status_code=200)
async def confirm_challan(
    request: Request,
    challan_id: uuid.UUID,
    payload: DeliveryChallanActionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(DELIVERY_CHALLAN_CONFIRM)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = DeliveryChallanService(session)
        challan, customer_name, so_number, lines = await service.confirm_challan(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            challan_id=challan_id,
            expected_row_version=payload.expected_row_version,
            ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": _to_detail(challan, customer_name, so_number, lines).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/sales/delivery-challans/{challan_id}/confirm",
        tenant_id=tenant_id,
        request_payload={"challan_id": str(challan_id), **payload.model_dump(mode="json")},
        execute=_execute,
        response_status=200,
    )


@router.post("/{challan_id}/cancel")
async def cancel_challan(
    request: Request,
    challan_id: uuid.UUID,
    payload: DeliveryChallanActionRequest,
    context: AuthenticatedContext = Depends(require_permission(DELIVERY_CHALLAN_CANCEL)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = DeliveryChallanService(session)
    challan = await service.cancel_challan(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        challan_id=challan_id,
        expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    _, customer_name, so_number, lines = await service.get_challan(tenant_id=tenant_id, challan_id=challan.id)
    return {"data": _to_detail(challan, customer_name, so_number, lines).model_dump(), "meta": _meta()}


@router.get("/{challan_id}/invoice-eligibility")
async def get_invoice_eligibility(
    challan_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(SALES_INVOICE_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-015 §13's "load delivered items" step — how much of THIS
    delivery challan remains invoiceable per line (§24)."""
    tenant_id = _require_tenant(context)
    service = SalesInvoiceService(session)
    challan, customer_name, so_number, eligibility_lines = await service.get_invoice_eligibility(
        tenant_id=tenant_id, challan_id=challan_id
    )
    result = InvoiceEligibility(
        source_delivery_challan_id=str(challan.id),
        source_delivery_challan_number=challan.challan_number,
        source_delivery_challan_status=challan.status,
        customer_id=str(challan.customer_id),
        customer_name=customer_name,
        billing_address=challan.billing_address,
        shipping_address=challan.shipping_address,
        place_of_supply_state_code=challan.place_of_supply_state_code,
        lines=[
            InvoiceEligibilityLine(
                source_delivery_challan_line_id=str(dc_line.id),
                product_id=str(dc_line.product_id) if dc_line.product_id else None,
                description=dc_line.description,
                hsn_code=dc_line.hsn_code,
                uom=_to_unit_ref(uom),
                delivered_quantity=str(dc_line.current_delivery_quantity),
                invoiced_quantity=str(dc_line.invoiced_quantity),
                invoiceable_quantity=str(dc_line.current_delivery_quantity - dc_line.invoiced_quantity),
                unit_price=str(so_line.unit_price),
                gst_rate=str(so_line.gst_rate),
            )
            for dc_line, uom, so_line in eligibility_lines
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.post("/{challan_id}/create-invoice", status_code=201)
async def create_invoice_from_challan(
    request: Request,
    challan_id: uuid.UUID,
    payload: CreateInvoiceFromChallanRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(SALES_INVOICE_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = SalesInvoiceService(session)
        invoice, customer_name, dc_number, lines = await service.create_invoice_from_challan(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            challan_id=challan_id,
            invoice_date=payload.invoice_date,
            notes=payload.notes,
            line_inputs=payload.lines,
            ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": _invoice_to_detail(invoice, customer_name, dc_number, lines).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/sales/delivery-challans/{challan_id}/create-invoice",
        tenant_id=tenant_id,
        request_payload={"challan_id": str(challan_id), **payload.model_dump(mode="json")},
        execute=_execute,
    )
