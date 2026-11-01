"""Analysis page aggregation layer (BI module, Phase 1).

A thin COMPOSITION layer only — every KPI/formula here is computed by
calling the existing, already-tested, already-documented report services
(`SalesReportService`/`PurchaseReportService`/`InventoryReportService`/
`ReceivablesPayablesService`) for the current period and (optionally) a
comparison period, then merging the two into `{current, previous, change,
change_percent}`. No Net Sales / Net Purchase / Outstanding formula is
reimplemented here — see those services' own module docstrings for the
authoritative formulas this module calls, unchanged.

The only genuinely NEW query logic in this file is:
1. Trend series (daily/weekly/monthly points) — the existing report
   services return period TOTALS, not a time series, so a trend chart
   needs its own `GROUP BY date_trunc(...)` query. These copy the exact
   same tenant/status/date-column filter conditions the corresponding
   report service already uses (POSTED invoices only, same date column).
2. Receivables aging bucketing for the Overview tab, using the exact same
   bucket boundaries as `dashboard_service.py`'s `_AGING_BUCKETS`
   (current/1-30/31-60/61-90/90+/no_due_date) — duplicated as a small,
   self-contained helper rather than reaching into `DashboardService`'s
   private method.

**Inventory Value, Gross Margin, and Stock Turnover are never computed
here** — no inventory valuation method or COGS source is approved
anywhere in this codebase (confirmed: `Product.cost_price` is the only
cost field, no COGS account type is ever posted to, `dashboard_service.
py` hardcodes `inventory_value: None`). Every such field returns
`{"value": None, "reason": "..."}` instead of a fabricated number.

**Product Category** does not exist on `Product` at all (confirmed:
`product.py`'s own docstring — "Deliberately has NO category/subcategory
... columns"), so no category-based breakdown is offered anywhere in
this module; flagged, not faked with a fake single "Uncategorized"
bucket.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.customer import Customer
from app.models.purchase_invoice import POSTED as PINV_POSTED
from app.models.purchase_invoice import PurchaseInvoice
from app.models.sales_invoice import POSTED as SINV_POSTED
from app.models.sales_invoice import SalesInvoice
from app.models.sales_invoice_line import SalesInvoiceLine
from app.models.user import User
from app.services.analysis.period_utils import safe_percent_change
from app.services.reports.inventory_report_service import InventoryReportService
from app.services.reports.purchase_report_service import PurchaseReportService
from app.services.reports.receivables_payables_service import ReceivablesPayablesService
from app.services.reports.sales_report_service import SalesReportService

_ZERO = Decimal("0")
_TOP_N = 10
_AGING_BUCKETS = ("current", "days_1_30", "days_31_60", "days_61_90", "days_90_plus", "no_due_date")
_UNAVAILABLE_INVENTORY_VALUE = {"value": None, "reason": "No inventory valuation method (FIFO/weighted-average/standard-cost) is approved for this codebase."}
_UNAVAILABLE_MARGIN = {"value": None, "reason": "No approved costing method exists to compute Cost of Goods Sold — purchase price is not substituted for it."}
_UNAVAILABLE_TURNOVER = {"value": None, "reason": "Stock turnover / days-of-inventory has no approved formula or data source in this codebase."}


def _trend_granularity(date_from: date, date_to: date) -> str:
    span_days = (date_to - date_from).days + 1
    if span_days <= 31:
        return "day"
    if span_days <= 120:
        return "week"
    return "month"


def _kpi(current: Decimal, previous: Decimal | None) -> dict:
    change = (current - previous) if previous is not None else None
    return {
        "current": current, "previous": previous, "change": change,
        "change_percent": safe_percent_change(current, previous),
    }


class AnalysisService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sales = SalesReportService(session)
        self._purchase = PurchaseReportService(session)
        self._inventory = InventoryReportService(session)
        self._receivables = ReceivablesPayablesService(session)

    # --- Shared helpers ---------------------------------------------------

    async def _sales_trend(self, *, tenant_id: uuid.UUID, date_from: date, date_to: date) -> list[dict]:
        granularity = _trend_granularity(date_from, date_to)
        bucket = func.date_trunc(granularity, SalesInvoice.invoice_date)
        rows = (
            await self._session.execute(
                select(bucket, func.coalesce(func.sum(SalesInvoice.taxable_total), _ZERO))
                .where(SalesInvoice.tenant_id == tenant_id, SalesInvoice.status == SINV_POSTED, SalesInvoice.invoice_date >= date_from, SalesInvoice.invoice_date <= date_to)
                .group_by(bucket).order_by(bucket)
            )
        ).all()
        return [{"date": bucket_date.date().isoformat(), "value": value} for bucket_date, value in rows]

    async def _purchase_trend(self, *, tenant_id: uuid.UUID, date_from: date, date_to: date) -> list[dict]:
        granularity = _trend_granularity(date_from, date_to)
        bucket = func.date_trunc(granularity, PurchaseInvoice.document_date)
        rows = (
            await self._session.execute(
                select(bucket, func.coalesce(func.sum(PurchaseInvoice.taxable_total), _ZERO))
                .where(PurchaseInvoice.tenant_id == tenant_id, PurchaseInvoice.status == PINV_POSTED, PurchaseInvoice.document_date >= date_from, PurchaseInvoice.document_date <= date_to)
                .group_by(bucket).order_by(bucket)
            )
        ).all()
        return [{"date": bucket_date.date().isoformat(), "value": value} for bucket_date, value in rows]

    async def _quantity_sold(self, *, tenant_id: uuid.UUID, date_from: date, date_to: date) -> Decimal:
        result = await self._session.execute(
            select(func.coalesce(func.sum(SalesInvoiceLine.quantity), _ZERO))
            .select_from(SalesInvoiceLine).join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
            .where(SalesInvoiceLine.tenant_id == tenant_id, SalesInvoice.status == SINV_POSTED, SalesInvoice.invoice_date >= date_from, SalesInvoice.invoice_date <= date_to)
        )
        return result.scalar_one()

    async def _receivables_aging(self, *, tenant_id: uuid.UUID) -> dict:
        # Same bucket thresholds as dashboard_service.py's _AGING_BUCKETS —
        # duplicated intentionally (self-contained aggregation layer, no
        # cross-service private-method reach-in).
        rows = (
            await self._session.execute(
                select(SalesInvoice.invoice_date, Customer.payment_terms_days, (SalesInvoice.grand_total - SalesInvoice.paid_amount))
                .join(Customer, Customer.id == SalesInvoice.customer_id)
                .where(SalesInvoice.tenant_id == tenant_id, SalesInvoice.status == SINV_POSTED, SalesInvoice.payment_status != "PAID")
            )
        ).all()
        today = date.today()
        aging = {b: _ZERO for b in _AGING_BUCKETS}
        for invoice_date, terms_days, outstanding in rows:
            if not terms_days:
                aging["no_due_date"] += outstanding
                continue
            days_past_due = (today - (invoice_date + timedelta(days=terms_days))).days
            if days_past_due <= 0:
                aging["current"] += outstanding
            elif days_past_due <= 30:
                aging["days_1_30"] += outstanding
            elif days_past_due <= 60:
                aging["days_31_60"] += outstanding
            elif days_past_due <= 90:
                aging["days_61_90"] += outstanding
            else:
                aging["days_90_plus"] += outstanding
        return aging

    # --- Overview -----------------------------------------------------------

    async def get_overview(self, *, tenant_id: uuid.UUID, date_from: date, date_to: date, compare_from: date | None, compare_to: date | None) -> dict:
        sales_now = await self._sales.get_sales_summary(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
        purchase_now = await self._purchase.get_purchase_summary(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
        sales_prev = purchase_prev = None
        if compare_from and compare_to:
            sales_prev = await self._sales.get_sales_summary(tenant_id=tenant_id, date_from=compare_from, date_to=compare_to)
            purchase_prev = await self._purchase.get_purchase_summary(tenant_id=tenant_id, date_from=compare_from, date_to=compare_to)

        avg_invoice_now = (sales_now["invoice_total"] / sales_now["invoice_count"]) if sales_now["invoice_count"] else _ZERO
        avg_invoice_prev = None
        if sales_prev is not None:
            avg_invoice_prev = (sales_prev["invoice_total"] / sales_prev["invoice_count"]) if sales_prev["invoice_count"] else _ZERO

        _, _, receivables_summary = await self._receivables.get_receivables(tenant_id=tenant_id, page=1, page_size=1, customer_id=None)
        _, _, payables_summary = await self._receivables.get_payables(tenant_id=tenant_id, page=1, page_size=1, supplier_id=None)

        top_products, _ = await self._sales.get_product_wise_sales(tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=1, page_size=5)
        top_customers, _ = await self._sales.get_customer_wise_sales(tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=1, page_size=5)
        aging = await self._receivables_aging(tenant_id=tenant_id)

        return {
            "kpis": {
                "net_sales": _kpi(sales_now["net_sales"], sales_prev["net_sales"] if sales_prev else None),
                "purchase_value": _kpi(purchase_now["net_purchase"], purchase_prev["net_purchase"] if purchase_prev else None),
                "gross_profit": _UNAVAILABLE_MARGIN,
                "average_invoice_value": _kpi(avg_invoice_now, avg_invoice_prev),
                "customer_outstanding": {"current": receivables_summary["total_receivables"], "previous": None, "change": None, "change_percent": None},
                "supplier_payables": {"current": payables_summary["total_payables"], "previous": None, "change": None, "change_percent": None},
                "inventory_value": _UNAVAILABLE_INVENTORY_VALUE,
            },
            "sales_trend": await self._sales_trend(tenant_id=tenant_id, date_from=date_from, date_to=date_to),
            "purchase_trend": await self._purchase_trend(tenant_id=tenant_id, date_from=date_from, date_to=date_to),
            "top_products": top_products,
            "top_customers": top_customers,
            "receivables_aging": aging,
        }

    # --- Sales ---------------------------------------------------------------

    async def get_sales_analysis(self, *, tenant_id: uuid.UUID, date_from: date, date_to: date, compare_from: date | None, compare_to: date | None) -> dict:
        now = await self._sales.get_sales_summary(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
        qty_now = await self._quantity_sold(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
        prev = qty_prev = None
        if compare_from and compare_to:
            prev = await self._sales.get_sales_summary(tenant_id=tenant_id, date_from=compare_from, date_to=compare_to)
            qty_prev = await self._quantity_sold(tenant_id=tenant_id, date_from=compare_from, date_to=compare_to)

        avg_now = (now["invoice_total"] / now["invoice_count"]) if now["invoice_count"] else _ZERO
        avg_prev = None
        if prev is not None:
            avg_prev = (prev["invoice_total"] / prev["invoice_count"]) if prev["invoice_count"] else _ZERO

        products, _ = await self._sales.get_product_wise_sales(tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=1, page_size=_TOP_N)
        customers, _ = await self._sales.get_customer_wise_sales(tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=1, page_size=_TOP_N)

        total_net_sales = now["net_sales"] or _ZERO
        table_rows = []
        for row in products:
            contribution = (row["net_sales"] / total_net_sales * Decimal("100")) if total_net_sales else None
            table_rows.append({**row, "contribution_percent": contribution})

        return {
            "kpis": {
                "gross_sales": _kpi(now["gross_sales"], prev["gross_sales"] if prev else None),
                "discounts": _kpi(now["discount"], prev["discount"] if prev else None),
                "sales_returns": _kpi(now["sales_returns_total"], prev["sales_returns_total"] if prev else None),
                "net_sales": _kpi(now["net_sales"], prev["net_sales"] if prev else None),
                "invoice_count": _kpi(Decimal(now["invoice_count"]), Decimal(prev["invoice_count"]) if prev else None),
                "average_invoice_value": _kpi(avg_now, avg_prev),
                "quantity_sold": _kpi(qty_now, qty_prev),
            },
            "sales_trend": await self._sales_trend(tenant_id=tenant_id, date_from=date_from, date_to=date_to),
            "top_products": products[:10],
            "top_customers": customers[:10],
            "table": table_rows,
        }

    # --- Products --------------------------------------------------------------

    async def get_product_analysis(self, *, tenant_id: uuid.UUID, date_from: date, date_to: date, compare_from: date | None, compare_to: date | None) -> dict:
        products, total = await self._sales.get_product_wise_sales(tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=1, page_size=500)
        prev_by_id: dict[str, dict] = {}
        if compare_from and compare_to:
            prev_products, _ = await self._sales.get_product_wise_sales(tenant_id=tenant_id, date_from=compare_from, date_to=compare_to, page=1, page_size=500)
            prev_by_id = {p["product_id"]: p for p in prev_products}

        stock_rows, _ = await self._inventory.get_current_stock(tenant_id=tenant_id, page=1, page_size=1000, status_filter=None, search=None)
        stock_by_id = {s["product_id"]: s for s in stock_rows}

        table = []
        for row in sorted(products, key=lambda r: r["net_sales"], reverse=True):
            prev_row = prev_by_id.get(row["product_id"])
            stock = stock_by_id.get(row["product_id"])
            table.append({
                **row,
                "previous_net_sales": prev_row["net_sales"] if prev_row else None,
                "change_percent": safe_percent_change(row["net_sales"], prev_row["net_sales"] if prev_row else None),
                "current_stock": stock["current_quantity"] if stock else None,
                "stock_status": stock["stock_status"] if stock else None,
                "gross_margin": _UNAVAILABLE_MARGIN,
            })

        return {
            "top_10": table[:10],
            "bottom_10": list(reversed(table[-10:])) if len(table) > 10 else [],
            "table": table,
            "total_products_with_sales": total,
            "sales_trend": await self._sales_trend(tenant_id=tenant_id, date_from=date_from, date_to=date_to),
        }

    # --- Customers --------------------------------------------------------------

    async def get_customer_analysis(self, *, tenant_id: uuid.UUID, date_from: date, date_to: date, compare_from: date | None, compare_to: date | None) -> dict:
        customers, total = await self._sales.get_customer_wise_sales(tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=1, page_size=500)
        prev_by_id: dict[str, dict] = {}
        if compare_from and compare_to:
            prev_customers, _ = await self._sales.get_customer_wise_sales(tenant_id=tenant_id, date_from=compare_from, date_to=compare_to, page=1, page_size=500)
            prev_by_id = {c["customer_id"]: c for c in prev_customers}

        aging = await self._receivables_aging(tenant_id=tenant_id)
        overdue_by_customer = await self._overdue_by_customer(tenant_id=tenant_id)

        table = []
        for row in sorted(customers, key=lambda r: r["net_sales"], reverse=True):
            prev_row = prev_by_id.get(row["customer_id"])
            avg_invoice = (row["taxable_sales"] / row["invoice_count"]) if row["invoice_count"] else _ZERO
            table.append({
                **row, "average_invoice_value": avg_invoice,
                "overdue_amount": overdue_by_customer.get(row["customer_id"], _ZERO),
                "previous_net_sales": prev_row["net_sales"] if prev_row else None,
                "change_percent": safe_percent_change(row["net_sales"], prev_row["net_sales"] if prev_row else None),
            })

        active_customers = len(customers)
        total_net_sales = sum((c["net_sales"] for c in customers), _ZERO)
        avg_sales_per_customer = (total_net_sales / active_customers) if active_customers else _ZERO

        return {
            "kpis": {
                "sales_to_customers": {"current": total_net_sales, "previous": None, "change": None, "change_percent": None},
                "active_customers": active_customers,
                "average_sales_per_customer": avg_sales_per_customer,
            },
            "top_customers": table[:10],
            "receivables_aging": aging,
            "table": table,
            "total_customers_with_sales": total,
        }

    async def _overdue_by_customer(self, *, tenant_id: uuid.UUID) -> dict[str, Decimal]:
        rows = (
            await self._session.execute(
                select(SalesInvoice.customer_id, SalesInvoice.invoice_date, Customer.payment_terms_days, (SalesInvoice.grand_total - SalesInvoice.paid_amount))
                .join(Customer, Customer.id == SalesInvoice.customer_id)
                .where(SalesInvoice.tenant_id == tenant_id, SalesInvoice.status == SINV_POSTED, SalesInvoice.payment_status != "PAID")
            )
        ).all()
        today = date.today()
        overdue: dict[str, Decimal] = {}
        for customer_id, invoice_date, terms_days, outstanding in rows:
            if terms_days and (today - (invoice_date + timedelta(days=terms_days))).days > 0:
                key = str(customer_id)
                overdue[key] = overdue.get(key, _ZERO) + outstanding
        return overdue

    # --- Purchases --------------------------------------------------------------

    async def get_purchase_analysis(self, *, tenant_id: uuid.UUID, date_from: date, date_to: date, compare_from: date | None, compare_to: date | None) -> dict:
        now = await self._purchase.get_purchase_summary(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
        prev = None
        if compare_from and compare_to:
            prev = await self._purchase.get_purchase_summary(tenant_id=tenant_id, date_from=compare_from, date_to=compare_to)

        suppliers, _ = await self._purchase.get_supplier_wise_purchase(tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=1, page_size=_TOP_N)
        products, _ = await self._purchase.get_product_wise_purchase(tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=1, page_size=_TOP_N)

        return {
            "kpis": {
                "gross_purchase": _kpi(now["gross_purchase"], prev["gross_purchase"] if prev else None),
                "purchase_returns": _kpi(now["purchase_returns"], prev["purchase_returns"] if prev else None),
                "net_purchase": _kpi(now["net_purchase"], prev["net_purchase"] if prev else None),
                "invoice_count": _kpi(Decimal(now["invoice_count"]), Decimal(prev["invoice_count"]) if prev else None),
            },
            "purchase_trend": await self._purchase_trend(tenant_id=tenant_id, date_from=date_from, date_to=date_to),
            "top_suppliers": suppliers,
            "top_products": products,
        }

    # --- Sales by User (staff performance — how many sales each user has
    # made) ------------------------------------------------------------------
    # `restrict_to_user_id` is set by the router whenever the caller's role
    # is SALESPERSON (per the user's own explicit decision: Owner/Manager
    # see every staff member, Salesperson sees only their own row) — a
    # server-side filter, never a frontend-only hide, consistent with this
    # codebase's "backend authorization is always authoritative" rule.

    async def get_sales_by_user(
        self, *, tenant_id: uuid.UUID, date_from: date, date_to: date, restrict_to_user_id: uuid.UUID | None,
    ) -> list[dict]:
        creator = aliased(User)
        conditions = [
            SalesInvoice.tenant_id == tenant_id, SalesInvoice.status == SINV_POSTED,
            SalesInvoice.invoice_date >= date_from, SalesInvoice.invoice_date <= date_to,
        ]
        if restrict_to_user_id is not None:
            conditions.append(SalesInvoice.created_by == restrict_to_user_id)

        rows = (
            await self._session.execute(
                select(creator.id, creator.name, func.count(SalesInvoice.id), func.coalesce(func.sum(SalesInvoice.grand_total), _ZERO))
                .select_from(SalesInvoice)
                .outerjoin(creator, creator.id == SalesInvoice.created_by)
                .where(*conditions)
                .group_by(creator.id, creator.name)
                .order_by(func.coalesce(func.sum(SalesInvoice.grand_total), _ZERO).desc())
            )
        ).all()
        return [
            {"user_id": str(user_id) if user_id else None, "user_name": user_name or "Unknown", "invoice_count": count, "total_amount": total}
            for user_id, user_name, count, total in rows
        ]

    # --- Inventory --------------------------------------------------------------

    async def get_inventory_analysis(self, *, tenant_id: uuid.UUID, date_from: date, date_to: date) -> dict:
        stock_rows, total_products = await self._inventory.get_current_stock(tenant_id=tenant_id, page=1, page_size=1000, status_filter=None, search=None)
        low_stock = sum(1 for s in stock_rows if s["stock_status"] == "LOW_STOCK")
        out_of_stock = sum(1 for s in stock_rows if s["stock_status"] == "OUT_OF_STOCK")

        sold, _ = await self._sales.get_product_wise_sales(tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=1, page_size=1000)
        sold_by_id = {s["product_id"]: s["quantity_sold"] for s in sold}

        movement_rows = []
        for s in stock_rows:
            movement_rows.append({
                **s, "quantity_sold_in_period": sold_by_id.get(s["product_id"], _ZERO),
            })

        fast_moving = sorted((m for m in movement_rows if m["quantity_sold_in_period"] > 0), key=lambda m: m["quantity_sold_in_period"], reverse=True)[:10]
        slow_moving = sorted(
            (m for m in movement_rows if m["current_quantity"] > 0),
            key=lambda m: (m["quantity_sold_in_period"], -m["current_quantity"]),
        )[:10]

        return {
            "kpis": {
                "total_stock_quantity": sum((s["current_quantity"] for s in stock_rows), _ZERO),
                "low_stock_items": low_stock,
                "out_of_stock_items": out_of_stock,
                "inventory_value": _UNAVAILABLE_INVENTORY_VALUE,
                "stock_turnover": _UNAVAILABLE_TURNOVER,
            },
            "fast_moving": fast_moving,
            "slow_moving": slow_moving,
            "table": movement_rows,
            "total_products": total_products,
        }
