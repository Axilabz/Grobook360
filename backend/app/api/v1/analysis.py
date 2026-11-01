"""Analysis page endpoints (BI module, Phase 1).

READ-ONLY, same discipline as `app/api/v1/reports.py` (§53 of that
module's own docstring): `tenant_id` always comes from the authenticated
session context, never a client-supplied parameter. Gated by the
EXISTING `reports.view_*` permission codes — Analysis is an alternate,
interactive VIEW over the same authorized data Reports already exposes,
not a new data domain, so no new permission codes or migration were
added for it (see the approved plan's Architecture Decision #1).
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.error_codes import REPORT_INVALID_DATE_RANGE
from app.core.exceptions import AuthorizationError, ValidationAppError
from app.core.permissions import REPORTS_VIEW_DASHBOARD, REPORTS_VIEW_INVENTORY, REPORTS_VIEW_PURCHASE, REPORTS_VIEW_SALES
from app.db.session import get_db_session
from app.models.tenant import Tenant
from app.services.analysis.analysis_service import AnalysisService
from app.services.analysis.period_utils import (
    ANALYSIS_PERIODS,
    COMPARISON_MODES,
    CUSTOM,
    THIS_MONTH,
    resolve_analysis_period,
    resolve_comparison_period,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])


async def _get_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    return result.scalar_one()


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


def _jsonify(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    return value


async def _resolve_dates(
    *, session: AsyncSession, tenant_id: uuid.UUID, period: str, date_from: date | None, date_to: date | None,
    compare_mode: str, compare_from: date | None, compare_to: date | None,
) -> dict:
    if period not in ANALYSIS_PERIODS:
        raise ValidationAppError(f"Unknown analysis period '{period}'.", code=REPORT_INVALID_DATE_RANGE)
    if period == CUSTOM and date_from is not None and date_to is not None and date_from > date_to:
        raise ValidationAppError("date_from must not be after date_to.", code=REPORT_INVALID_DATE_RANGE)
    if compare_mode not in COMPARISON_MODES:
        raise ValidationAppError(f"Unknown comparison mode '{compare_mode}'.", code=REPORT_INVALID_DATE_RANGE)

    tenant = await _get_tenant(session, tenant_id)
    resolved_from, resolved_to = resolve_analysis_period(tenant=tenant, period=period, custom_from=date_from, custom_to=date_to)
    comparison = resolve_comparison_period(mode=compare_mode, date_from=resolved_from, date_to=resolved_to, custom_from=compare_from, custom_to=compare_to)
    return {
        "date_from": resolved_from, "date_to": resolved_to,
        "compare_from": comparison[0] if comparison else None, "compare_to": comparison[1] if comparison else None,
    }


@router.get("/overview")
async def get_overview(
    period: str = THIS_MONTH, date_from: date | None = None, date_to: date | None = None,
    compare: str = "NONE", compare_from: date | None = None, compare_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_DASHBOARD)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    resolved = await _resolve_dates(session=session, tenant_id=tenant_id, period=period, date_from=date_from, date_to=date_to, compare_mode=compare, compare_from=compare_from, compare_to=compare_to)
    data = await AnalysisService(session).get_overview(tenant_id=tenant_id, **resolved)
    return {"data": _jsonify(data), "meta": {**_meta(), "period": _jsonify({k: v for k, v in resolved.items()})}}


@router.get("/sales")
async def get_sales_analysis(
    period: str = THIS_MONTH, date_from: date | None = None, date_to: date | None = None,
    compare: str = "NONE", compare_from: date | None = None, compare_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_SALES)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    resolved = await _resolve_dates(session=session, tenant_id=tenant_id, period=period, date_from=date_from, date_to=date_to, compare_mode=compare, compare_from=compare_from, compare_to=compare_to)
    data = await AnalysisService(session).get_sales_analysis(tenant_id=tenant_id, **resolved)
    return {"data": _jsonify(data), "meta": {**_meta(), "period": _jsonify({k: v for k, v in resolved.items()})}}


@router.get("/sales-by-user")
async def get_sales_by_user(
    period: str = THIS_MONTH, date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_SALES)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    """How many sales (POSTED Sales Invoices) each staff member has made.
    Reuses reports.view_sales — same convention as every other Analysis
    endpoint, no new permission code. Per the approved plan's explicit
    product decision: Owner/Manager see every staff member's figures;
    a Salesperson sees only their own row — enforced HERE, server-side,
    not left to the frontend to hide (this codebase's "backend
    authorization is always authoritative" rule)."""
    tenant_id = _require_tenant(context)
    resolved = await _resolve_dates(session=session, tenant_id=tenant_id, period=period, date_from=date_from, date_to=date_to, compare_mode="NONE", compare_from=None, compare_to=None)
    restrict_to_user_id = context.user_id if context.role == "SALESPERSON" else None
    data = await AnalysisService(session).get_sales_by_user(
        tenant_id=tenant_id, date_from=resolved["date_from"], date_to=resolved["date_to"], restrict_to_user_id=restrict_to_user_id,
    )
    return {"data": _jsonify(data), "meta": {**_meta(), "period": _jsonify({k: v for k, v in resolved.items()})}}


@router.get("/products")
async def get_product_analysis(
    period: str = THIS_MONTH, date_from: date | None = None, date_to: date | None = None,
    compare: str = "NONE", compare_from: date | None = None, compare_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_SALES)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    resolved = await _resolve_dates(session=session, tenant_id=tenant_id, period=period, date_from=date_from, date_to=date_to, compare_mode=compare, compare_from=compare_from, compare_to=compare_to)
    data = await AnalysisService(session).get_product_analysis(tenant_id=tenant_id, **resolved)
    return {"data": _jsonify(data), "meta": {**_meta(), "period": _jsonify({k: v for k, v in resolved.items()})}}


@router.get("/customers")
async def get_customer_analysis(
    period: str = THIS_MONTH, date_from: date | None = None, date_to: date | None = None,
    compare: str = "NONE", compare_from: date | None = None, compare_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_SALES)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    resolved = await _resolve_dates(session=session, tenant_id=tenant_id, period=period, date_from=date_from, date_to=date_to, compare_mode=compare, compare_from=compare_from, compare_to=compare_to)
    data = await AnalysisService(session).get_customer_analysis(tenant_id=tenant_id, **resolved)
    return {"data": _jsonify(data), "meta": {**_meta(), "period": _jsonify({k: v for k, v in resolved.items()})}}


@router.get("/purchases")
async def get_purchase_analysis(
    period: str = THIS_MONTH, date_from: date | None = None, date_to: date | None = None,
    compare: str = "NONE", compare_from: date | None = None, compare_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_PURCHASE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    resolved = await _resolve_dates(session=session, tenant_id=tenant_id, period=period, date_from=date_from, date_to=date_to, compare_mode=compare, compare_from=compare_from, compare_to=compare_to)
    data = await AnalysisService(session).get_purchase_analysis(tenant_id=tenant_id, **resolved)
    return {"data": _jsonify(data), "meta": {**_meta(), "period": _jsonify({k: v for k, v in resolved.items()})}}


@router.get("/inventory")
async def get_inventory_analysis(
    period: str = THIS_MONTH, date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_INVENTORY)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    resolved = await _resolve_dates(session=session, tenant_id=tenant_id, period=period, date_from=date_from, date_to=date_to, compare_mode="NONE", compare_from=None, compare_to=None)
    data = await AnalysisService(session).get_inventory_analysis(tenant_id=tenant_id, date_from=resolved["date_from"], date_to=resolved["date_to"])
    return {"data": _jsonify(data), "meta": {**_meta(), "period": _jsonify({k: v for k, v in resolved.items()})}}
