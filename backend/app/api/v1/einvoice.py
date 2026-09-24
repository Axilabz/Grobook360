"""E-Invoice endpoints (PROMPT-018).

Mounted under the existing `/sales/invoices` prefix (a separate router
file, same prefix — FastAPI supports this, matching how PROMPT-016/017
added endpoints to OTHER existing routers rather than duplicating logic;
this one is a new file because of its own size). Generate/cancel require
an Idempotency-Key (the HTTP-level replay guard — the deeper
generate-vs-generate-again duplicate-IRN guard lives in
`EInvoiceService` itself via row locking, per that module's docstring).

Every mutating action follows the established "commit a failure state
before re-raising" pattern (see `app/api/v1/auth.py`'s login handler for
the precedent) — `EInvoiceService.generate`/`.cancel`/`.refresh_status`
deliberately flush intermediate state (e.g. marking a record FAILED/
NOT_APPLICABLE/STATUS_UNKNOWN) before raising an error response; without
an explicit commit here, that state would be silently rolled back when
the uncommitted session closes, defeating the entire point of persisting
it for operator visibility.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.error_codes import REG_MISSING_FIELD
from app.core.exceptions import AppError, AuthorizationError, BadRequestError
from app.core.permissions import EINVOICE_CANCEL, EINVOICE_GENERATE, EINVOICE_VIEW
from app.db.session import get_db_session
from app.models.einvoice import Einvoice
from app.schemas.gst_integration import EinvoiceCancelRequest, EinvoiceDetail
from app.services.gst_integration.einvoice_service import EInvoiceService
from app.services.idempotency.idempotency_service import IdempotencyService

router = APIRouter(prefix="/sales/invoices", tags=["einvoice"])


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


def _to_detail(invoice_id: uuid.UUID, record: Einvoice | None) -> EinvoiceDetail:
    if record is None:
        return EinvoiceDetail(
            id=None, sales_invoice_id=str(invoice_id), status="READY", applicable=None, applicability_reason=None,
            irn=None, ack_number=None, ack_date=None, has_signed_qr=False, provider_reference=None,
            provider_response_message=None, generated_at=None, cancelled_at=None, cancellation_reason=None,
            row_version=None, updated_at=None,
        )
    applicability = record.applicability_result or {}
    return EinvoiceDetail(
        id=str(record.id),
        sales_invoice_id=str(record.sales_invoice_id),
        status=record.status,
        applicable=applicability.get("applicable"),
        applicability_reason=applicability.get("reason"),
        irn=record.irn,
        ack_number=record.ack_number,
        ack_date=record.ack_date.isoformat() if record.ack_date else None,
        has_signed_qr=bool(record.signed_qr_data),
        provider_reference=record.provider_reference,
        provider_response_message=record.provider_response_message,
        generated_at=record.generated_at.isoformat() if record.generated_at else None,
        cancelled_at=record.cancelled_at.isoformat() if record.cancelled_at else None,
        cancellation_reason=record.cancellation_reason,
        row_version=record.row_version,
        updated_at=record.updated_at.isoformat() if record.updated_at else None,
    )


async def _idempotent_post(
    *, session: AsyncSession, idempotency_key: str, endpoint: str, tenant_id: uuid.UUID,
    request_payload: dict, execute, response_status: int = 200,
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


@router.get("/{invoice_id}/einvoice")
async def get_einvoice(
    invoice_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(EINVOICE_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = EInvoiceService(session)
    _invoice, record = await service.get_status(tenant_id=tenant_id, invoice_id=invoice_id)
    return {"data": _to_detail(invoice_id, record).model_dump(), "meta": _meta()}


@router.post("/{invoice_id}/einvoice/generate", status_code=200)
async def generate_einvoice(
    request: Request,
    invoice_id: uuid.UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(EINVOICE_GENERATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)
    client_ip = request.client.host if request.client else "unknown"

    async def _execute() -> dict:
        service = EInvoiceService(session)
        try:
            record = await service.generate(
                tenant_id=tenant_id, actor_user_id=context.user_id, invoice_id=invoice_id, ip_address=client_ip
            )
        except AppError:
            await session.commit()  # persist whatever failure/interim state was flushed
            raise
        return {"data": _to_detail(invoice_id, record).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/sales/invoices/{invoice_id}/einvoice/generate",
        tenant_id=tenant_id, request_payload={"invoice_id": str(invoice_id)}, execute=_execute,
    )


@router.post("/{invoice_id}/einvoice/status", status_code=200)
async def refresh_einvoice_status(
    request: Request,
    invoice_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(EINVOICE_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"
    service = EInvoiceService(session)
    try:
        record = await service.refresh_status(
            tenant_id=tenant_id, actor_user_id=context.user_id, invoice_id=invoice_id, ip_address=client_ip
        )
    except AppError:
        await session.commit()
        raise
    await session.commit()
    return {"data": _to_detail(invoice_id, record).model_dump(), "meta": _meta()}


@router.post("/{invoice_id}/einvoice/cancel", status_code=200)
async def cancel_einvoice(
    request: Request,
    invoice_id: uuid.UUID,
    payload: EinvoiceCancelRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(EINVOICE_CANCEL)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)
    client_ip = request.client.host if request.client else "unknown"

    async def _execute() -> dict:
        service = EInvoiceService(session)
        try:
            record = await service.cancel(
                tenant_id=tenant_id, actor_user_id=context.user_id, invoice_id=invoice_id,
                reason=payload.reason, ip_address=client_ip,
            )
        except AppError:
            await session.commit()
            raise
        return {"data": _to_detail(invoice_id, record).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/sales/invoices/{invoice_id}/einvoice/cancel",
        tenant_id=tenant_id, request_payload={"invoice_id": str(invoice_id), **payload.model_dump()}, execute=_execute,
    )
