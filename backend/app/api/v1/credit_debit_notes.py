"""Credit Note / Debit Note endpoints (PROMPT-017).

Mirrors `sales_returns.py`'s router shape exactly. Create and post are
the duplicate-submission-sensitive operations (numbering allocation and
accounting/GST posting respectively) and require an Idempotency-Key.

Because one table/endpoint set serves BOTH note types, RBAC here checks
`note_type`-specific permissions dynamically (a credit_note.* code for a
CREDIT_NOTE row, a debit_note.* code for a DEBIT_NOTE row) rather than a
single static `require_permission(...)` dependency — see `_require_note_
permission` below.
"""

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, get_current_user
from app.core.error_codes import REG_MISSING_FIELD
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import (
    CREDIT_NOTE_CANCEL,
    CREDIT_NOTE_CREATE,
    CREDIT_NOTE_EDIT,
    CREDIT_NOTE_POST,
    CREDIT_NOTE_VIEW,
    DEBIT_NOTE_CANCEL,
    DEBIT_NOTE_CREATE,
    DEBIT_NOTE_EDIT,
    DEBIT_NOTE_POST,
    DEBIT_NOTE_VIEW,
)
from app.db.session import get_db_session
from app.models.credit_debit_note import CREDIT_NOTE, CreditDebitNote
from app.models.credit_debit_note_line import CreditDebitNoteLine
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.credit_debit_note import (
    CreateCreditDebitNoteRequest,
    CreditDebitNoteActionRequest,
    CreditDebitNoteDetail,
    CreditDebitNoteLineItem,
    CreditDebitNoteListItem,
    UpdateCreditDebitNoteRequest,
)
from app.schemas.envelopes import Pagination
from app.schemas.sales_estimate import UnitRef
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.sales.credit_debit_note_service import CreditDebitNoteService

router = APIRouter(prefix="/sales/credit-debit-notes", tags=["credit-debit-notes"])

_ACTION_PERMISSIONS = {
    ("view", CREDIT_NOTE): CREDIT_NOTE_VIEW,
    ("view", "DEBIT_NOTE"): DEBIT_NOTE_VIEW,
    ("create", CREDIT_NOTE): CREDIT_NOTE_CREATE,
    ("create", "DEBIT_NOTE"): DEBIT_NOTE_CREATE,
    ("edit", CREDIT_NOTE): CREDIT_NOTE_EDIT,
    ("edit", "DEBIT_NOTE"): DEBIT_NOTE_EDIT,
    ("post", CREDIT_NOTE): CREDIT_NOTE_POST,
    ("post", "DEBIT_NOTE"): DEBIT_NOTE_POST,
    ("cancel", CREDIT_NOTE): CREDIT_NOTE_CANCEL,
    ("cancel", "DEBIT_NOTE"): DEBIT_NOTE_CANCEL,
}


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


def _require_note_permission(context: AuthenticatedContext, action: str, note_type: str) -> None:
    permission_code = _ACTION_PERMISSIONS[(action, note_type)]
    if permission_code not in context.permissions:
        raise AuthorizationError(f"Missing required permission: {permission_code}")


def _require_any_view_permission(context: AuthenticatedContext) -> None:
    if CREDIT_NOTE_VIEW not in context.permissions and DEBIT_NOTE_VIEW not in context.permissions:
        raise AuthorizationError(f"Missing required permission: {CREDIT_NOTE_VIEW} or {DEBIT_NOTE_VIEW}")


async def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise BadRequestError("Idempotency-Key header is required for this operation", code=REG_MISSING_FIELD)
    return idempotency_key


def _to_unit_ref(unit: UnitOfMeasure) -> UnitRef:
    return UnitRef(id=str(unit.id), code=unit.code, name=unit.name)


def _to_list_item(
    note: CreditDebitNote,
    customer_name: str,
    invoice_number: str,
    created_by_name: str | None = None,
    updated_by_name: str | None = None,
) -> CreditDebitNoteListItem:
    return CreditDebitNoteListItem(
        id=str(note.id),
        note_number=note.note_number,
        note_type=note.note_type,
        note_date=note.note_date.isoformat(),
        customer_id=str(note.customer_id),
        customer_name=customer_name,
        source_invoice_id=str(note.source_invoice_id),
        source_invoice_number=invoice_number,
        status=note.status,
        reason=note.reason,
        grand_total=str(note.grand_total),
        tax_total=str(note.tax_total),
        created_by=str(note.created_by) if note.created_by else None,
        created_by_name=created_by_name,
        updated_by_name=updated_by_name,
        created_at=note.created_at.isoformat(),
        updated_at=note.updated_at.isoformat(),
        row_version=note.row_version,
    )


def _to_line_item(line: CreditDebitNoteLine, uom: UnitOfMeasure) -> CreditDebitNoteLineItem:
    return CreditDebitNoteLineItem(
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
    note: CreditDebitNote,
    customer_name: str,
    invoice_number: str,
    lines: list[tuple[CreditDebitNoteLine, UnitOfMeasure]],
    created_by_name: str | None = None,
    updated_by_name: str | None = None,
) -> CreditDebitNoteDetail:
    return CreditDebitNoteDetail(
        **_to_list_item(note, customer_name, invoice_number, created_by_name, updated_by_name).model_dump(),
        customer_gstin=note.customer_gstin,
        billing_address=note.billing_address,
        shipping_address=note.shipping_address,
        place_of_supply_state_code=note.place_of_supply_state_code,
        subtotal=str(note.subtotal),
        discount_total=str(note.discount_total),
        taxable_total=str(note.taxable_total),
        cgst_total=str(note.cgst_total),
        sgst_total=str(note.sgst_total),
        igst_total=str(note.igst_total),
        notes=note.notes,
        accounting_posting_reference=note.accounting_posting_reference,
        gst_transaction_reference=note.gst_transaction_reference,
        lines=[_to_line_item(line, uom) for line, uom in lines],
    )


@router.get("")
async def list_notes(
    request: Request,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    note_type: str | None = None,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    source_invoice_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    context: AuthenticatedContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    _require_any_view_permission(context)
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)

    # A caller with only one of the two view permissions sees only that
    # note type's rows — never a permission-bypassing peek at the other.
    effective_type_filter = note_type
    if CREDIT_NOTE_VIEW not in context.permissions:
        effective_type_filter = "DEBIT_NOTE"
    elif DEBIT_NOTE_VIEW not in context.permissions:
        effective_type_filter = CREDIT_NOTE

    service = CreditDebitNoteService(session)
    result = await service.list_notes(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        search=search,
        note_type_filter=effective_type_filter,
        status_filter=status,
        customer_id=customer_id,
        source_invoice_id=source_invoice_id,
        date_from=date_from,
        date_to=date_to,
    )

    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(note, name, inv_num, cbn, ubn).model_dump() for note, name, inv_num, cbn, ubn in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/{note_id}")
async def get_note(
    note_id: uuid.UUID,
    context: AuthenticatedContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = CreditDebitNoteService(session)
    note, customer_name, invoice_number, created_by_name, updated_by_name, lines = await service.get_note(tenant_id=tenant_id, note_id=note_id)
    _require_note_permission(context, "view", note.note_type)
    return {"data": _to_detail(note, customer_name, invoice_number, lines, created_by_name, updated_by_name).model_dump(), "meta": _meta()}


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
async def create_note(
    request: Request,
    payload: CreateCreditDebitNoteRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    _require_note_permission(context, "create", payload.note_type)
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = CreditDebitNoteService(session)
        note, customer_name, invoice_number, lines = await service.create_note(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            source_invoice_id=uuid.UUID(payload.source_invoice_id),
            note_type=payload.note_type,
            note_date=payload.note_date,
            reason=payload.reason,
            notes=payload.notes,
            line_inputs=payload.lines,
            ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": _to_detail(note, customer_name, invoice_number, lines).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/sales/credit-debit-notes",
        tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"),
        execute=_execute,
    )


@router.patch("/{note_id}")
async def update_note(
    request: Request,
    note_id: uuid.UUID,
    payload: UpdateCreditDebitNoteRequest,
    context: AuthenticatedContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = CreditDebitNoteService(session)
    existing, _name, _inv, _cbn, _ubn, _lines = await service.get_note(tenant_id=tenant_id, note_id=note_id)
    _require_note_permission(context, "edit", existing.note_type)

    note, customer_name, invoice_number, lines = await service.update_note(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        note_id=note_id,
        expected_row_version=payload.expected_row_version,
        note_date=payload.note_date,
        reason=payload.reason,
        notes=payload.notes,
        line_inputs=payload.lines,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_detail(note, customer_name, invoice_number, lines).model_dump(), "meta": _meta()}


@router.post("/{note_id}/post", status_code=200)
async def post_note(
    request: Request,
    note_id: uuid.UUID,
    payload: CreditDebitNoteActionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    service = CreditDebitNoteService(session)
    existing, _name, _inv, _cbn, _ubn, _lines = await service.get_note(tenant_id=tenant_id, note_id=note_id)
    _require_note_permission(context, "post", existing.note_type)

    async def _execute() -> dict:
        note, customer_name, invoice_number, lines = await service.post_note(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            note_id=note_id,
            expected_row_version=payload.expected_row_version,
            ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": _to_detail(note, customer_name, invoice_number, lines).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/sales/credit-debit-notes/{note_id}/post",
        tenant_id=tenant_id,
        request_payload={"note_id": str(note_id), **payload.model_dump(mode="json")},
        execute=_execute,
        response_status=200,
    )


@router.post("/{note_id}/cancel")
async def cancel_note(
    request: Request,
    note_id: uuid.UUID,
    payload: CreditDebitNoteActionRequest,
    context: AuthenticatedContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = CreditDebitNoteService(session)
    existing, _name, _inv, _cbn, _ubn, _lines = await service.get_note(tenant_id=tenant_id, note_id=note_id)
    _require_note_permission(context, "cancel", existing.note_type)

    note = await service.cancel_note(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        note_id=note_id,
        expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    _, customer_name, invoice_number, created_by_name, updated_by_name, lines = await service.get_note(tenant_id=tenant_id, note_id=note.id)
    return {"data": _to_detail(note, customer_name, invoice_number, lines, created_by_name, updated_by_name).model_dump(), "meta": _meta()}
