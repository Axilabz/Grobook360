"""Purchase Invoice endpoints (PROMPT-019 foundation, PROMPT-022 full
Purchase Invoice Management workflow).

Mirrors `sales_invoices.py`'s router shape exactly.
"""

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.error_codes import REG_MISSING_FIELD
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import (
    PURCHASE_INVOICE_CANCEL,
    PURCHASE_INVOICE_CREATE,
    PURCHASE_INVOICE_EDIT,
    PURCHASE_INVOICE_POST,
    PURCHASE_INVOICE_VIEW,
    PURCHASE_RETURN_CREATE,
)
from app.db.session import get_db_session
from app.models.purchase_invoice import DIRECT_PURCHASE_INVOICE, PurchaseInvoice
from app.models.purchase_invoice_line import PurchaseInvoiceLine
from app.models.purchase_order import PurchaseOrder
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.envelopes import Pagination
from app.schemas.purchase import (
    CreateDirectPurchaseInvoiceRequest,
    CreateInvoiceFromPurchaseOrderRequest,
    PurchaseInvoiceActionRequest,
    PurchaseInvoiceAuditEvent,
    PurchaseInvoiceAuditHistory,
    PurchaseInvoiceDetail,
    PurchaseInvoiceLineItem,
    PurchaseInvoiceListItem,
    PurchaseInvoiceRelatedDocuments,
    PurchaseInvoiceRelatedGoodsReceipt,
    PurchaseInvoiceRelatedReturn,
    PurchaseOrderInvoiceEligibility,
    PurchaseOrderInvoiceEligibilityLine,
    PurchaseReturnEligibility,
    PurchaseReturnEligibilityLine,
    UpdatePurchaseInvoiceRequest,
)
from app.schemas.sales_estimate import UnitRef
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.purchase.purchase_invoice_service import PurchaseInvoiceService
from app.services.purchase.purchase_return_service import PurchaseReturnService

router = APIRouter(prefix="/purchase/invoices", tags=["purchase-invoices"])


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


def _stock_impact(invoice: PurchaseInvoice) -> str:
    """§12: the system-determined decision — never user-editable, never
    accepted from the client. A DIRECT invoice always requires its own
    Stock IN (once posted); a GR-sourced or PO-consolidated invoice
    bills quantity that was already received, so it never does."""
    return "STOCK_IN_REQUIRED" if invoice.invoice_type == DIRECT_PURCHASE_INVOICE else "STOCK_ALREADY_RECEIVED"


def _to_list_item(invoice: PurchaseInvoice, supplier_name: str, grn_number: str | None, po_number: str | None) -> PurchaseInvoiceListItem:
    return PurchaseInvoiceListItem(
        id=str(invoice.id), purchase_invoice_number=invoice.purchase_invoice_number,
        supplier_invoice_number=invoice.supplier_invoice_number, document_date=invoice.document_date.isoformat(),
        supplier_invoice_date=invoice.supplier_invoice_date.isoformat() if invoice.supplier_invoice_date else None,
        due_date=invoice.due_date.isoformat() if invoice.due_date else None,
        invoice_type=invoice.invoice_type, supplier_id=str(invoice.supplier_id), supplier_name=supplier_name,
        status=invoice.status, source_goods_receipt_id=str(invoice.source_goods_receipt_id) if invoice.source_goods_receipt_id else None,
        source_goods_receipt_number=grn_number,
        source_purchase_order_id=str(invoice.source_purchase_order_id) if invoice.source_purchase_order_id else None,
        source_purchase_order_number=po_number, stock_impact=_stock_impact(invoice),
        grand_total=str(invoice.grand_total), tax_total=str(invoice.tax_total),
        paid_amount=str(invoice.paid_amount), payment_status=invoice.payment_status,
        created_by=str(invoice.created_by) if invoice.created_by else None, created_at=invoice.created_at.isoformat(),
        updated_at=invoice.updated_at.isoformat(), row_version=invoice.row_version,
    )


def _to_line_item(
    line: PurchaseInvoiceLine, uom: UnitOfMeasure, stock_info: tuple[uuid.UUID | None, bool] | None = None
) -> PurchaseInvoiceLineItem:
    movement_id, reversed_flag = stock_info or (None, False)
    return PurchaseInvoiceLineItem(
        id=str(line.id), line_no=line.line_no, product_id=str(line.product_id) if line.product_id else None,
        description=line.description, hsn_code=line.hsn_code, quantity=str(line.quantity), uom=_to_unit_ref(uom),
        unit_price=str(line.unit_price), discount_amount=str(line.discount_amount), taxable_amount=str(line.taxable_amount),
        gst_rate=str(line.gst_rate), cgst_amount=str(line.cgst_amount), sgst_amount=str(line.sgst_amount),
        igst_amount=str(line.igst_amount), line_total=str(line.line_total),
        source_goods_receipt_line_id=str(line.source_goods_receipt_line_id) if line.source_goods_receipt_line_id else None,
        source_purchase_order_line_id=str(line.source_purchase_order_line_id) if line.source_purchase_order_line_id else None,
        returned_quantity=str(line.returned_quantity),
        stock_movement_id=str(movement_id) if movement_id else None, stock_movement_reversed=reversed_flag,
    )


def _to_detail(
    invoice: PurchaseInvoice, supplier_name: str, grn_number: str | None, po_number: str | None,
    lines: list[tuple[PurchaseInvoiceLine, UnitOfMeasure]], duplicate_warning: bool = False,
    stock_info: dict[uuid.UUID, tuple[uuid.UUID | None, bool]] | None = None,
) -> PurchaseInvoiceDetail:
    stock_info = stock_info or {}
    return PurchaseInvoiceDetail(
        **_to_list_item(invoice, supplier_name, grn_number, po_number).model_dump(), supplier_gstin=invoice.supplier_gstin,
        place_of_supply_state_code=invoice.place_of_supply_state_code, subtotal=str(invoice.subtotal),
        discount_total=str(invoice.discount_total), taxable_total=str(invoice.taxable_total), cgst_total=str(invoice.cgst_total),
        sgst_total=str(invoice.sgst_total), igst_total=str(invoice.igst_total), notes=invoice.notes,
        duplicate_supplier_invoice_warning=duplicate_warning,
        accounting_posting_reference=invoice.accounting_posting_reference,
        gst_transaction_reference=invoice.gst_transaction_reference,
        lines=[_to_line_item(line, uom, stock_info.get(line.id)) for line, uom in lines],
    )


@router.get("")
async def list_invoices(
    page: int = 1, page_size: int = 25, search: str | None = None, status: str | None = None, invoice_type: str | None = None,
    supplier_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_INVOICE_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)
    service = PurchaseInvoiceService(session)
    result = await service.list_invoices(
        tenant_id=tenant_id, page=page, page_size=page_size, search=search, status_filter=status,
        invoice_type_filter=invoice_type, supplier_id=supplier_id, date_from=date_from, date_to=date_to,
    )
    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(inv, name, grn, po_num).model_dump() for inv, name, grn, po_num in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/{invoice_id}")
async def get_invoice(
    invoice_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PURCHASE_INVOICE_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseInvoiceService(session)
    invoice, supplier_name, grn_number, po_number, lines = await service.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
    duplicate_warning = await service.check_duplicate_supplier_invoice(
        tenant_id=tenant_id, supplier_id=invoice.supplier_id, supplier_invoice_number=invoice.supplier_invoice_number,
        exclude_invoice_id=invoice.id,
    )
    stock_info = await service.stock_movement_info_for_lines(tenant_id, [line.id for line, _uom in lines])
    return {"data": _to_detail(invoice, supplier_name, grn_number, po_number, lines, duplicate_warning, stock_info).model_dump(), "meta": _meta()}


async def _idempotent_post(
    *, session: AsyncSession, idempotency_key: str, endpoint: str, tenant_id: uuid.UUID, request_payload: dict, execute, response_status: int = 201,
) -> dict:
    idempotency = IdempotencyService(session)
    check_result = await idempotency.check(idempotency_key=idempotency_key, endpoint=endpoint, payload=request_payload)
    if check_result.existing_response is not None:
        _, body = check_result.existing_response
        return body
    response_body = await execute()
    await idempotency.store(
        idempotency_key=idempotency_key, endpoint=endpoint, payload=request_payload, tenant_id=tenant_id,
        response_status=response_status, response_body=response_body,
    )
    await session.commit()
    return response_body


@router.post("", status_code=201)
async def create_direct_invoice(
    request: Request, payload: CreateDirectPurchaseInvoiceRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_INVOICE_CREATE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = PurchaseInvoiceService(session)
        invoice, supplier_name, grn_number, lines = await service.create_direct_invoice(
            tenant_id=tenant_id, actor_user_id=context.user_id, supplier_id=uuid.UUID(payload.supplier_id),
            document_date=payload.document_date, supplier_invoice_number=payload.supplier_invoice_number,
            supplier_invoice_date=payload.supplier_invoice_date, due_date=payload.due_date, notes=payload.notes,
            line_inputs=payload.lines, ip_address=request.client.host if request.client else "unknown",
        )
        duplicate_warning = await service.check_duplicate_supplier_invoice(
            tenant_id=tenant_id, supplier_id=invoice.supplier_id, supplier_invoice_number=invoice.supplier_invoice_number,
            exclude_invoice_id=invoice.id,
        )
        return {"data": _to_detail(invoice, supplier_name, grn_number, None, lines, duplicate_warning).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/purchase/invoices", tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"), execute=_execute,
    )


@router.patch("/{invoice_id}")
async def update_invoice(
    request: Request, invoice_id: uuid.UUID, payload: UpdatePurchaseInvoiceRequest,
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_INVOICE_EDIT)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseInvoiceService(session)
    invoice, supplier_name, grn_number, lines = await service.update_invoice(
        tenant_id=tenant_id, actor_user_id=context.user_id, invoice_id=invoice_id, expected_row_version=payload.expected_row_version,
        document_date=payload.document_date, supplier_invoice_number=payload.supplier_invoice_number,
        supplier_invoice_date=payload.supplier_invoice_date, due_date=payload.due_date, notes=payload.notes,
        line_inputs=payload.lines, ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    duplicate_warning = await service.check_duplicate_supplier_invoice(
        tenant_id=tenant_id, supplier_id=invoice.supplier_id, supplier_invoice_number=invoice.supplier_invoice_number,
        exclude_invoice_id=invoice.id,
    )
    po_number = None
    if invoice.source_purchase_order_id:
        po_result = await session.execute(select(PurchaseOrder.po_number).where(PurchaseOrder.id == invoice.source_purchase_order_id))
        po_number = po_result.scalar_one_or_none()
    return {"data": _to_detail(invoice, supplier_name, grn_number, po_number, lines, duplicate_warning).model_dump(), "meta": _meta()}


@router.post("/{invoice_id}/post", status_code=200)
async def post_invoice(
    request: Request, invoice_id: uuid.UUID, payload: PurchaseInvoiceActionRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_INVOICE_POST)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = PurchaseInvoiceService(session)
        invoice, supplier_name, grn_number, lines = await service.post_invoice(
            tenant_id=tenant_id, actor_user_id=context.user_id, invoice_id=invoice_id, expected_row_version=payload.expected_row_version,
            ip_address=request.client.host if request.client else "unknown",
        )
        stock_info = await service.stock_movement_info_for_lines(tenant_id, [line.id for line, _uom in lines])
        po_number = None
        if invoice.source_purchase_order_id:
            po_result = await session.execute(select(PurchaseOrder.po_number).where(PurchaseOrder.id == invoice.source_purchase_order_id))
            po_number = po_result.scalar_one_or_none()
        return {"data": _to_detail(invoice, supplier_name, grn_number, po_number, lines, False, stock_info).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/purchase/invoices/{invoice_id}/post", tenant_id=tenant_id,
        request_payload={"invoice_id": str(invoice_id), **payload.model_dump(mode="json")}, execute=_execute, response_status=200,
    )


@router.post("/{invoice_id}/cancel")
async def cancel_invoice(
    request: Request, invoice_id: uuid.UUID, payload: PurchaseInvoiceActionRequest,
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_INVOICE_CANCEL)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseInvoiceService(session)
    await service.cancel_invoice(
        tenant_id=tenant_id, actor_user_id=context.user_id, invoice_id=invoice_id, expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    invoice, supplier_name, grn_number, po_number, lines = await service.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
    stock_info = await service.stock_movement_info_for_lines(tenant_id, [line.id for line, _uom in lines])
    return {"data": _to_detail(invoice, supplier_name, grn_number, po_number, lines, False, stock_info).model_dump(), "meta": _meta()}


@router.get("/{invoice_id}/return-eligibility")
async def get_return_eligibility(
    invoice_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PURCHASE_RETURN_CREATE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseReturnService(session)
    invoice, supplier_name, lines = await service.get_return_eligibility(tenant_id=tenant_id, invoice_id=invoice_id)
    result = PurchaseReturnEligibility(
        source_purchase_invoice_id=str(invoice.id), source_purchase_invoice_number=invoice.purchase_invoice_number,
        source_purchase_invoice_status=invoice.status, supplier_id=str(invoice.supplier_id), supplier_name=supplier_name,
        lines=[
            PurchaseReturnEligibilityLine(
                source_purchase_invoice_line_id=str(line.id), product_id=str(line.product_id) if line.product_id else None,
                description=line.description, hsn_code=line.hsn_code, uom=_to_unit_ref(uom), original_quantity=str(line.quantity),
                previously_returned_quantity=str(line.returned_quantity), returnable_quantity=str(line.quantity - line.returned_quantity),
                unit_price=str(line.unit_price), gst_rate=str(line.gst_rate),
            )
            for line, uom in lines
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.get("/{invoice_id}/related-documents")
async def get_related_documents(
    invoice_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PURCHASE_INVOICE_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-022 §36/§47: source PO (if any), every contributing Goods
    Receipt, and every Purchase Return created against this invoice.
    Gated by `purchase_invoice.view` — same convention PROMPT-020/021
    established for their own related-documents endpoints (no separate
    permission is defined for this by the entitlement matrix)."""
    tenant_id = _require_tenant(context)
    service = PurchaseInvoiceService(session)
    invoice, order, goods_receipts, purchase_returns = await service.get_related_documents(tenant_id=tenant_id, invoice_id=invoice_id)
    result = PurchaseInvoiceRelatedDocuments(
        purchase_invoice_id=str(invoice.id),
        source_purchase_order_id=str(order.id) if order else None,
        source_purchase_order_number=order.po_number if order else None,
        source_purchase_order_status=order.status if order else None,
        goods_receipts=[
            PurchaseInvoiceRelatedGoodsReceipt(id=str(gr.id), grn_number=gr.grn_number, document_date=gr.document_date.isoformat(), status=gr.status)
            for gr in goods_receipts
        ],
        purchase_returns=[
            PurchaseInvoiceRelatedReturn(
                id=str(ret.id), purchase_return_number=ret.purchase_return_number, document_date=ret.document_date.isoformat(),
                status=ret.status, grand_total=str(ret.grand_total),
            )
            for ret in purchase_returns
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.get("/{invoice_id}/audit-history")
async def get_audit_history(
    invoice_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PURCHASE_INVOICE_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-022 §51: the audit trail shown on the invoice detail
    screen. Gated by `purchase_invoice.view` (same reasoning as
    related-documents above)."""
    tenant_id = _require_tenant(context)
    service = PurchaseInvoiceService(session)
    events = await service.get_audit_history(tenant_id=tenant_id, invoice_id=invoice_id)
    result = PurchaseInvoiceAuditHistory(
        purchase_invoice_id=str(invoice_id),
        events=[
            PurchaseInvoiceAuditEvent(
                id=str(event.id), action=event.action,
                actor_user_id=str(event.actor_user_id) if event.actor_user_id else None,
                occurred_at=event.occurred_at.isoformat(), before=event.before_json, after=event.after_json,
            )
            for event in events
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}
