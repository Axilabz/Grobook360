"""Sales Return endpoints (PROMPT-016).

Mirrors `sales_invoices.py`/`delivery_challans.py`'s router shape
exactly. Create and confirm are the duplicate-submission-sensitive
operations (numbering allocation and stock/accounting/GST-boundary
posting respectively) and require an Idempotency-Key.
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
    SALES_RETURN_CANCEL,
    SALES_RETURN_CONFIRM,
    SALES_RETURN_CREATE,
    SALES_RETURN_EDIT,
    SALES_RETURN_VIEW,
)
from app.db.session import get_db_session
from app.models.sales_return import SalesReturn
from app.models.sales_return_line import SalesReturnLine
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.envelopes import Pagination
from app.schemas.sales_estimate import UnitRef
from app.schemas.sales_return import (
    CreateSalesReturnRequest,
    SalesReturnActionRequest,
    SalesReturnDetail,
    SalesReturnLineItem,
    SalesReturnListItem,
    UpdateSalesReturnRequest,
)
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.sales.sales_return_service import SalesReturnService

router = APIRouter(prefix="/sales/returns", tags=["sales-returns"])


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


def _to_list_item(sales_return: SalesReturn, customer_name: str, invoice_number: str) -> SalesReturnListItem:
    return SalesReturnListItem(
        id=str(sales_return.id),
        return_number=sales_return.return_number,
        return_date=sales_return.return_date.isoformat(),
        customer_id=str(sales_return.customer_id),
        customer_name=customer_name,
        source_invoice_id=str(sales_return.source_invoice_id),
        source_invoice_number=invoice_number,
        status=sales_return.status,
        return_reason=sales_return.return_reason,
        total_return_quantity=str(sales_return.total_return_quantity),
        grand_total=str(sales_return.grand_total),
        tax_total=str(sales_return.tax_total),
        created_by=str(sales_return.created_by) if sales_return.created_by else None,
        created_at=sales_return.created_at.isoformat(),
        updated_at=sales_return.updated_at.isoformat(),
        row_version=sales_return.row_version,
    )


def _to_line_item(line: SalesReturnLine, uom: UnitOfMeasure) -> SalesReturnLineItem:
    return SalesReturnLineItem(
        id=str(line.id),
        line_no=line.line_no,
        source_invoice_line_id=str(line.source_invoice_line_id),
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
    sales_return: SalesReturn,
    customer_name: str,
    invoice_number: str,
    lines: list[tuple[SalesReturnLine, UnitOfMeasure]],
) -> SalesReturnDetail:
    return SalesReturnDetail(
        **_to_list_item(sales_return, customer_name, invoice_number).model_dump(),
        customer_gstin=sales_return.customer_gstin,
        billing_address=sales_return.billing_address,
        shipping_address=sales_return.shipping_address,
        place_of_supply_state_code=sales_return.place_of_supply_state_code,
        reason_description=sales_return.reason_description,
        subtotal=str(sales_return.subtotal),
        discount_total=str(sales_return.discount_total),
        taxable_total=str(sales_return.taxable_total),
        cgst_total=str(sales_return.cgst_total),
        sgst_total=str(sales_return.sgst_total),
        igst_total=str(sales_return.igst_total),
        notes=sales_return.notes,
        accounting_posting_reference=sales_return.accounting_posting_reference,
        gst_transaction_reference=sales_return.gst_transaction_reference,
        lines=[_to_line_item(line, uom) for line, uom in lines],
    )


@router.get("")
async def list_returns(
    request: Request,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    status: str | None = None,
    return_reason: str | None = None,
    customer_id: uuid.UUID | None = None,
    source_invoice_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(SALES_RETURN_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)

    service = SalesReturnService(session)
    result = await service.list_returns(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        search=search,
        status_filter=status,
        customer_id=customer_id,
        return_reason_filter=return_reason,
        source_invoice_id=source_invoice_id,
        date_from=date_from,
        date_to=date_to,
    )

    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(ret, name, inv_num).model_dump() for ret, name, inv_num in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/{return_id}")
async def get_return(
    return_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(SALES_RETURN_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = SalesReturnService(session)
    sales_return, customer_name, invoice_number, lines = await service.get_return(
        tenant_id=tenant_id, return_id=return_id
    )
    return {"data": _to_detail(sales_return, customer_name, invoice_number, lines).model_dump(), "meta": _meta()}


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
async def create_return(
    request: Request,
    payload: CreateSalesReturnRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(SALES_RETURN_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = SalesReturnService(session)
        sales_return, customer_name, invoice_number, lines = await service.create_return(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            source_invoice_id=uuid.UUID(payload.source_invoice_id),
            return_date=payload.return_date,
            return_reason=payload.return_reason,
            reason_description=payload.reason_description,
            notes=payload.notes,
            line_inputs=payload.lines,
            ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": _to_detail(sales_return, customer_name, invoice_number, lines).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/sales/returns",
        tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"),
        execute=_execute,
    )


@router.patch("/{return_id}")
async def update_return(
    request: Request,
    return_id: uuid.UUID,
    payload: UpdateSalesReturnRequest,
    context: AuthenticatedContext = Depends(require_permission(SALES_RETURN_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = SalesReturnService(session)
    sales_return, customer_name, invoice_number, lines = await service.update_return(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        return_id=return_id,
        expected_row_version=payload.expected_row_version,
        return_date=payload.return_date,
        return_reason=payload.return_reason,
        reason_description=payload.reason_description,
        notes=payload.notes,
        line_inputs=payload.lines,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_detail(sales_return, customer_name, invoice_number, lines).model_dump(), "meta": _meta()}


@router.post("/{return_id}/confirm", status_code=200)
async def confirm_return(
    request: Request,
    return_id: uuid.UUID,
    payload: SalesReturnActionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(SALES_RETURN_CONFIRM)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = SalesReturnService(session)
        sales_return, customer_name, invoice_number, lines = await service.confirm_return(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            return_id=return_id,
            expected_row_version=payload.expected_row_version,
            ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": _to_detail(sales_return, customer_name, invoice_number, lines).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/sales/returns/{return_id}/confirm",
        tenant_id=tenant_id,
        request_payload={"return_id": str(return_id), **payload.model_dump(mode="json")},
        execute=_execute,
        response_status=200,
    )


@router.post("/{return_id}/cancel")
async def cancel_return(
    request: Request,
    return_id: uuid.UUID,
    payload: SalesReturnActionRequest,
    context: AuthenticatedContext = Depends(require_permission(SALES_RETURN_CANCEL)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = SalesReturnService(session)
    sales_return = await service.cancel_return(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        return_id=return_id,
        expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    _, customer_name, invoice_number, lines = await service.get_return(tenant_id=tenant_id, return_id=sales_return.id)
    return {"data": _to_detail(sales_return, customer_name, invoice_number, lines).model_dump(), "meta": _meta()}
