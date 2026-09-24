"""Goods Receipt endpoints (PROMPT-019 foundation, PROMPT-021 full Goods
Receipt Management workflow).

Mirrors `delivery_challans.py`'s router shape exactly.
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
    GOODS_RECEIPT_CANCEL,
    GOODS_RECEIPT_CONFIRM,
    GOODS_RECEIPT_CREATE,
    GOODS_RECEIPT_EDIT,
    GOODS_RECEIPT_VIEW,
    PURCHASE_INVOICE_CREATE,
)
from app.db.session import get_db_session
from app.models.goods_receipt import GoodsReceipt
from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.envelopes import Pagination
from app.schemas.purchase import (
    CreateGoodsReceiptRequest,
    CreateInvoiceFromReceiptRequest,
    GoodsReceiptActionRequest,
    GoodsReceiptAuditEvent,
    GoodsReceiptAuditHistory,
    GoodsReceiptDetail,
    GoodsReceiptLineItem,
    GoodsReceiptListItem,
    GoodsReceiptRelatedDocuments,
    GoodsReceiptRelatedInvoice,
    InvoiceEligibility,
    InvoiceEligibilityLine,
    UpdateGoodsReceiptRequest,
)
from app.schemas.sales_estimate import UnitRef
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.purchase.goods_receipt_service import GoodsReceiptService
from app.services.purchase.purchase_invoice_service import PurchaseInvoiceService

router = APIRouter(prefix="/purchase/goods-receipts", tags=["goods-receipts"])


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


def _to_list_item(receipt: GoodsReceipt, supplier_name: str, po_number: str | None) -> GoodsReceiptListItem:
    return GoodsReceiptListItem(
        id=str(receipt.id), grn_number=receipt.grn_number, document_date=receipt.document_date.isoformat(),
        supplier_id=str(receipt.supplier_id), supplier_name=supplier_name,
        supplier_delivery_note=receipt.supplier_delivery_note,
        source_purchase_order_id=str(receipt.source_purchase_order_id) if receipt.source_purchase_order_id else None,
        source_purchase_order_number=po_number, status=receipt.status, total_quantity=str(receipt.total_quantity),
        grand_total=str(receipt.grand_total), created_by=str(receipt.created_by) if receipt.created_by else None,
        created_at=receipt.created_at.isoformat(), updated_at=receipt.updated_at.isoformat(), row_version=receipt.row_version,
    )


def _to_line_item(
    line: GoodsReceiptLine, uom: UnitOfMeasure, stock_info: tuple[uuid.UUID | None, bool] | None = None
) -> GoodsReceiptLineItem:
    movement_id, reversed_flag = stock_info or (None, False)
    return GoodsReceiptLineItem(
        id=str(line.id), line_no=line.line_no, source_purchase_order_line_id=str(line.source_purchase_order_line_id) if line.source_purchase_order_line_id else None,
        product_id=str(line.product_id) if line.product_id else None, description=line.description, hsn_code=line.hsn_code,
        ordered_quantity=str(line.ordered_quantity), previously_received_quantity=str(line.previously_received_quantity),
        quantity=str(line.quantity), remaining_quantity=str(line.remaining_quantity), uom=_to_unit_ref(uom),
        unit_price=str(line.unit_price), taxable_amount=str(line.taxable_amount), gst_rate=str(line.gst_rate),
        line_total=str(line.line_total), invoiced_quantity=str(line.invoiced_quantity),
        stock_movement_id=str(movement_id) if movement_id else None, stock_movement_reversed=reversed_flag,
    )


def _to_detail(
    receipt: GoodsReceipt, supplier_name: str, po_number: str | None, lines: list[tuple[GoodsReceiptLine, UnitOfMeasure]],
    stock_info: dict[uuid.UUID, tuple[uuid.UUID | None, bool]] | None = None,
) -> GoodsReceiptDetail:
    stock_info = stock_info or {}
    return GoodsReceiptDetail(
        **_to_list_item(receipt, supplier_name, po_number).model_dump(), notes=receipt.notes, subtotal=str(receipt.subtotal),
        discount_total=str(receipt.discount_total), taxable_total=str(receipt.taxable_total), cgst_total=str(receipt.cgst_total),
        sgst_total=str(receipt.sgst_total), igst_total=str(receipt.igst_total), tax_total=str(receipt.tax_total),
        lines=[_to_line_item(line, uom, stock_info.get(line.id)) for line, uom in lines],
    )


@router.get("")
async def list_receipts(
    page: int = 1, page_size: int = 25, search: str | None = None, status: str | None = None,
    supplier_id: uuid.UUID | None = None, purchase_order_id: uuid.UUID | None = None,
    date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(GOODS_RECEIPT_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)
    service = GoodsReceiptService(session)
    result = await service.list_receipts(
        tenant_id=tenant_id, page=page, page_size=page_size, search=search, status_filter=status,
        supplier_id=supplier_id, purchase_order_id=purchase_order_id, date_from=date_from, date_to=date_to,
    )
    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(r, name, po_num).model_dump() for r, name, po_num in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/{receipt_id}")
async def get_receipt(
    receipt_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(GOODS_RECEIPT_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = GoodsReceiptService(session)
    receipt, supplier_name, po_number, lines, stock_info = await service.get_receipt(tenant_id=tenant_id, receipt_id=receipt_id)
    return {"data": _to_detail(receipt, supplier_name, po_number, lines, stock_info).model_dump(), "meta": _meta()}


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
async def create_receipt(
    request: Request, payload: CreateGoodsReceiptRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(GOODS_RECEIPT_CREATE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = GoodsReceiptService(session)
        receipt, supplier_name, po_number, lines = await service.create_receipt(
            tenant_id=tenant_id, actor_user_id=context.user_id, purchase_order_id=uuid.UUID(payload.purchase_order_id),
            document_date=payload.document_date, supplier_delivery_note=payload.supplier_delivery_note,
            notes=payload.notes, line_inputs=payload.lines,
            ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": _to_detail(receipt, supplier_name, po_number, lines).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/purchase/goods-receipts", tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"), execute=_execute,
    )


@router.patch("/{receipt_id}")
async def update_receipt(
    request: Request, receipt_id: uuid.UUID, payload: UpdateGoodsReceiptRequest,
    context: AuthenticatedContext = Depends(require_permission(GOODS_RECEIPT_EDIT)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = GoodsReceiptService(session)
    receipt, supplier_name, po_number, lines = await service.update_receipt(
        tenant_id=tenant_id, actor_user_id=context.user_id, receipt_id=receipt_id, expected_row_version=payload.expected_row_version,
        document_date=payload.document_date, supplier_delivery_note=payload.supplier_delivery_note,
        notes=payload.notes, line_inputs=payload.lines,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    return {"data": _to_detail(receipt, supplier_name, po_number, lines).model_dump(), "meta": _meta()}


@router.post("/{receipt_id}/confirm", status_code=200)
async def confirm_receipt(
    request: Request, receipt_id: uuid.UUID, payload: GoodsReceiptActionRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(GOODS_RECEIPT_CONFIRM)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = GoodsReceiptService(session)
        receipt, supplier_name, po_number, lines = await service.confirm_receipt(
            tenant_id=tenant_id, actor_user_id=context.user_id, receipt_id=receipt_id, expected_row_version=payload.expected_row_version,
            ip_address=request.client.host if request.client else "unknown",
        )
        stock_info = await service.stock_movement_info_for_lines(tenant_id, [line.id for line, _uom in lines])
        return {"data": _to_detail(receipt, supplier_name, po_number, lines, stock_info).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/purchase/goods-receipts/{receipt_id}/confirm",
        tenant_id=tenant_id, request_payload={"receipt_id": str(receipt_id), **payload.model_dump(mode="json")},
        execute=_execute, response_status=200,
    )


@router.post("/{receipt_id}/cancel")
async def cancel_receipt(
    request: Request, receipt_id: uuid.UUID, payload: GoodsReceiptActionRequest,
    context: AuthenticatedContext = Depends(require_permission(GOODS_RECEIPT_CANCEL)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = GoodsReceiptService(session)
    await service.cancel_receipt(
        tenant_id=tenant_id, actor_user_id=context.user_id, receipt_id=receipt_id, expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    receipt, supplier_name, po_number, lines, stock_info = await service.get_receipt(tenant_id=tenant_id, receipt_id=receipt_id)
    return {"data": _to_detail(receipt, supplier_name, po_number, lines, stock_info).model_dump(), "meta": _meta()}


@router.get("/{receipt_id}/invoice-eligibility")
async def get_invoice_eligibility(
    receipt_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PURCHASE_INVOICE_CREATE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseInvoiceService(session)
    receipt, supplier_name, gr_lines = await service.get_invoice_eligibility(tenant_id=tenant_id, receipt_id=receipt_id)
    result = InvoiceEligibility(
        source_goods_receipt_id=str(receipt.id), source_goods_receipt_number=receipt.grn_number,
        source_goods_receipt_status=receipt.status, supplier_id=str(receipt.supplier_id), supplier_name=supplier_name,
        lines=[
            InvoiceEligibilityLine(
                source_goods_receipt_line_id=str(gr_line.id), product_id=str(gr_line.product_id) if gr_line.product_id else None,
                description=gr_line.description, hsn_code=gr_line.hsn_code, uom=_to_unit_ref(uom),
                received_quantity=str(gr_line.quantity), invoiced_quantity=str(gr_line.invoiced_quantity),
                invoiceable_quantity=str(gr_line.quantity - gr_line.invoiced_quantity), unit_price=str(gr_line.unit_price),
                gst_rate=str(gr_line.gst_rate),
            )
            for gr_line, uom in gr_lines
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.post("/{receipt_id}/create-invoice", status_code=201)
async def create_invoice_from_receipt(
    request: Request, receipt_id: uuid.UUID, payload: CreateInvoiceFromReceiptRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_INVOICE_CREATE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    from app.api.v1.purchase_invoices import _to_detail as _invoice_to_detail

    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = PurchaseInvoiceService(session)
        invoice, supplier_name, grn_number, lines = await service.create_invoice_from_receipt(
            tenant_id=tenant_id, actor_user_id=context.user_id, receipt_id=receipt_id, document_date=payload.document_date,
            supplier_invoice_number=payload.supplier_invoice_number, supplier_invoice_date=payload.supplier_invoice_date,
            due_date=payload.due_date, notes=payload.notes, line_inputs=payload.lines,
            ip_address=request.client.host if request.client else "unknown",
        )
        duplicate_warning = await service.check_duplicate_supplier_invoice(
            tenant_id=tenant_id, supplier_id=invoice.supplier_id, supplier_invoice_number=invoice.supplier_invoice_number,
            exclude_invoice_id=invoice.id,
        )
        return {"data": _invoice_to_detail(invoice, supplier_name, grn_number, None, lines, duplicate_warning).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/purchase/goods-receipts/{receipt_id}/create-invoice",
        tenant_id=tenant_id, request_payload={"receipt_id": str(receipt_id), **payload.model_dump(mode="json")}, execute=_execute,
    )


@router.get("/{receipt_id}/related-documents")
async def get_related_documents(
    receipt_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(GOODS_RECEIPT_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-021 §18/§34/§41: the source Purchase Order plus every
    Purchase Invoice created against this Goods Receipt. Gated by
    `goods_receipt.view` — the entitlement matrix does not define a
    separate "view related documents" permission (§45 Open Decision),
    same resolution PROMPT-020 already used for Purchase Order's own
    equivalent endpoint."""
    tenant_id = _require_tenant(context)
    service = GoodsReceiptService(session)
    receipt, order, invoices = await service.get_related_documents(tenant_id=tenant_id, receipt_id=receipt_id)
    result = GoodsReceiptRelatedDocuments(
        goods_receipt_id=str(receipt.id),
        source_purchase_order_id=str(order.id) if order else None,
        source_purchase_order_number=order.po_number if order else None,
        source_purchase_order_status=order.status if order else None,
        purchase_invoices=[
            GoodsReceiptRelatedInvoice(
                id=str(inv.id), purchase_invoice_number=inv.purchase_invoice_number,
                document_date=inv.document_date.isoformat(), status=inv.status, grand_total=str(inv.grand_total),
            )
            for inv in invoices
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.get("/{receipt_id}/audit-history")
async def get_audit_history(
    receipt_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(GOODS_RECEIPT_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-021 §46: the audit trail shown on the GR detail screen.
    Gated by `goods_receipt.view` (same reasoning as related-documents
    above)."""
    tenant_id = _require_tenant(context)
    service = GoodsReceiptService(session)
    events = await service.get_audit_history(tenant_id=tenant_id, receipt_id=receipt_id)
    result = GoodsReceiptAuditHistory(
        goods_receipt_id=str(receipt_id),
        events=[
            GoodsReceiptAuditEvent(
                id=str(event.id), action=event.action,
                actor_user_id=str(event.actor_user_id) if event.actor_user_id else None,
                occurred_at=event.occurred_at.isoformat(), before=event.before_json, after=event.after_json,
            )
            for event in events
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}
