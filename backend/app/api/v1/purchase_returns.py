"""Purchase Return endpoints (PROMPT-019).

Mirrors `sales_returns.py`'s router shape exactly.
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
    PURCHASE_RETURN_CANCEL,
    PURCHASE_RETURN_CONFIRM,
    PURCHASE_RETURN_CREATE,
    PURCHASE_RETURN_EDIT,
    PURCHASE_RETURN_VIEW,
)
from app.db.session import get_db_session
from app.models.purchase_return import PurchaseReturn
from app.models.purchase_return_line import PurchaseReturnLine
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.envelopes import Pagination
from app.schemas.purchase import (
    CreatePurchaseReturnRequest,
    PurchaseReturnActionRequest,
    PurchaseReturnAuditEvent,
    PurchaseReturnAuditHistory,
    PurchaseReturnDetail,
    PurchaseReturnLineItem,
    PurchaseReturnListItem,
    PurchaseReturnRelatedDocuments,
    PurchaseReturnRelatedGoodsReceipt,
    UpdatePurchaseReturnRequest,
)
from app.schemas.sales_estimate import UnitRef
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.purchase.purchase_return_service import PurchaseReturnService

router = APIRouter(prefix="/purchase/returns", tags=["purchase-returns"])


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


def _to_list_item(purchase_return: PurchaseReturn, supplier_name: str, invoice_number: str) -> PurchaseReturnListItem:
    return PurchaseReturnListItem(
        id=str(purchase_return.id), purchase_return_number=purchase_return.purchase_return_number,
        document_date=purchase_return.document_date.isoformat(), supplier_id=str(purchase_return.supplier_id),
        supplier_name=supplier_name, source_purchase_invoice_id=str(purchase_return.source_purchase_invoice_id),
        source_purchase_invoice_number=invoice_number, status=purchase_return.status, return_reason=purchase_return.return_reason,
        total_return_quantity=str(purchase_return.total_return_quantity), grand_total=str(purchase_return.grand_total),
        created_by=str(purchase_return.created_by) if purchase_return.created_by else None,
        created_at=purchase_return.created_at.isoformat(), updated_at=purchase_return.updated_at.isoformat(),
        row_version=purchase_return.row_version,
    )


def _to_line_item(
    line: PurchaseReturnLine, uom: UnitOfMeasure, stock_info: dict[uuid.UUID, tuple[uuid.UUID | None, bool]] | None = None,
) -> PurchaseReturnLineItem:
    movement_id, reversed_flag = (stock_info or {}).get(line.id, (None, False))
    return PurchaseReturnLineItem(
        id=str(line.id), line_no=line.line_no, source_purchase_invoice_line_id=str(line.source_purchase_invoice_line_id),
        product_id=str(line.product_id) if line.product_id else None, description=line.description, hsn_code=line.hsn_code,
        quantity=str(line.quantity), uom=_to_unit_ref(uom), unit_price=str(line.unit_price), discount_amount=str(line.discount_amount),
        taxable_amount=str(line.taxable_amount), gst_rate=str(line.gst_rate), cgst_amount=str(line.cgst_amount),
        sgst_amount=str(line.sgst_amount), igst_amount=str(line.igst_amount), line_total=str(line.line_total),
        stock_movement_id=str(movement_id) if movement_id else None, stock_movement_reversed=reversed_flag,
    )


def _to_detail(
    purchase_return: PurchaseReturn, supplier_name: str, invoice_number: str, lines: list[tuple[PurchaseReturnLine, UnitOfMeasure]],
    stock_info: dict[uuid.UUID, tuple[uuid.UUID | None, bool]] | None = None,
) -> PurchaseReturnDetail:
    return PurchaseReturnDetail(
        **_to_list_item(purchase_return, supplier_name, invoice_number).model_dump(), reason_description=purchase_return.reason_description,
        subtotal=str(purchase_return.subtotal), discount_total=str(purchase_return.discount_total),
        taxable_total=str(purchase_return.taxable_total), cgst_total=str(purchase_return.cgst_total),
        sgst_total=str(purchase_return.sgst_total), igst_total=str(purchase_return.igst_total), tax_total=str(purchase_return.tax_total),
        notes=purchase_return.notes, accounting_posting_reference=purchase_return.accounting_posting_reference,
        gst_transaction_reference=purchase_return.gst_transaction_reference,
        lines=[_to_line_item(line, uom, stock_info) for line, uom in lines],
    )


@router.get("")
async def list_returns(
    page: int = 1, page_size: int = 25, search: str | None = None, status: str | None = None, return_reason: str | None = None,
    supplier_id: uuid.UUID | None = None, source_purchase_invoice_id: uuid.UUID | None = None,
    date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_RETURN_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)
    service = PurchaseReturnService(session)
    result = await service.list_returns(
        tenant_id=tenant_id, page=page, page_size=page_size, search=search, status_filter=status, supplier_id=supplier_id,
        return_reason_filter=return_reason, source_purchase_invoice_id=source_purchase_invoice_id, date_from=date_from, date_to=date_to,
    )
    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(ret, name, inv_num).model_dump() for ret, name, inv_num in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/{return_id}")
async def get_return(
    return_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PURCHASE_RETURN_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseReturnService(session)
    purchase_return, supplier_name, invoice_number, lines = await service.get_return(tenant_id=tenant_id, return_id=return_id)
    stock_info = await service.stock_movement_info_for_lines(tenant_id, [line.id for line, _uom in lines])
    return {"data": _to_detail(purchase_return, supplier_name, invoice_number, lines, stock_info).model_dump(), "meta": _meta()}


@router.get("/{return_id}/related-documents")
async def get_related_documents(
    return_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PURCHASE_RETURN_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseReturnService(session)
    purchase_return, invoice, order, goods_receipts = await service.get_related_documents(tenant_id=tenant_id, return_id=return_id)
    data = PurchaseReturnRelatedDocuments(
        purchase_return_id=str(purchase_return.id), source_purchase_invoice_id=str(invoice.id),
        source_purchase_invoice_number=invoice.purchase_invoice_number, source_purchase_invoice_status=invoice.status,
        source_purchase_order_id=str(order.id) if order else None, source_purchase_order_number=order.po_number if order else None,
        goods_receipts=[
            PurchaseReturnRelatedGoodsReceipt(id=str(gr.id), grn_number=gr.grn_number, document_date=gr.document_date.isoformat(), status=gr.status)
            for gr in goods_receipts
        ],
    )
    return {"data": data.model_dump(), "meta": _meta()}


@router.get("/{return_id}/audit-history")
async def get_audit_history(
    return_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PURCHASE_RETURN_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseReturnService(session)
    events = await service.get_audit_history(tenant_id=tenant_id, return_id=return_id)
    data = PurchaseReturnAuditHistory(
        purchase_return_id=str(return_id),
        events=[
            PurchaseReturnAuditEvent(
                id=str(event.id), action=event.action, actor_user_id=str(event.actor_user_id) if event.actor_user_id else None,
                occurred_at=event.occurred_at.isoformat(), before=event.before_json, after=event.after_json,
            )
            for event in events
        ],
    )
    return {"data": data.model_dump(), "meta": _meta()}


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
async def create_return(
    request: Request, payload: CreatePurchaseReturnRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_RETURN_CREATE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = PurchaseReturnService(session)
        purchase_return, supplier_name, invoice_number, lines = await service.create_return(
            tenant_id=tenant_id, actor_user_id=context.user_id, source_purchase_invoice_id=uuid.UUID(payload.source_purchase_invoice_id),
            document_date=payload.document_date, return_reason=payload.return_reason, reason_description=payload.reason_description,
            notes=payload.notes, line_inputs=payload.lines, ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": _to_detail(purchase_return, supplier_name, invoice_number, lines).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/purchase/returns", tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"), execute=_execute,
    )


@router.patch("/{return_id}")
async def update_return(
    request: Request, return_id: uuid.UUID, payload: UpdatePurchaseReturnRequest,
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_RETURN_EDIT)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseReturnService(session)
    purchase_return, supplier_name, invoice_number, lines = await service.update_return(
        tenant_id=tenant_id, actor_user_id=context.user_id, return_id=return_id, expected_row_version=payload.expected_row_version,
        document_date=payload.document_date, return_reason=payload.return_reason, reason_description=payload.reason_description,
        notes=payload.notes, line_inputs=payload.lines, ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    return {"data": _to_detail(purchase_return, supplier_name, invoice_number, lines).model_dump(), "meta": _meta()}


@router.post("/{return_id}/confirm", status_code=200)
async def confirm_return(
    request: Request, return_id: uuid.UUID, payload: PurchaseReturnActionRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_RETURN_CONFIRM)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = PurchaseReturnService(session)
        purchase_return, supplier_name, invoice_number, lines = await service.confirm_return(
            tenant_id=tenant_id, actor_user_id=context.user_id, return_id=return_id, expected_row_version=payload.expected_row_version,
            ip_address=request.client.host if request.client else "unknown",
        )
        stock_info = await service.stock_movement_info_for_lines(tenant_id, [line.id for line, _uom in lines])
        return {"data": _to_detail(purchase_return, supplier_name, invoice_number, lines, stock_info).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/purchase/returns/{return_id}/confirm", tenant_id=tenant_id,
        request_payload={"return_id": str(return_id), **payload.model_dump(mode="json")}, execute=_execute, response_status=200,
    )


@router.post("/{return_id}/cancel")
async def cancel_return(
    request: Request, return_id: uuid.UUID, payload: PurchaseReturnActionRequest,
    context: AuthenticatedContext = Depends(require_permission(PURCHASE_RETURN_CANCEL)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PurchaseReturnService(session)
    await service.cancel_return(
        tenant_id=tenant_id, actor_user_id=context.user_id, return_id=return_id, expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    purchase_return, supplier_name, invoice_number, lines = await service.get_return(tenant_id=tenant_id, return_id=return_id)
    stock_info = await service.stock_movement_info_for_lines(tenant_id, [line.id for line, _uom in lines])
    return {"data": _to_detail(purchase_return, supplier_name, invoice_number, lines, stock_info).model_dump(), "meta": _meta()}
