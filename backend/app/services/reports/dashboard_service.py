"""Management Dashboard (PROMPT-027 §8/§9/§41).

Deliberately does NOT recompute anything — every KPI here calls the
SAME report-service method the corresponding detailed report itself
calls, with the SAME date range, so dashboard and detailed-report
figures are trivially reconciled by construction (§41's own "Dashboard
Sales This Month must equal Sales Report This Month" requirement) rather
than needing a separate, potentially-drifting reconciliation check.

**Inventory Value is explicitly NOT computed or shown (§8/§56 OD-002/
OD-003)** — no inventory valuation method (FIFO/weighted-average/
standard-cost) is approved anywhere in this codebase's baseline. Showing
a number here would silently invent a financial valuation policy, which
§8 explicitly forbids.

**GST figures always reflect the CURRENT calendar-month return period**,
not the dashboard's own selected date range — `gst_transaction.
return_period` (PROMPT-026) is monthly-only by design; there is no
sub-month or multi-month GST aggregation to align with an arbitrary
Today/This-Week/Custom-Range dashboard filter. This is a documented
simplification, not a bug (see PROMPT-027-NOTES.md).
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import CUSTOMER as PAYMENT_CUSTOMER
from app.models.payment import SUPPLIER as PAYMENT_SUPPLIER
from app.models.payment import POSTED as PAYMENT_POSTED
from app.models.payment import Payment
from app.models.tenant import Tenant
from app.services.gst.gstr_service import GstrService
from app.services.reports.inventory_report_service import LOW_STOCK, InventoryReportService
from app.services.reports.purchase_report_service import PurchaseReportService
from app.services.reports.receivables_payables_service import ReceivablesPayablesService
from app.services.reports.sales_report_service import SalesReportService

_ZERO = Decimal("0")

TODAY = "TODAY"
THIS_WEEK = "THIS_WEEK"
THIS_MONTH = "THIS_MONTH"
THIS_FY = "THIS_FY"
CUSTOM = "CUSTOM"

DASHBOARD_PERIODS = frozenset({TODAY, THIS_WEEK, THIS_MONTH, THIS_FY, CUSTOM})


def resolve_period(*, tenant: Tenant, period: str, custom_from: date | None, custom_to: date | None) -> tuple[date, date]:
    today = date.today()
    if period == TODAY:
        return today, today
    if period == THIS_WEEK:
        return today - timedelta(days=today.weekday()), today
    if period == THIS_MONTH:
        return today.replace(day=1), today
    if period == THIS_FY:
        start_month = tenant.financial_year_start_month
        fy_start_year = today.year if today.month >= start_month else today.year - 1
        return date(fy_start_year, start_month, 1), today
    # CUSTOM
    return custom_from or today, custom_to or today


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_dashboard(self, *, tenant: Tenant, date_from: date, date_to: date) -> dict:
        tenant_id = tenant.id
        sales_summary = await SalesReportService(self._session).get_sales_summary(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
        purchase_summary = await PurchaseReportService(self._session).get_purchase_summary(tenant_id=tenant_id, date_from=date_from, date_to=date_to)

        _, _, receivables_summary = await ReceivablesPayablesService(self._session).get_receivables(tenant_id=tenant_id, page=1, page_size=1, customer_id=None)
        _, _, payables_summary = await ReceivablesPayablesService(self._session).get_payables(tenant_id=tenant_id, page=1, page_size=1, supplier_id=None)

        _, low_stock_total = await InventoryReportService(self._session).get_current_stock(tenant_id=tenant_id, page=1, page_size=1, status_filter=LOW_STOCK, search=None)

        return_period = date.today().strftime("%Y-%m")
        gst_dashboard = await GstrService(self._session).dashboard(tenant_id=tenant_id, return_period=return_period)

        collections = await self._payment_total(tenant_id=tenant_id, party_type=PAYMENT_CUSTOMER, date_from=date_from, date_to=date_to)
        supplier_payments = await self._payment_total(tenant_id=tenant_id, party_type=PAYMENT_SUPPLIER, date_from=date_from, date_to=date_to)

        return {
            "period": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
            "sales": {"net_sales": sales_summary["net_sales"], "invoice_total": sales_summary["invoice_total"], "invoice_count": sales_summary["invoice_count"]},
            "purchase": {"net_purchase": purchase_summary["net_purchase"], "invoice_count": purchase_summary["invoice_count"]},
            "receivables": {"total_outstanding": receivables_summary["total_receivables"]},
            "payables": {"total_outstanding": payables_summary["total_payables"]},
            "inventory": {"low_stock_item_count": low_stock_total, "inventory_value": None},
            "gst": {
                "return_period": return_period, "output_gst": gst_dashboard["output_gst"], "input_gst": gst_dashboard["input_gst"],
                "net_gst_position": gst_dashboard["net_gst_position"],
            },
            "collections": {"customer_collections": collections, "supplier_payments": supplier_payments},
        }

    async def _payment_total(self, *, tenant_id: uuid.UUID, party_type: str, date_from: date, date_to: date) -> Decimal:
        result = await self._session.execute(
            select(func.coalesce(func.sum(Payment.amount), _ZERO)).where(
                Payment.tenant_id == tenant_id, Payment.party_type == party_type, Payment.status == PAYMENT_POSTED,
                Payment.payment_date >= date_from, Payment.payment_date <= date_to,
            )
        )
        return result.scalar_one()
