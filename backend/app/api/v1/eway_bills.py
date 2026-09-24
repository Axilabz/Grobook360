"""E-Way Bill endpoints (PROMPT-018).

Top-level `/eway-bills` router per §27's suggested convention (E-Way
Bill is not nested under `/sales/invoices` in the API surface, even
though this MVP's only supported source is a Sales Invoice — see
`eway_bill.py`'s model docstring on `source_type`). A convenience
`GET /sales/invoices/{invoice_id}/eway-bill` is also exposed for the
invoice detail screen, mirroring `einvoice.py`'s own GET shape.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.error_codes import REG_MISSING_FIELD
from app.core.exceptions import AppError, AuthorizationError, BadRequestError
from app.core.permissions import EWAY_BILL_CANCEL, EWAY_BILL_GENERATE, EWAY_BILL_VIEW
from app.db.session import get_db_session
from app.models.eway_bill import EwayBill
from app.schemas.gst_integration import EwayBillCancelRequest, EwayBillDetail, GenerateEwayBillRequest
from app.services.gst_integration.eway_bill_service import EWayBillService
from app.services.idempotency.idempotency_service import IdempotencyService

router = APIRouter(prefix="/eway-bills", tags=["eway-bills"])
invoice_router = APIRouter(prefix="/sales/invoices", tags=["eway-bills"])


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


def _to_detail(record: EwayBill | None, invoice_id: uuid.UUID | None = None) -> EwayBillDetail:
    if record is None:
        return EwayBillDetail(
            id=None, sales_invoice_id=str(invoice_id) if invoice_id else "", status="READY", applicable=None,
            applicability_reason=None, eway_bill_number=None, valid_from=None, valid_until=None, transport_mode=None,
            vehicle_number=None, transporter_id=None, transporter_name=None, distance_km=None, provider_reference=None,
            provider_response_message=None, generated_at=None, cancelled_at=None, cancellation_reason=None,
            row_version=None, updated_at=None,
        )
    applicability = record.applicability_result or {}
    return EwayBillDetail(
        id=str(record.id),
        sales_invoice_id=str(record.sales_invoice_id),
        status=record.status,
        applicable=applicability.get("applicable"),
        applicability_reason=applicability.get("reason"),
        eway_bill_number=record.eway_bill_number,
        valid_from=record.valid_from.isoformat() if record.valid_from else None,
        valid_until=record.valid_until.isoformat() if record.valid_until else None,
        transport_mode=record.transport_mode,
        vehicle_number=record.vehicle_number,
        transporter_id=record.transporter_id,
        transporter_name=record.transporter_name,
        distance_km=str(record.distance_km) if record.distance_km is not None else None,
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


@invoice_router.get("/{invoice_id}/eway-bill")
async def get_eway_bill_by_invoice(
    invoice_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(EWAY_BILL_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = EWayBillService(session)
    _invoice, record = await service.get_status_by_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
    return {"data": _to_detail(record, invoice_id).model_dump(), "meta": _meta()}


@router.get("/{eway_bill_id}")
async def get_eway_bill(
    eway_bill_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(EWAY_BILL_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = EWayBillService(session)
    record = await service.get(tenant_id=tenant_id, eway_bill_id=eway_bill_id)
    return {"data": _to_detail(record).model_dump(), "meta": _meta()}


@router.post("/generate", status_code=201)
async def generate_eway_bill(
    request: Request,
    payload: GenerateEwayBillRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(EWAY_BILL_GENERATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)
    client_ip = request.client.host if request.client else "unknown"

    async def _execute() -> dict:
        service = EWayBillService(session)
        try:
            record = await service.generate(
                tenant_id=tenant_id, actor_user_id=context.user_id, invoice_id=uuid.UUID(payload.invoice_id),
                transport_mode=payload.transport_mode, vehicle_number=payload.vehicle_number,
                transporter_id=payload.transporter_id, transporter_name=payload.transporter_name,
                distance_km=payload.distance_km, ip_address=client_ip,
            )
        except AppError:
            await session.commit()
            raise
        return {"data": _to_detail(record).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/eway-bills/generate",
        tenant_id=tenant_id, request_payload=payload.model_dump(mode="json"), execute=_execute, response_status=201,
    )


@router.post("/{eway_bill_id}/status", status_code=200)
async def refresh_eway_bill_status(
    request: Request,
    eway_bill_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(EWAY_BILL_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"
    service = EWayBillService(session)
    try:
        record = await service.refresh_status(
            tenant_id=tenant_id, actor_user_id=context.user_id, eway_bill_id=eway_bill_id, ip_address=client_ip
        )
    except AppError:
        await session.commit()
        raise
    await session.commit()
    return {"data": _to_detail(record).model_dump(), "meta": _meta()}


@router.post("/{eway_bill_id}/cancel", status_code=200)
async def cancel_eway_bill(
    request: Request,
    eway_bill_id: uuid.UUID,
    payload: EwayBillCancelRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(EWAY_BILL_CANCEL)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)
    client_ip = request.client.host if request.client else "unknown"

    async def _execute() -> dict:
        service = EWayBillService(session)
        try:
            record = await service.cancel(
                tenant_id=tenant_id, actor_user_id=context.user_id, eway_bill_id=eway_bill_id,
                reason=payload.reason, ip_address=client_ip,
            )
        except AppError:
            await session.commit()
            raise
        return {"data": _to_detail(record).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session, idempotency_key=key, endpoint="POST /api/v1/eway-bills/{eway_bill_id}/cancel",
        tenant_id=tenant_id, request_payload={"eway_bill_id": str(eway_bill_id), **payload.model_dump()}, execute=_execute,
    )
