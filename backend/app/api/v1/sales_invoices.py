"""Sales Invoice endpoints (PROMPT-015).

Mirrors `sales_orders.py`/`delivery_challans.py`'s router shape exactly.
Create and post are the duplicate-submission-sensitive operations
(numbering allocation and stock/accounting/GST posting respectively) and
require an Idempotency-Key.
"""

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, get_current_user, require_permission
from app.core.error_codes import REG_MISSING_FIELD
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import (
    CREDIT_NOTE_CREATE,
    DEBIT_NOTE_CREATE,
    SALES_INVOICE_CANCEL,
    SALES_INVOICE_CREATE,
    SALES_INVOICE_EDIT,
    SALES_INVOICE_POST,
    SALES_INVOICE_VIEW,
    SALES_RETURN_CREATE,
)
from app.db.session import get_db_session
from app.models.sales_invoice import SalesInvoice
from app.models.sales_invoice_line import SalesInvoiceLine
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.credit_debit_note import AdjustmentEligibility, AdjustmentEligibilityLine
from app.schemas.envelopes import Pagination
from app.schemas.sales_estimate import UnitRef
from app.schemas.sales_invoice import (
    CreateDirectInvoiceRequest,
    SalesInvoiceActionRequest,
    SalesInvoiceDetail,
    SalesInvoiceLineItem,
    SalesInvoiceListItem,
    UpdateSalesInvoiceRequest,
)
from app.schemas.sales_return import ReturnEligibility, ReturnEligibilityLine
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.payments.payment_service import PaymentService
from app.services.sales.credit_debit_note_service import CreditDebitNoteService
from app.services.sales.sales_invoice_service import SalesInvoiceService
from app.services.sales.sales_return_service import SalesReturnService

router = APIRouter(prefix="/sales/invoices", tags=["sales-invoices"])


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


def _to_list_item(invoice: SalesInvoice, customer_name: str, dc_number: str | None) -> SalesInvoiceListItem:
    return SalesInvoiceListItem(
        id=str(invoice.id),
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date.isoformat(),
        invoice_type=invoice.invoice_type,
        customer_id=str(invoice.customer_id),
        customer_name=customer_name,
        status=invoice.status,
        source_delivery_challan_id=str(invoice.source_delivery_challan_id) if invoice.source_delivery_challan_id else None,
        source_delivery_challan_number=dc_number,
        grand_total=str(invoice.grand_total),
        tax_total=str(invoice.tax_total),
        paid_amount=str(invoice.paid_amount),
        payment_status=invoice.payment_status,
        created_by=str(invoice.created_by) if invoice.created_by else None,
        created_at=invoice.created_at.isoformat(),
        updated_at=invoice.updated_at.isoformat(),
        row_version=invoice.row_version,
    )


def _to_line_item(line: SalesInvoiceLine, uom: UnitOfMeasure) -> SalesInvoiceLineItem:
    return SalesInvoiceLineItem(
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
        source_delivery_challan_line_id=str(line.source_delivery_challan_line_id)
        if line.source_delivery_challan_line_id
        else None,
    )


def _to_detail(
    invoice: SalesInvoice,
    customer_name: str,
    dc_number: str | None,
    lines: list[tuple[SalesInvoiceLine, UnitOfMeasure]],
) -> SalesInvoiceDetail:
    return SalesInvoiceDetail(
        **_to_list_item(invoice, customer_name, dc_number).model_dump(),
        customer_gstin=invoice.customer_gstin,
        customer_type=invoice.customer_type,
        billing_address=invoice.billing_address,
        shipping_address=invoice.shipping_address,
        place_of_supply_state_code=invoice.place_of_supply_state_code,
        source_sales_order_id=str(invoice.source_sales_order_id) if invoice.source_sales_order_id else None,
        subtotal=str(invoice.subtotal),
        discount_total=str(invoice.discount_total),
        taxable_total=str(invoice.taxable_total),
        cgst_total=str(invoice.cgst_total),
        sgst_total=str(invoice.sgst_total),
        igst_total=str(invoice.igst_total),
        notes=invoice.notes,
        accounting_posting_reference=invoice.accounting_posting_reference,
        gst_transaction_reference=invoice.gst_transaction_reference,
        irn=invoice.irn,
        ack_number=invoice.ack_number,
        ack_date=invoice.ack_date.isoformat() if invoice.ack_date else None,
        einvoice_status=invoice.einvoice_status,
        lines=[_to_line_item(line, uom) for line, uom in lines],
    )


@router.get("")
async def list_invoices(
    request: Request,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    status: str | None = None,
    invoice_type: str | None = None,
    customer_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(SALES_INVOICE_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)

    service = SalesInvoiceService(session)
    result = await service.list_invoices(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        search=search,
        status_filter=status,
        invoice_type_filter=invoice_type,
        customer_id=customer_id,
        date_from=date_from,
        date_to=date_to,
    )

    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(inv, name, dc_num).model_dump() for inv, name, dc_num in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/{invoice_id}")
async def get_invoice(
    invoice_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(SALES_INVOICE_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = SalesInvoiceService(session)
    invoice, customer_name, dc_number, lines = await service.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
    return {"data": _to_detail(invoice, customer_name, dc_number, lines).model_dump(), "meta": _meta()}


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
async def create_direct_invoice(
    request: Request,
    payload: CreateDirectInvoiceRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(SALES_INVOICE_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = SalesInvoiceService(session)
        invoice, customer_name, dc_number, lines = await service.create_direct_invoice(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            customer_id=uuid.UUID(payload.customer_id),
            invoice_date=payload.invoice_date,
            shipping_address=payload.shipping_address,
            notes=payload.notes,
            line_inputs=payload.lines,
            ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": _to_detail(invoice, customer_name, dc_number, lines).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/sales/invoices",
        tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"),
        execute=_execute,
    )


@router.patch("/{invoice_id}")
async def update_invoice(
    request: Request,
    invoice_id: uuid.UUID,
    payload: UpdateSalesInvoiceRequest,
    context: AuthenticatedContext = Depends(require_permission(SALES_INVOICE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = SalesInvoiceService(session)
    invoice, customer_name, dc_number, lines = await service.update_invoice(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        invoice_id=invoice_id,
        expected_row_version=payload.expected_row_version,
        invoice_date=payload.invoice_date,
        shipping_address=payload.shipping_address,
        notes=payload.notes,
        line_inputs=payload.lines,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_detail(invoice, customer_name, dc_number, lines).model_dump(), "meta": _meta()}


@router.post("/{invoice_id}/post", status_code=200)
async def post_invoice(
    request: Request,
    invoice_id: uuid.UUID,
    payload: SalesInvoiceActionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(SALES_INVOICE_POST)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = SalesInvoiceService(session)
        invoice, customer_name, dc_number, lines = await service.post_invoice(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            invoice_id=invoice_id,
            expected_row_version=payload.expected_row_version,
            ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": _to_detail(invoice, customer_name, dc_number, lines).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/sales/invoices/{invoice_id}/post",
        tenant_id=tenant_id,
        request_payload={"invoice_id": str(invoice_id), **payload.model_dump(mode="json")},
        execute=_execute,
        response_status=200,
    )


@router.post("/{invoice_id}/cancel")
async def cancel_invoice(
    request: Request,
    invoice_id: uuid.UUID,
    payload: SalesInvoiceActionRequest,
    context: AuthenticatedContext = Depends(require_permission(SALES_INVOICE_CANCEL)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = SalesInvoiceService(session)
    invoice = await service.cancel_invoice(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        invoice_id=invoice_id,
        expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    _, customer_name, dc_number, lines = await service.get_invoice(tenant_id=tenant_id, invoice_id=invoice.id)
    return {"data": _to_detail(invoice, customer_name, dc_number, lines).model_dump(), "meta": _meta()}


@router.get("/{invoice_id}/return-eligibility")
async def get_return_eligibility(
    invoice_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(SALES_RETURN_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-016 §14's "load invoice items" step — how much of THIS
    invoice remains returnable per line (§7). Gated by sales_return.create
    (same convention as PROMPT-015's own invoice-eligibility endpoint,
    gated by sales_invoice.create): a preparatory read for creating a
    Sales Return, not a mutation of the source Sales Invoice."""
    tenant_id = _require_tenant(context)
    service = SalesReturnService(session)
    invoice, customer_name, lines = await service.get_return_eligibility(tenant_id=tenant_id, invoice_id=invoice_id)
    result = ReturnEligibility(
        source_invoice_id=str(invoice.id),
        source_invoice_number=invoice.invoice_number,
        source_invoice_status=invoice.status,
        customer_id=str(invoice.customer_id),
        customer_name=customer_name,
        customer_gstin=invoice.customer_gstin,
        billing_address=invoice.billing_address,
        shipping_address=invoice.shipping_address,
        place_of_supply_state_code=invoice.place_of_supply_state_code,
        lines=[
            ReturnEligibilityLine(
                source_invoice_line_id=str(line.id),
                product_id=str(line.product_id) if line.product_id else None,
                description=line.description,
                hsn_code=line.hsn_code,
                uom=_to_unit_ref(uom),
                original_quantity=str(line.quantity),
                previously_returned_quantity=str(line.returned_quantity),
                returnable_quantity=str(line.quantity - line.returned_quantity),
                unit_price=str(line.unit_price),
                gst_rate=str(line.gst_rate),
            )
            for line, uom in lines
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.get("/{invoice_id}/adjustment-eligibility")
async def get_adjustment_eligibility(
    invoice_id: uuid.UUID,
    context: AuthenticatedContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-017 §24 step 5's "load eligible quantities/values" step —
    how much of THIS invoice remains creditable/debitable per line (§17).
    Gated by EITHER credit_note.create OR debit_note.create (checked
    directly, since this one endpoint serves both note types) — same
    preparatory-read convention as the return-eligibility endpoint above."""
    if CREDIT_NOTE_CREATE not in context.permissions and DEBIT_NOTE_CREATE not in context.permissions:
        raise AuthorizationError(f"Missing required permission: {CREDIT_NOTE_CREATE} or {DEBIT_NOTE_CREATE}")
    tenant_id = _require_tenant(context)
    service = CreditDebitNoteService(session)
    invoice, customer_name, lines = await service.get_adjustment_eligibility(tenant_id=tenant_id, invoice_id=invoice_id)
    result = AdjustmentEligibility(
        source_invoice_id=str(invoice.id),
        source_invoice_number=invoice.invoice_number,
        source_invoice_status=invoice.status,
        customer_id=str(invoice.customer_id),
        customer_name=customer_name,
        customer_gstin=invoice.customer_gstin,
        billing_address=invoice.billing_address,
        shipping_address=invoice.shipping_address,
        place_of_supply_state_code=invoice.place_of_supply_state_code,
        lines=[
            AdjustmentEligibilityLine(
                source_invoice_line_id=str(line.id),
                product_id=str(line.product_id) if line.product_id else None,
                description=line.description,
                hsn_code=line.hsn_code,
                uom=_to_unit_ref(uom),
                original_quantity=str(line.quantity),
                previously_credited_quantity=str(line.credited_quantity),
                previously_debited_quantity=str(line.debited_quantity),
                creditable_quantity=str(line.quantity - line.credited_quantity),
                debitable_quantity=str(line.quantity - line.debited_quantity),
                unit_price=str(line.unit_price),
                gst_rate=str(line.gst_rate),
            )
            for line, uom in lines
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.get("/{invoice_id}/payment-history")
async def get_payment_history(
    invoice_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(SALES_INVOICE_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Collections recorded against THIS invoice — a narrow, document-
    scoped read gated by the source document's own .view permission,
    mirroring the Purchase chain's own related-documents/audit-history
    convention (PROMPT-020/021/022/023), not a general payment-browsing
    API. Confirms tenant ownership of the invoice first (same 404-for-
    cross-tenant discipline used everywhere else in this codebase)."""
    tenant_id = _require_tenant(context)
    await SalesInvoiceService(session).get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
    entries = await PaymentService(session).list_receipts_for_invoice(tenant_id=tenant_id, sales_invoice_id=invoice_id)
    return {"data": entries, "meta": _meta()}
