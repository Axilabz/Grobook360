"""Reports, Dashboards & Financial Statements endpoints (PROMPT-027 §48).

Every endpoint here is READ-ONLY and aggregates over already-posted,
already-authoritative data (§2's own mandatory principle) — no report
endpoint writes to any business/accounting/GST table. `tenant_id` always
comes from the authenticated session context, never from a client-
supplied parameter (§53).
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
from app.core.permissions import (
    REPORTS_VIEW_BALANCE_SHEET,
    REPORTS_VIEW_DASHBOARD,
    REPORTS_VIEW_GENERAL_LEDGER,
    REPORTS_VIEW_GST,
    REPORTS_VIEW_INVENTORY,
    REPORTS_VIEW_PAYABLES,
    REPORTS_VIEW_PAYMENTS,
    REPORTS_VIEW_PROFIT_LOSS,
    REPORTS_VIEW_PURCHASE,
    REPORTS_VIEW_RECEIVABLES,
    REPORTS_VIEW_SALES,
    REPORTS_VIEW_TRIAL_BALANCE,
)
from app.db.session import get_db_session
from app.models.tenant import Tenant
from app.schemas.envelopes import Pagination
from app.services.gst.gstr_service import GstrService
from app.services.reports.accounting_report_service import AccountingReportService
from app.services.reports.dashboard_service import CUSTOM, DASHBOARD_PERIODS, THIS_MONTH, DashboardService, resolve_period
from app.services.reports.inventory_report_service import InventoryReportService
from app.services.reports.payment_report_service import PaymentReportService
from app.services.reports.purchase_report_service import PurchaseReportService
from app.services.reports.receivables_payables_service import ReceivablesPayablesService
from app.services.reports.sales_report_service import SalesReportService

router = APIRouter(prefix="/reports", tags=["reports"])


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


def _pagination(page: int, page_size: int, total_items: int) -> dict:
    total_pages = (total_items + page_size - 1) // page_size if total_items else 0
    return Pagination(page=page, page_size=page_size, total_items=total_items, total_pages=total_pages).model_dump()


def _clean_page(page: int, page_size: int) -> tuple[int, int]:
    return max(page, 1), min(max(page_size, 1), 200)


def _validate_range(date_from: date | None, date_to: date | None) -> None:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValidationAppError("date_from must not be after date_to.", code=REPORT_INVALID_DATE_RANGE)


async def _get_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    return result.scalar_one()


# --- Dashboard (§8/§9) ----------------------------------------------------


@router.get("/dashboard")
async def get_dashboard(
    period: str = THIS_MONTH, date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_DASHBOARD)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    if period not in DASHBOARD_PERIODS:
        raise ValidationAppError(f"Unknown dashboard period '{period}'.", code=REPORT_INVALID_DATE_RANGE)
    if period == CUSTOM:
        _validate_range(date_from, date_to)
    tenant = await _get_tenant(session, tenant_id)
    resolved_from, resolved_to = resolve_period(tenant=tenant, period=period, custom_from=date_from, custom_to=date_to)
    data = await DashboardService(session).get_dashboard(tenant=tenant, date_from=resolved_from, date_to=resolved_to)
    return {"data": _jsonify(data), "meta": _meta()}


@router.get("/dashboard/alerts")
async def get_dashboard_alerts(
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_DASHBOARD)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    data = await DashboardService(session).get_alerts(tenant_id=tenant_id)
    return {"data": _jsonify(data), "meta": _meta()}


@router.get("/dashboard/recent-transactions")
async def get_dashboard_recent_transactions(
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_DASHBOARD)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    data = await DashboardService(session).get_recent_transactions(tenant_id=tenant_id)
    return {"data": _jsonify(data), "meta": _meta()}


# --- Sales reports (§10-§15) -----------------------------------------------


@router.get("/sales/summary")
async def sales_summary(
    date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_SALES)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    data = await SalesReportService(session).get_sales_summary(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
    return {"data": _jsonify(data), "meta": _meta()}


@router.get("/sales/invoices")
async def sales_invoice_register(
    page: int = 1, page_size: int = 25, date_from: date | None = None, date_to: date | None = None,
    customer_id: uuid.UUID | None = None, payment_status: str | None = None, amount_min: Decimal | None = None, amount_max: Decimal | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_SALES)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    page, page_size = _clean_page(page, page_size)
    rows, total_items = await SalesReportService(session).list_sales_invoices(
        tenant_id=tenant_id, page=page, page_size=page_size, date_from=date_from, date_to=date_to,
        customer_id=customer_id, payment_status=payment_status, amount_min=amount_min, amount_max=amount_max,
    )
    items = [
        {
            "invoice_id": str(inv.id), "invoice_number": inv.invoice_number, "invoice_date": inv.invoice_date.isoformat(), "customer_name": name,
            "gstin": inv.customer_gstin, "taxable_value": inv.taxable_total, "cgst": inv.cgst_total, "sgst": inv.sgst_total, "igst": inv.igst_total,
            "total_gst": inv.tax_total, "invoice_total": inv.grand_total, "payment_status": inv.payment_status,
            "einvoice_status": inv.einvoice_status, "created_by": str(inv.created_by) if inv.created_by else None,
        }
        for inv, name in rows
    ]
    return {"data": _jsonify(items), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


@router.get("/sales/customers")
async def sales_customer_wise(
    page: int = 1, page_size: int = 25, date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_SALES)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    page, page_size = _clean_page(page, page_size)
    items, total_items = await SalesReportService(session).get_customer_wise_sales(tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=page, page_size=page_size)
    return {"data": _jsonify(items), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


@router.get("/sales/products")
async def sales_product_wise(
    page: int = 1, page_size: int = 25, date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_SALES)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    page, page_size = _clean_page(page, page_size)
    items, total_items = await SalesReportService(session).get_product_wise_sales(tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=page, page_size=page_size)
    return {"data": _jsonify(items), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


@router.get("/sales/returns")
async def sales_return_report(
    page: int = 1, page_size: int = 25, date_from: date | None = None, date_to: date | None = None, customer_id: uuid.UUID | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_SALES)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    page, page_size = _clean_page(page, page_size)
    rows, total_items = await SalesReportService(session).list_sales_returns(tenant_id=tenant_id, page=page, page_size=page_size, date_from=date_from, date_to=date_to, customer_id=customer_id)
    items = [
        {
            "return_id": str(ret.id), "return_number": ret.return_number, "return_date": ret.return_date.isoformat(), "customer_name": name,
            "source_invoice_number": invoice_number, "taxable_value": ret.taxable_total, "total_gst": ret.tax_total,
            "total_return_value": ret.grand_total, "reason": ret.return_reason, "status": ret.status,
        }
        for ret, name, invoice_number in rows
    ]
    return {"data": _jsonify(items), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


# --- Purchase reports (§16-§21) --------------------------------------------


@router.get("/purchase/summary")
async def purchase_summary(
    date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_PURCHASE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    data = await PurchaseReportService(session).get_purchase_summary(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
    return {"data": _jsonify(data), "meta": _meta()}


@router.get("/purchase/invoices")
async def purchase_invoice_register(
    page: int = 1, page_size: int = 25, date_from: date | None = None, date_to: date | None = None,
    supplier_id: uuid.UUID | None = None, payment_status: str | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_PURCHASE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    page, page_size = _clean_page(page, page_size)
    rows, total_items = await PurchaseReportService(session).list_purchase_invoices(
        tenant_id=tenant_id, page=page, page_size=page_size, date_from=date_from, date_to=date_to, supplier_id=supplier_id, payment_status=payment_status,
    )
    items = [
        {
            "invoice_id": str(inv.id), "purchase_invoice_number": inv.purchase_invoice_number, "supplier_invoice_number": inv.supplier_invoice_number,
            "invoice_date": inv.document_date.isoformat(), "supplier_name": name, "gstin": inv.supplier_gstin, "taxable_value": inv.taxable_total,
            "cgst": inv.cgst_total, "sgst": inv.sgst_total, "igst": inv.igst_total, "total_gst": inv.cgst_total + inv.sgst_total + inv.igst_total,
            "invoice_total": inv.grand_total, "payment_status": inv.payment_status, "status": inv.status,
            "created_by": str(inv.created_by) if inv.created_by else None,
        }
        for inv, name in rows
    ]
    return {"data": _jsonify(items), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


@router.get("/purchase/suppliers")
async def purchase_supplier_wise(
    page: int = 1, page_size: int = 25, date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_PURCHASE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    page, page_size = _clean_page(page, page_size)
    items, total_items = await PurchaseReportService(session).get_supplier_wise_purchase(tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=page, page_size=page_size)
    return {"data": _jsonify(items), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


@router.get("/purchase/products")
async def purchase_product_wise(
    page: int = 1, page_size: int = 25, date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_PURCHASE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    page, page_size = _clean_page(page, page_size)
    items, total_items = await PurchaseReportService(session).get_product_wise_purchase(tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=page, page_size=page_size)
    return {"data": _jsonify(items), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


@router.get("/purchase/returns")
async def purchase_return_report(
    page: int = 1, page_size: int = 25, date_from: date | None = None, date_to: date | None = None, supplier_id: uuid.UUID | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_PURCHASE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    page, page_size = _clean_page(page, page_size)
    rows, total_items = await PurchaseReportService(session).list_purchase_returns(tenant_id=tenant_id, page=page, page_size=page_size, date_from=date_from, date_to=date_to, supplier_id=supplier_id)
    items = [
        {
            "return_id": str(ret.id), "return_number": ret.purchase_return_number, "return_date": ret.document_date.isoformat(), "supplier_name": name,
            "source_purchase_invoice_number": invoice_number, "taxable_value": ret.taxable_total, "total_gst": ret.tax_total,
            "total_return_value": ret.grand_total, "reason": ret.return_reason, "status": ret.status,
        }
        for ret, name, invoice_number in rows
    ]
    return {"data": _jsonify(items), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


# --- Inventory reports (§22-§25) --------------------------------------------


@router.get("/inventory/current-stock")
async def current_stock(
    page: int = 1, page_size: int = 25, status: str | None = None, search: str | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_INVENTORY)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page, page_size = _clean_page(page, page_size)
    items, total_items = await InventoryReportService(session).get_current_stock(tenant_id=tenant_id, page=page, page_size=page_size, status_filter=status, search=search)
    return {"data": _jsonify(items), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


@router.get("/inventory/movements")
async def stock_movements(
    page: int = 1, page_size: int = 25, date_from: date | None = None, date_to: date | None = None,
    product_id: uuid.UUID | None = None, movement_type: str | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_INVENTORY)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    page, page_size = _clean_page(page, page_size)
    items, total_items = await InventoryReportService(session).list_stock_movements(
        tenant_id=tenant_id, page=page, page_size=page_size, date_from=date_from, date_to=date_to, product_id=product_id, movement_type=movement_type,
    )
    return {"data": _jsonify(items), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


@router.get("/inventory/history")
async def product_stock_history(
    product_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_INVENTORY)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    opening_balance, history = await InventoryReportService(session).get_product_stock_history(tenant_id=tenant_id, product_id=product_id, date_from=date_from, date_to=date_to)
    return {"data": _jsonify({"opening_balance": opening_balance, "movements": history}), "meta": _meta()}


# --- Receivables / Payables (§26-§29) ---------------------------------------


@router.get("/receivables")
async def receivables(
    page: int = 1, page_size: int = 25, customer_id: uuid.UUID | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_RECEIVABLES)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page, page_size = _clean_page(page, page_size)
    items, total_items, summary = await ReceivablesPayablesService(session).get_receivables(tenant_id=tenant_id, page=page, page_size=page_size, customer_id=customer_id)
    return {"data": _jsonify(items), "summary": _jsonify(summary), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


@router.get("/payables")
async def payables(
    page: int = 1, page_size: int = 25, supplier_id: uuid.UUID | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_PAYABLES)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page, page_size = _clean_page(page, page_size)
    items, total_items, summary = await ReceivablesPayablesService(session).get_payables(tenant_id=tenant_id, page=page, page_size=page_size, supplier_id=supplier_id)
    return {"data": _jsonify(items), "summary": _jsonify(summary), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


# --- Payments (§30-§32) ------------------------------------------------------


@router.get("/payments")
async def payments(
    page: int = 1, page_size: int = 25, date_from: date | None = None, date_to: date | None = None,
    party_type: str | None = None, payment_method: str | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_PAYMENTS)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    page, page_size = _clean_page(page, page_size)
    items, total_items = await PaymentReportService(session).list_payments(
        tenant_id=tenant_id, page=page, page_size=page_size, date_from=date_from, date_to=date_to, party_type=party_type, payment_method=payment_method,
    )
    return {"data": _jsonify(items), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


@router.get("/payments/method-summary")
async def payment_method_summary(
    date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_PAYMENTS)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    items = await PaymentReportService(session).get_payment_method_summary(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
    return {"data": _jsonify(items), "meta": _meta()}


@router.get("/payments/cheques")
async def cheque_report(
    page: int = 1, page_size: int = 25, cheque_status: str | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_PAYMENTS)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page, page_size = _clean_page(page, page_size)
    items, total_items = await PaymentReportService(session).list_cheques(tenant_id=tenant_id, page=page, page_size=page_size, cheque_status=cheque_status)
    return {"data": _jsonify(items), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


# --- Accounting (§33-§38) -----------------------------------------------------


@router.get("/accounting/general-ledger")
async def general_ledger(
    account_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_GENERAL_LEDGER)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    account, opening_balance, entries = await AccountingReportService(session).get_general_ledger(tenant_id=tenant_id, account_id=account_id, date_from=date_from, date_to=date_to)
    data = {
        "account_id": str(account.id), "account_code": account.code, "account_name": account.name, "account_type": account.account_type,
        "opening_balance": opening_balance, "closing_balance": entries[-1].running_balance if entries else opening_balance,
        "entries": [
            {
                "date": e.journal_date.isoformat(), "journal_number": e.journal_number, "source_type": e.source_type, "source_id": e.source_id,
                "source_number": e.source_number, "description": e.description, "debit": e.debit, "credit": e.credit, "running_balance": e.running_balance,
            }
            for e in entries
        ],
    }
    return {"data": _jsonify(data), "meta": _meta()}


@router.get("/accounting/trial-balance")
async def trial_balance(
    date_to: date | None = None, context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_TRIAL_BALANCE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    balances, total_debit, total_credit, is_balanced = await AccountingReportService(session).get_trial_balance(tenant_id=tenant_id, date_to=date_to)
    data = {
        "as_of_date": (date_to or date.today()).isoformat(), "is_balanced": is_balanced,
        "total_debit": total_debit, "total_credit": total_credit,
        "accounts": [
            {
                "account_id": b.account_id, "account_code": b.account_code, "account_name": b.account_name, "account_type": b.account_type,
                "debit": b.debit_total, "credit": b.credit_total,
            }
            for b in balances
        ],
    }
    return {"data": _jsonify(data), "meta": _meta()}


@router.get("/accounting/profit-loss")
async def profit_and_loss(
    date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_PROFIT_LOSS)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_range(date_from, date_to)
    result = await AccountingReportService(session).get_profit_and_loss(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
    data = {
        "period": {"date_from": date_from.isoformat() if date_from else None, "date_to": (date_to or date.today()).isoformat()},
        "revenue_accounts": [_balance_dict(b) for b in result["revenue_accounts"]], "total_revenue": result["total_revenue"],
        "cogs_accounts": [_balance_dict(b) for b in result["cogs_accounts"]], "total_cogs": result["total_cogs"], "gross_profit": result["gross_profit"],
        "expense_accounts": [_balance_dict(b) for b in result["expense_accounts"]], "total_expenses": result["total_expenses"], "net_profit": result["net_profit"],
    }
    return {"data": _jsonify(data), "meta": _meta()}


@router.get("/accounting/balance-sheet")
async def balance_sheet(
    as_of_date: date | None = None, context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_BALANCE_SHEET)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    result = await AccountingReportService(session).get_balance_sheet(tenant_id=tenant_id, as_of_date=as_of_date)
    data = {
        "as_of_date": (as_of_date or date.today()).isoformat(),
        "asset_accounts": [_balance_dict(b) for b in result["asset_accounts"]], "total_assets": result["total_assets"],
        "liability_accounts": [_balance_dict(b) for b in result["liability_accounts"]], "total_liabilities": result["total_liabilities"],
        "equity_accounts": [_balance_dict(b) for b in result["equity_accounts"]], "total_equity_posted": result["total_equity_posted"],
        "current_period_earnings": result["current_period_earnings"], "total_equity": result["total_equity"],
        "is_balanced": result["is_balanced"], "difference": result["difference"],
    }
    return {"data": _jsonify(data), "meta": _meta()}


def _balance_dict(b) -> dict:
    return {"account_id": b.account_id, "account_code": b.account_code, "account_name": b.account_name, "net_balance": b.net_debit_normal}


# --- GST reporting views (§39/§40) — thin delegation to the GST module ------


@router.get("/gst/summary")
async def gst_summary(
    return_period: str, context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_GST)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    data = await GstrService(session).dashboard(tenant_id=tenant_id, return_period=return_period)
    return {"data": _jsonify(data), "meta": _meta()}


@router.get("/gst/transactions")
async def gst_transactions(
    return_period: str | None = None, page: int = 1, page_size: int = 25,
    context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_GST)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page, page_size = _clean_page(page, page_size)
    transactions, total_items = await GstrService(session).list_transactions(
        tenant_id=tenant_id, page=page, page_size=page_size, return_period=return_period, source_type=None, classification=None, party_gstin=None, direction=None,
    )
    items = [
        {
            "id": str(t.id), "source_type": t.source_type, "source_number": t.source_number, "document_date": t.document_date.isoformat(),
            "classification": t.classification, "party_name": t.party_name, "taxable_value": t.taxable_value, "total_gst": t.total_gst,
        }
        for t in transactions
    ]
    return {"data": _jsonify(items), "pagination": _pagination(page, page_size, total_items), "meta": _meta()}


@router.get("/gst/hsn-summary")
async def gst_hsn_summary(
    return_period: str, context: AuthenticatedContext = Depends(require_permission(REPORTS_VIEW_GST)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    dataset = await GstrService(session).gstr1_dataset(tenant_id=tenant_id, return_period=return_period)
    return {"data": _jsonify(dataset["hsn_summary"]), "meta": _meta()}
