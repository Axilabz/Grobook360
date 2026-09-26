"""Supplier Payment endpoints (PROMPT-024).

Thin wrapper over the shared `PaymentService`, fixed to
`party_type=SUPPLIER` — mirrors `customer_receipts.py` exactly, the
mirror-image direction (§4: a caller cannot construct a wrong-party
request through this URL at all).
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
    SUPPLIER_PAYMENT_CREATE,
    SUPPLIER_PAYMENT_EDIT,
    SUPPLIER_PAYMENT_POST,
    SUPPLIER_PAYMENT_REVERSE,
    SUPPLIER_PAYMENT_VIEW,
)
from app.db.session import get_db_session
from app.models.payment import SUPPLIER, Payment
from app.models.payment_allocation import PaymentAllocation
from app.models.purchase_invoice import PurchaseInvoice
from app.models.sales_invoice import SalesInvoice
from app.schemas.envelopes import Pagination
from app.schemas.payments import (
    ChequeStatusRequest,
    CreateSupplierPaymentRequest,
    OutstandingInvoicesResponse,
    PaymentActionRequest,
    PaymentAllocationItem,
    PaymentDetail,
    PaymentListItem,
    UpdatePaymentRequest,
)
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.payments.payment_service import PaymentService

router = APIRouter(prefix="/supplier-payments", tags=["supplier-payments"])


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


def _to_list_item(
    payment: Payment, party_name: str, created_by_name: str | None = None, updated_by_name: str | None = None
) -> PaymentListItem:
    return PaymentListItem(
        id=str(payment.id), payment_number=payment.payment_number, party_type=payment.party_type,
        customer_id=str(payment.customer_id) if payment.customer_id else None,
        supplier_id=str(payment.supplier_id) if payment.supplier_id else None,
        party_name=party_name, payment_date=payment.payment_date.isoformat(), payment_method=payment.payment_method,
        amount=str(payment.amount), allocated_amount=str(payment.allocated_amount), unallocated_amount=str(payment.unallocated_amount),
        status=payment.status, cheque_status=payment.cheque_status,
        created_by=str(payment.created_by) if payment.created_by else None,
        created_by_name=created_by_name, updated_by_name=updated_by_name,
        created_at=payment.created_at.isoformat(), updated_at=payment.updated_at.isoformat(), row_version=payment.row_version,
    )


async def _to_allocation_item(session: AsyncSession, allocation: PaymentAllocation) -> PaymentAllocationItem:
    if allocation.sales_invoice_id:
        result = await session.execute(select(SalesInvoice.invoice_number).where(SalesInvoice.id == allocation.sales_invoice_id))
        return PaymentAllocationItem(
            id=str(allocation.id), invoice_id=str(allocation.sales_invoice_id), invoice_type="SALES_INVOICE",
            invoice_number=result.scalar_one(), allocated_amount=str(allocation.allocated_amount),
        )
    result = await session.execute(select(PurchaseInvoice.purchase_invoice_number).where(PurchaseInvoice.id == allocation.purchase_invoice_id))
    return PaymentAllocationItem(
        id=str(allocation.id), invoice_id=str(allocation.purchase_invoice_id), invoice_type="PURCHASE_INVOICE",
        invoice_number=result.scalar_one(), allocated_amount=str(allocation.allocated_amount),
    )


async def _to_detail(
    session: AsyncSession, payment: Payment, party_name: str, allocations: list[PaymentAllocation],
    created_by_name: str | None = None, updated_by_name: str | None = None,
) -> PaymentDetail:
    allocation_items = [await _to_allocation_item(session, a) for a in allocations]
    return PaymentDetail(
        **_to_list_item(payment, party_name, created_by_name, updated_by_name).model_dump(),
        reference_number=payment.reference_number, notes=payment.notes, client_transaction_id=payment.client_transaction_id,
        cheque_number=payment.cheque_number, cheque_date=payment.cheque_date.isoformat() if payment.cheque_date else None,
        cheque_bank_name=payment.cheque_bank_name, cleared_date=payment.cleared_date.isoformat() if payment.cleared_date else None,
        accounting_posting_reference=payment.accounting_posting_reference, allocations=allocation_items,
    )


@router.get("")
async def list_payments(
    page: int = 1, page_size: int = 25, search: str | None = None, status: str | None = None,
    supplier_id: uuid.UUID | None = None, payment_method: str | None = None,
    date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(SUPPLIER_PAYMENT_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)
    service = PaymentService(session)
    result = await service.list_payments(
        tenant_id=tenant_id, party_type=SUPPLIER, page=page, page_size=page_size, search=search, status_filter=status,
        party_id=supplier_id, payment_method_filter=payment_method, date_from=date_from, date_to=date_to,
    )
    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(p, name, cbn, ubn).model_dump() for p, name, cbn, ubn in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/outstanding-invoices")
async def outstanding_invoices(
    supplier_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(SUPPLIER_PAYMENT_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PaymentService(session)
    party_name, invoices = await service.get_outstanding_invoices(tenant_id=tenant_id, party_type=SUPPLIER, party_id=supplier_id)
    data = OutstandingInvoicesResponse(
        party_type=SUPPLIER, party_id=str(supplier_id), party_name=party_name,
        invoices=[
            {
                "invoice_id": str(inv.invoice_id), "invoice_number": inv.invoice_number, "invoice_date": inv.invoice_date.isoformat(),
                "invoice_total": str(inv.invoice_total), "paid_amount": str(inv.paid_amount),
                "outstanding_amount": str(inv.outstanding_amount), "payment_status": inv.payment_status,
            }
            for inv in invoices
        ],
    )
    return {"data": data.model_dump(), "meta": _meta()}


@router.get("/{payment_id}")
async def get_payment(
    payment_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(SUPPLIER_PAYMENT_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PaymentService(session)
    payment, party_name, created_by_name, updated_by_name, allocations = await service.get_payment(tenant_id=tenant_id, payment_id=payment_id)
    return {"data": (await _to_detail(session, payment, party_name, allocations, created_by_name, updated_by_name)).model_dump(), "meta": _meta()}


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
async def create_payment(
    request: Request, payload: CreateSupplierPaymentRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(SUPPLIER_PAYMENT_CREATE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = PaymentService(session)
        payment, party_name, allocations = await service.create_payment(
            tenant_id=tenant_id, actor_user_id=context.user_id, party_type=SUPPLIER, customer_id=None,
            supplier_id=uuid.UUID(payload.supplier_id), payment_date=payload.payment_date, payment_method=payload.payment_method,
            amount=payload.amount, reference_number=payload.reference_number, notes=payload.notes,
            client_transaction_id=payload.client_transaction_id, cheque_number=payload.cheque_number,
            cheque_date=payload.cheque_date, cheque_bank_name=payload.cheque_bank_name,
            allocation_inputs=payload.allocations, ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": (await _to_detail(session, payment, party_name, allocations)).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/supplier-payments", tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"), execute=_execute,
    )


@router.patch("/{payment_id}")
async def update_payment(
    request: Request, payment_id: uuid.UUID, payload: UpdatePaymentRequest,
    context: AuthenticatedContext = Depends(require_permission(SUPPLIER_PAYMENT_EDIT)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PaymentService(session)
    payment, party_name, allocations = await service.update_payment(
        tenant_id=tenant_id, actor_user_id=context.user_id, payment_id=payment_id, expected_row_version=payload.expected_row_version,
        payment_date=payload.payment_date, payment_method=payload.payment_method, amount=payload.amount,
        reference_number=payload.reference_number, notes=payload.notes, cheque_number=payload.cheque_number,
        cheque_date=payload.cheque_date, cheque_bank_name=payload.cheque_bank_name, allocation_inputs=payload.allocations,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    return {"data": (await _to_detail(session, payment, party_name, allocations)).model_dump(), "meta": _meta()}


@router.post("/{payment_id}/post", status_code=200)
async def post_payment(
    request: Request, payment_id: uuid.UUID, payload: PaymentActionRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(SUPPLIER_PAYMENT_POST)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = PaymentService(session)
        payment, party_name, allocations = await service.post_payment(
            tenant_id=tenant_id, actor_user_id=context.user_id, payment_id=payment_id, expected_row_version=payload.expected_row_version,
            ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": (await _to_detail(session, payment, party_name, allocations)).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/supplier-payments/{payment_id}/post", tenant_id=tenant_id,
        request_payload={"payment_id": str(payment_id), **payload.model_dump(mode="json")}, execute=_execute, response_status=200,
    )


@router.post("/{payment_id}/reverse")
async def reverse_payment(
    request: Request, payment_id: uuid.UUID, payload: PaymentActionRequest,
    context: AuthenticatedContext = Depends(require_permission(SUPPLIER_PAYMENT_REVERSE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PaymentService(session)
    payment, party_name, allocations = await service.reverse_payment(
        tenant_id=tenant_id, actor_user_id=context.user_id, payment_id=payment_id, expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    return {"data": (await _to_detail(session, payment, party_name, allocations)).model_dump(), "meta": _meta()}


@router.post("/{payment_id}/cheque-status")
async def update_cheque_status(
    request: Request, payment_id: uuid.UUID, payload: ChequeStatusRequest,
    context: AuthenticatedContext = Depends(require_permission(SUPPLIER_PAYMENT_POST)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = PaymentService(session)
    payment, party_name, allocations = await service.mark_cheque_status(
        tenant_id=tenant_id, actor_user_id=context.user_id, payment_id=payment_id, expected_row_version=payload.expected_row_version,
        cheque_status=payload.cheque_status, cleared_date=payload.cleared_date, ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    return {"data": (await _to_detail(session, payment, party_name, allocations)).model_dump(), "meta": _meta()}
