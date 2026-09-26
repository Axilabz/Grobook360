"""Purchase Order endpoints (PROMPT-019 foundation, PROMPT-020 full
Purchase Order Management workflow).

Mirrors `sales_orders.py`'s router shape exactly.
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
    GOODS_RECEIPT_CREATE,
    PURCHASE_INVOICE_CREATE,
    PURCHASE_ORDER_CANCEL,
    PURCHASE_ORDER_CONFIRM,
    PURCHASE_ORDER_CREATE,
    PURCHASE_ORDER_EDIT,
    PURCHASE_ORDER_VIEW,
)
from app.db.session import get_db_session
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_line import PurchaseOrderLine
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.envelopes import Pagination
from app.schemas.purchase import (
    CreateInvoiceFromPurchaseOrderRequest,
    CreatePurchaseOrderRequest,
    PurchaseOrderActionRequest,
    PurchaseOrderAuditEvent,
    PurchaseOrderAuditHistory,
    PurchaseOrderDetail,
    PurchaseOrderInvoiceEligibility,
    PurchaseOrderInvoiceEligibilityLine,
    PurchaseOrderLineItem,
    PurchaseOrderListItem,
    PurchaseOrderReceivingSummary,
    PurchaseOrderReceivingSummaryLine,
    PurchaseOrderRelatedDocuments,
    PurchaseOrderRelatedGoodsReceipt,
    PurchaseOrderRelatedInvoice,
    ReceiptEligibility,
    ReceiptEligibilityLine,
    UpdatePurchaseOrderRequest,
)
from app.schemas.sales_estimate import UnitRef
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.purchase.goods_receipt_service import GoodsReceiptService
from app.services.purchase.purchase_invoice_service import PurchaseInvoiceService
from app.services.purchase.purchase_order_service import PurchaseOrderService, QuantityTotals

router = APIRouter(prefix="/purchase/orders", tags=["purchase-orders"])


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


def _to_list_item(
    order: PurchaseOrder, supplier_name: str, totals: QuantityTotals,
    created_by_name: str | None = None, updated_by_name: str | None = None,
) -> PurchaseOrderListItem:
    return PurchaseOrderListItem(
        id=str(order.id), po_number=order.po_number, document_date=order.document_date.isoformat(),
        supplier_id=str(order.supplier_id), supplier_name=supplier_name,
        supplier_reference=order.supplier_reference,
        expected_delivery_date=order.expected_delivery_date.isoformat() if order.expected_delivery_date else None,
        status=order.status,
        total_ordered_quantity=str(totals.ordered), total_received_quantity=str(totals.received),
        total_remaining_quantity=str(totals.remaining),
        grand_total=str(order.grand_total), tax_total=str(order.tax_total),
        created_by=str(order.created_by) if order.created_by else None,
        created_by_name=created_by_name, updated_by_name=updated_by_name,
        created_at=order.created_at.isoformat(),
        updated_at=order.updated_at.isoformat(), row_version=order.row_version,
    )


def _to_line_item(line: PurchaseOrderLine, uom: UnitOfMeasure) -> PurchaseOrderLineItem:
    return PurchaseOrderLineItem(
        id=str(line.id), line_no=line.line_no, product_id=str(line.product_id) if line.product_id else None,
        description=line.description, hsn_code=line.hsn_code, quantity=str(line.quantity), uom=_to_unit_ref(uom),
        unit_price=str(line.unit_price), discount_amount=str(line.discount_amount), taxable_amount=str(line.taxable_amount),
        gst_rate=str(line.gst_rate), cgst_amount=str(line.cgst_amount), sgst_amount=str(line.sgst_amount),
        igst_amount=str(line.igst_amount), line_total=str(line.line_total), received_quantity=str(line.received_quantity),
        remaining_quantity=str(line.quantity - line.received_quantity),
    )


def _to_detail(
    order: PurchaseOrder, supplier_name: str, lines: list[tuple[PurchaseOrderLine, UnitOfMeasure]], totals: QuantityTotals,
    created_by_name: str | None = None, updated_by_name: str | None = None,
) -> PurchaseOrderDetail:
    return PurchaseOrderDetail(
        **_to_list_item(order, supplier_name, totals, created_by_name, updated_by_name).model_dump(), supplier_gstin=order.supplier_gstin,
        billing_address=order.billing_address, shipping_address=order.shipping_address,
        place_of_supply_state_code=order.place_of_supply_state_code,
        payment_terms=order.payment_terms, delivery_terms=order.delivery_terms,
        subtotal=str(order.subtotal),
        discount_total=str(order.discount_total), taxable_total=str(order.taxable_total), cgst_total=str(order.cgst_total),
        sgst_total=str(order.sgst_total), igst_total=str(order.igst_total), notes=order.notes,
        lines=[_to_line_item(line, uom) for line, uom in lines],
    )


@router.get("")
async def list_orders(
    page: int = 1, page_size: int = 25, search: str | None = None, status: str | None = None,
    supplier_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_ORDER_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)

    service = PurchaseOrderService(session)
    result = await service.list_orders(
        tenant_id=tenant_id, page=page, page_size=page_size, search=search, status_filter=status,
        supplier_id=supplier_id, date_from=date_from, date_to=date_to,
    )
    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [
            _to_list_item(order, name, QuantityTotals(ordered=ordered, received=received, remaining=remaining), cbn, ubn).model_dump()
            for order, name, ordered, received, remaining, cbn, ubn in result.items
        ],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/{order_id}")
async def get_order(
    order_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PURCHASE_ORDER_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseOrderService(session)
    order, supplier_name, lines, totals = await service.get_order(tenant_id=tenant_id, order_id=order_id)
    created_by_name, updated_by_name = await service.get_creator_names(order)
    return {"data": _to_detail(order, supplier_name, lines, totals, created_by_name, updated_by_name).model_dump(), "meta": _meta()}


async def _idempotent_post(
    *, session: AsyncSession, idempotency_key: str, endpoint: str, tenant_id: uuid.UUID, request_payload: dict,
    execute, response_status: int = 201,
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
async def create_order(
    request: Request, payload: CreatePurchaseOrderRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_ORDER_CREATE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = PurchaseOrderService(session)
        order, supplier_name, lines = await service.create_order(
            tenant_id=tenant_id, actor_user_id=context.user_id, supplier_id=uuid.UUID(payload.supplier_id),
            document_date=payload.document_date, supplier_reference=payload.supplier_reference,
            expected_delivery_date=payload.expected_delivery_date, payment_terms=payload.payment_terms,
            delivery_terms=payload.delivery_terms, shipping_address=payload.shipping_address, notes=payload.notes,
            line_inputs=payload.lines, ip_address=request.client.host if request.client else "unknown",
        )
        totals = PurchaseOrderService.totals_from_lines(lines)
        return {"data": _to_detail(order, supplier_name, lines, totals).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/purchase/orders", tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"), execute=_execute,
    )


@router.patch("/{order_id}")
async def update_order(
    request: Request, order_id: uuid.UUID, payload: UpdatePurchaseOrderRequest,
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_ORDER_EDIT)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseOrderService(session)
    order, supplier_name, lines = await service.update_order(
        tenant_id=tenant_id, actor_user_id=context.user_id, order_id=order_id, expected_row_version=payload.expected_row_version,
        document_date=payload.document_date, supplier_reference=payload.supplier_reference,
        expected_delivery_date=payload.expected_delivery_date, payment_terms=payload.payment_terms,
        delivery_terms=payload.delivery_terms, shipping_address=payload.shipping_address, notes=payload.notes,
        line_inputs=payload.lines, ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    totals = PurchaseOrderService.totals_from_lines(lines)
    return {"data": _to_detail(order, supplier_name, lines, totals).model_dump(), "meta": _meta()}


@router.post("/{order_id}/confirm")
async def confirm_order(
    request: Request, order_id: uuid.UUID, payload: PurchaseOrderActionRequest,
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_ORDER_CONFIRM)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseOrderService(session)
    await service.confirm_order(
        tenant_id=tenant_id, actor_user_id=context.user_id, order_id=order_id, expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    order, supplier_name, lines, totals = await service.get_order(tenant_id=tenant_id, order_id=order_id)
    created_by_name, updated_by_name = await service.get_creator_names(order)
    return {"data": _to_detail(order, supplier_name, lines, totals, created_by_name, updated_by_name).model_dump(), "meta": _meta()}


@router.post("/{order_id}/cancel")
async def cancel_order(
    request: Request, order_id: uuid.UUID, payload: PurchaseOrderActionRequest,
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_ORDER_CANCEL)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseOrderService(session)
    await service.cancel_order(
        tenant_id=tenant_id, actor_user_id=context.user_id, order_id=order_id, expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    order, supplier_name, lines, totals = await service.get_order(tenant_id=tenant_id, order_id=order_id)
    created_by_name, updated_by_name = await service.get_creator_names(order)
    return {"data": _to_detail(order, supplier_name, lines, totals, created_by_name, updated_by_name).model_dump(), "meta": _meta()}


@router.get("/{order_id}/receipt-eligibility")
async def get_receipt_eligibility(
    order_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(GOODS_RECEIPT_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-019's own equivalent of Delivery Challan's `delivery-
    eligibility` endpoint — how much of THIS purchase order remains
    receivable per line. Gated by goods_receipt.create (preparatory read
    for creating a Goods Receipt), same convention as every prior
    eligibility endpoint in this codebase."""
    tenant_id = _require_tenant(context)
    service = GoodsReceiptService(session)
    order, supplier_name, eligibility_lines = await service.get_receipt_eligibility(tenant_id=tenant_id, purchase_order_id=order_id)
    result = ReceiptEligibility(
        purchase_order_id=str(order.id), purchase_order_number=order.po_number, purchase_order_status=order.status,
        supplier_id=str(order.supplier_id), supplier_name=supplier_name, billing_address=order.billing_address,
        shipping_address=order.shipping_address, place_of_supply_state_code=order.place_of_supply_state_code,
        lines=[
            ReceiptEligibilityLine(
                purchase_order_line_id=str(line.purchase_order_line.id), product_id=str(line.purchase_order_line.product_id) if line.purchase_order_line.product_id else None,
                description=line.purchase_order_line.description, hsn_code=line.purchase_order_line.hsn_code, uom=_to_unit_ref(line.uom),
                unit_price=str(line.purchase_order_line.unit_price), gst_rate=str(line.purchase_order_line.gst_rate),
                ordered_quantity=str(line.purchase_order_line.quantity), received_quantity=str(line.received_quantity),
                remaining_quantity=str(line.remaining_quantity),
            )
            for line in eligibility_lines
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.get("/{order_id}/related-documents")
async def get_related_documents(
    order_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PURCHASE_ORDER_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-020 §17/§24/§34: every Goods Receipt and (transitively, via
    those Goods Receipts) every Purchase Invoice linked to this Purchase
    Order — shown on the PO detail screen's "Related Documents" section.
    Gated by `purchase_order.view` — the entitlement matrix does not
    define a separate "view related documents" permission (§37 Open
    Decision), so this follows the same resolution every other
    supporting/eligibility endpoint in this codebase already uses:
    piggyback on the parent document's own view permission."""
    tenant_id = _require_tenant(context)
    service = PurchaseOrderService(session)
    order, goods_receipts, invoices = await service.get_related_documents(tenant_id=tenant_id, order_id=order_id)
    result = PurchaseOrderRelatedDocuments(
        purchase_order_id=str(order.id),
        goods_receipts=[
            PurchaseOrderRelatedGoodsReceipt(
                id=str(gr.id), grn_number=gr.grn_number, document_date=gr.document_date.isoformat(),
                status=gr.status, total_quantity=str(gr.total_quantity), created_at=gr.created_at.isoformat(),
            )
            for gr in goods_receipts
        ],
        purchase_invoices=[
            PurchaseOrderRelatedInvoice(
                id=str(inv.id), purchase_invoice_number=inv.purchase_invoice_number, document_date=inv.document_date.isoformat(),
                status=inv.status, grand_total=str(inv.grand_total),
                source_goods_receipt_id=str(inv.source_goods_receipt_id) if inv.source_goods_receipt_id else None,
            )
            for inv in invoices
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.get("/{order_id}/receiving-summary")
async def get_receiving_summary(
    order_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PURCHASE_ORDER_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-020 §30's explicit "GET Purchase Order receiving summary"
    capability — the authoritative ordered/received/remaining view, at
    both header and line level. Distinct from `/receipt-eligibility`
    (which is scoped to creating a NEW Goods Receipt and gated by
    `goods_receipt.create`); this one is a pure read of current state,
    gated by `purchase_order.view`."""
    tenant_id = _require_tenant(context)
    service = PurchaseOrderService(session)
    order, lines, totals = await service.get_receiving_summary(tenant_id=tenant_id, order_id=order_id)
    result = PurchaseOrderReceivingSummary(
        purchase_order_id=str(order.id), po_number=order.po_number, status=order.status,
        total_ordered_quantity=str(totals.ordered), total_received_quantity=str(totals.received),
        total_remaining_quantity=str(totals.remaining),
        lines=[
            PurchaseOrderReceivingSummaryLine(
                purchase_order_line_id=str(line.id), product_id=str(line.product_id) if line.product_id else None,
                description=line.description, uom=_to_unit_ref(uom), ordered_quantity=str(line.quantity),
                received_quantity=str(line.received_quantity), remaining_quantity=str(line.quantity - line.received_quantity),
            )
            for line, uom in lines
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.get("/{order_id}/audit-history")
async def get_audit_history(
    order_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PURCHASE_ORDER_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-020 §34/§38: the audit trail shown on the PO detail
    screen. Gated by `purchase_order.view` (same reasoning as
    related-documents above)."""
    tenant_id = _require_tenant(context)
    service = PurchaseOrderService(session)
    events = await service.get_audit_history(tenant_id=tenant_id, order_id=order_id)
    result = PurchaseOrderAuditHistory(
        purchase_order_id=str(order_id),
        events=[
            PurchaseOrderAuditEvent(
                id=str(event.id), action=event.action,
                actor_user_id=str(event.actor_user_id) if event.actor_user_id else None,
                occurred_at=event.occurred_at.isoformat(), before=event.before_json, after=event.after_json,
            )
            for event in events
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.get("/{order_id}/invoiceable-items")
async def get_invoiceable_items(
    order_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PURCHASE_INVOICE_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-022 §8/§10/§26/§40: how much of each PO line is eligible
    to invoice right now — "eligible received quantity minus previously
    invoiced quantity," aggregated across ALL of that line's confirmed
    Goods Receipts (§18 "multiple GR linkage"). Gated by
    `purchase_invoice.create` (preparatory read for creating a Purchase
    Invoice from this PO), same convention as `/receipt-eligibility`
    being gated by `goods_receipt.create`."""
    tenant_id = _require_tenant(context)
    service = PurchaseInvoiceService(session)
    order, supplier_name, eligibility_lines = await service.get_po_invoice_eligibility(tenant_id=tenant_id, purchase_order_id=order_id)
    result = PurchaseOrderInvoiceEligibility(
        purchase_order_id=str(order.id), purchase_order_number=order.po_number, purchase_order_status=order.status,
        supplier_id=str(order.supplier_id), supplier_name=supplier_name,
        lines=[
            PurchaseOrderInvoiceEligibilityLine(
                purchase_order_line_id=str(line.purchase_order_line.id),
                product_id=str(line.purchase_order_line.product_id) if line.purchase_order_line.product_id else None,
                description=line.purchase_order_line.description, hsn_code=line.purchase_order_line.hsn_code, uom=_to_unit_ref(line.uom),
                unit_price=str(line.purchase_order_line.unit_price), gst_rate=str(line.purchase_order_line.gst_rate),
                ordered_quantity=str(line.purchase_order_line.quantity), received_quantity=str(line.purchase_order_line.received_quantity),
                invoiced_quantity=str(line.invoiced_quantity), invoiceable_quantity=str(line.invoiceable_quantity),
            )
            for line in eligibility_lines
        ],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.post("/{order_id}/create-invoice", status_code=201)
async def create_invoice_from_purchase_order(
    request: Request, order_id: uuid.UUID, payload: CreateInvoiceFromPurchaseOrderRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_INVOICE_CREATE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-022 "Supported Flow 2": create a Purchase Invoice directly
    from a Purchase Order, consolidating eligible quantity across
    potentially multiple confirmed Goods Receipts under it — see
    `PurchaseInvoiceService.create_invoice_from_purchase_order`."""
    from app.api.v1.purchase_invoices import _to_detail as _invoice_to_detail

    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = PurchaseInvoiceService(session)
        invoice, supplier_name, po_number, lines = await service.create_invoice_from_purchase_order(
            tenant_id=tenant_id, actor_user_id=context.user_id, purchase_order_id=order_id, document_date=payload.document_date,
            supplier_invoice_number=payload.supplier_invoice_number, supplier_invoice_date=payload.supplier_invoice_date,
            due_date=payload.due_date, notes=payload.notes, line_inputs=payload.lines,
            ip_address=request.client.host if request.client else "unknown",
        )
        duplicate_warning = await service.check_duplicate_supplier_invoice(
            tenant_id=tenant_id, supplier_id=invoice.supplier_id, supplier_invoice_number=invoice.supplier_invoice_number,
            exclude_invoice_id=invoice.id,
        )
        return {"data": _invoice_to_detail(invoice, supplier_name, None, po_number, lines, duplicate_warning).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/purchase/orders/{order_id}/create-invoice",
        tenant_id=tenant_id, request_payload={"order_id": str(order_id), **payload.model_dump(mode="json")}, execute=_execute,
    )
