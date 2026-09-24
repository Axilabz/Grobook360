"""Sales Estimate endpoints (PROMPT-012).

Mirrors the established router shape exactly (customers.py/products.py):
thin router, permission-code authorization, tenant context resolved
server-side only. Create and convert are state-mutating "financial"
operations and require an Idempotency-Key header (§24), reusing the same
`IdempotencyService` pattern as PROMPT-010's inventory endpoints and
PROMPT-002's sign-up.
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
    SALES_ESTIMATE_ACCEPT,
    SALES_ESTIMATE_CANCEL,
    SALES_ESTIMATE_CONVERT,
    SALES_ESTIMATE_CREATE,
    SALES_ESTIMATE_EDIT,
    SALES_ESTIMATE_REJECT,
    SALES_ESTIMATE_SEND,
    SALES_ESTIMATE_VIEW,
)
from app.db.session import get_db_session
from app.models.sales_estimate import ACCEPTED, DRAFT, SENT, SalesEstimate
from app.models.sales_estimate_line import SalesEstimateLine
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.envelopes import Pagination
from app.schemas.sales_estimate import (
    ConversionResult,
    CreateEstimateRequest,
    EstimateActionRequest,
    EstimateDetail,
    EstimateLineItem,
    EstimateListItem,
    UnitRef,
    UpdateEstimateRequest,
)
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.sales.estimate_service import EstimateService
from app.services.sales.sales_order_service import SalesOrderService

router = APIRouter(prefix="/sales/estimates", tags=["sales-estimates"])


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


def _to_list_item(estimate: SalesEstimate, customer_name: str) -> EstimateListItem:
    is_expired_display = bool(
        estimate.valid_until_date
        and estimate.valid_until_date < date.today()
        and estimate.status in (DRAFT, SENT, ACCEPTED)
    )
    return EstimateListItem(
        id=str(estimate.id),
        estimate_number=estimate.estimate_number,
        document_date=estimate.document_date.isoformat(),
        valid_until_date=estimate.valid_until_date.isoformat() if estimate.valid_until_date else None,
        customer_id=str(estimate.customer_id),
        customer_name=customer_name,
        status=estimate.status,
        is_expired_display=is_expired_display,
        grand_total=str(estimate.grand_total),
        created_by=str(estimate.created_by) if estimate.created_by else None,
        created_at=estimate.created_at.isoformat(),
        updated_at=estimate.updated_at.isoformat(),
        row_version=estimate.row_version,
    )


def _to_line_item(line: SalesEstimateLine, uom: UnitOfMeasure) -> EstimateLineItem:
    return EstimateLineItem(
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
    )


def _to_detail(
    estimate: SalesEstimate, customer_name: str, lines: list[tuple[SalesEstimateLine, UnitOfMeasure]]
) -> EstimateDetail:
    return EstimateDetail(
        **_to_list_item(estimate, customer_name).model_dump(),
        customer_gstin=estimate.customer_gstin,
        billing_address=estimate.billing_address,
        place_of_supply_state_code=estimate.place_of_supply_state_code,
        subtotal=str(estimate.subtotal),
        discount_total=str(estimate.discount_total),
        taxable_total=str(estimate.taxable_total),
        cgst_total=str(estimate.cgst_total),
        sgst_total=str(estimate.sgst_total),
        igst_total=str(estimate.igst_total),
        tax_total=str(estimate.tax_total),
        notes=estimate.notes,
        converted_at=estimate.converted_at.isoformat() if estimate.converted_at else None,
        lines=[_to_line_item(line, uom) for line, uom in lines],
    )


@router.get("")
async def list_estimates(
    request: Request,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(SALES_ESTIMATE_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)

    service = EstimateService(session)
    result = await service.list_estimates(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        search=search,
        status_filter=status,
        customer_id=customer_id,
        date_from=date_from,
        date_to=date_to,
    )

    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(e, name).model_dump() for e, name in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/{estimate_id}")
async def get_estimate(
    estimate_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(SALES_ESTIMATE_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = EstimateService(session)
    estimate, customer_name, lines = await service.get_estimate(tenant_id=tenant_id, estimate_id=estimate_id)
    await session.commit()  # persist any lazy expiry transition
    return {"data": _to_detail(estimate, customer_name, lines).model_dump(), "meta": _meta()}


async def _idempotent_post(
    *, session: AsyncSession, idempotency_key: str, endpoint: str, tenant_id: uuid.UUID, request_payload: dict, execute
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
        response_status=201,
        response_body=response_body,
    )
    await session.commit()
    return response_body


@router.post("", status_code=201)
async def create_estimate(
    request: Request,
    payload: CreateEstimateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(SALES_ESTIMATE_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        service = EstimateService(session)
        estimate, customer_name, lines = await service.create_estimate(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            customer_id=uuid.UUID(payload.customer_id),
            document_date=payload.document_date,
            valid_until_date=payload.valid_until_date,
            notes=payload.notes,
            line_inputs=payload.lines,
            ip_address=request.client.host if request.client else "unknown",
        )
        return {"data": _to_detail(estimate, customer_name, lines).model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/sales/estimates",
        tenant_id=tenant_id,
        request_payload=payload.model_dump(mode="json"),
        execute=_execute,
    )


@router.patch("/{estimate_id}")
async def update_estimate(
    request: Request,
    estimate_id: uuid.UUID,
    payload: UpdateEstimateRequest,
    context: AuthenticatedContext = Depends(require_permission(SALES_ESTIMATE_EDIT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = EstimateService(session)
    estimate, customer_name, lines = await service.update_estimate(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        estimate_id=estimate_id,
        expected_row_version=payload.expected_row_version,
        customer_id=uuid.UUID(payload.customer_id) if payload.customer_id else None,
        document_date=payload.document_date,
        valid_until_date=payload.valid_until_date,
        notes=payload.notes,
        line_inputs=payload.lines,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_detail(estimate, customer_name, lines).model_dump(), "meta": _meta()}


async def _run_transition(
    *, session: AsyncSession, tenant_id: uuid.UUID, context: AuthenticatedContext, estimate_id: uuid.UUID,
    payload: EstimateActionRequest, request: Request, action_fn,
) -> dict:
    service = EstimateService(session)
    estimate = await action_fn(
        service,
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        estimate_id=estimate_id,
        expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    _, customer_name, lines = await service.get_estimate(tenant_id=tenant_id, estimate_id=estimate.id)
    return {"data": _to_detail(estimate, customer_name, lines).model_dump(), "meta": _meta()}


@router.post("/{estimate_id}/send")
async def send_estimate(
    request: Request,
    estimate_id: uuid.UUID,
    payload: EstimateActionRequest,
    context: AuthenticatedContext = Depends(require_permission(SALES_ESTIMATE_SEND)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    return await _run_transition(
        session=session, tenant_id=tenant_id, context=context, estimate_id=estimate_id, payload=payload,
        request=request, action_fn=lambda svc, **kw: svc.send_estimate(**kw),
    )


@router.post("/{estimate_id}/accept")
async def accept_estimate(
    request: Request,
    estimate_id: uuid.UUID,
    payload: EstimateActionRequest,
    context: AuthenticatedContext = Depends(require_permission(SALES_ESTIMATE_ACCEPT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    return await _run_transition(
        session=session, tenant_id=tenant_id, context=context, estimate_id=estimate_id, payload=payload,
        request=request, action_fn=lambda svc, **kw: svc.accept_estimate(**kw),
    )


@router.post("/{estimate_id}/reject")
async def reject_estimate(
    request: Request,
    estimate_id: uuid.UUID,
    payload: EstimateActionRequest,
    context: AuthenticatedContext = Depends(require_permission(SALES_ESTIMATE_REJECT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    return await _run_transition(
        session=session, tenant_id=tenant_id, context=context, estimate_id=estimate_id, payload=payload,
        request=request, action_fn=lambda svc, **kw: svc.reject_estimate(**kw),
    )


@router.post("/{estimate_id}/cancel")
async def cancel_estimate(
    request: Request,
    estimate_id: uuid.UUID,
    payload: EstimateActionRequest,
    context: AuthenticatedContext = Depends(require_permission(SALES_ESTIMATE_CANCEL)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    return await _run_transition(
        session=session, tenant_id=tenant_id, context=context, estimate_id=estimate_id, payload=payload,
        request=request, action_fn=lambda svc, **kw: svc.cancel_estimate(**kw),
    )


@router.post("/{estimate_id}/convert-to-sales-order", status_code=201)
async def convert_estimate(
    request: Request,
    estimate_id: uuid.UUID,
    payload: EstimateActionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(SALES_ESTIMATE_CONVERT)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        # PROMPT-013: SalesOrderService.create_from_estimate delegates the
        # Estimate-side eligibility/locking to EstimateService internally
        # (same session/transaction — see that method's docstring for why
        # this keeps the whole conversion atomic), then builds the real
        # Sales Order.
        order_service = SalesOrderService(session)
        order, _customer_name, _lines, estimate = await order_service.create_from_estimate(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            estimate_id=estimate_id,
            expected_row_version=payload.expected_row_version,
            ip_address=request.client.host if request.client else "unknown",
        )
        result = ConversionResult(
            estimate_id=str(estimate.id),
            status=estimate.status,
            converted_at=estimate.converted_at.isoformat() if estimate.converted_at else None,
            sales_order_id=str(order.id),
            message=f"Estimate converted to Sales Order {order.order_number}.",
        )
        return {"data": result.model_dump(), "meta": _meta()}

    return await _idempotent_post(
        session=session,
        idempotency_key=key,
        endpoint="POST /api/v1/sales/estimates/{estimate_id}/convert-to-sales-order",
        tenant_id=tenant_id,
        request_payload={"estimate_id": str(estimate_id), **payload.model_dump(mode="json")},
        execute=_execute,
    )
