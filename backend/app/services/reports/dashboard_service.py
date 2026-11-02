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

import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.delivery_challan import DRAFT as DC_DRAFT
from app.models.delivery_challan import DeliveryChallan
from app.models.payment import BOUNCED as CHEQUE_BOUNCED
from app.models.payment import CHEQUE as PAYMENT_METHOD_CHEQUE
from app.models.payment import CUSTOMER as PAYMENT_CUSTOMER
from app.models.payment import PENDING as CHEQUE_PENDING
from app.models.payment import SUPPLIER as PAYMENT_SUPPLIER
from app.models.payment import POSTED as PAYMENT_POSTED
from app.models.payment import Payment
from app.models.purchase_invoice import POSTED as PINV_POSTED
from app.models.purchase_invoice import PurchaseInvoice
from app.models.sales_invoice import POSTED as SINV_POSTED
from app.models.sales_invoice import SalesInvoice
from app.models.sales_order import CONFIRMED as SO_CONFIRMED
from app.models.sales_order import PARTIALLY_FULFILLED as SO_PARTIALLY_FULFILLED
from app.models.sales_order import SalesOrder
from app.models.supplier import Supplier
from app.models.customer import Customer
from app.models.tenant import Tenant
from app.services.gst.gstr_service import GstrService
from app.services.reports.parallel import run_lanes
from app.services.reports.inventory_report_service import LOW_STOCK, OUT_OF_STOCK, InventoryReportService
from app.services.reports.purchase_report_service import PurchaseReportService
from app.services.reports.receivables_payables_service import ReceivablesPayablesService
from app.services.reports.sales_report_service import SalesReportService

_ZERO = Decimal("0")
_DASHBOARD_CACHE: dict[tuple, tuple[float, dict]] = {}
_RECENT_TRANSACTIONS_LIMIT = 8
_TOP_N = 5

# Aging bucket boundaries in days-past-due. An invoice with no derivable
# due_date (no `customer.payment_terms_days` set — see receivables_
# payables_service.py's own module docstring) is reported under its own
# "no_due_date" bucket rather than silently defaulted into "Current" or
# dropped — OD-007/OD-008/OD-009 (PROMPT-027) stay open on a real overdue
# policy; this is a transparent best-effort using the one due_date signal
# that already exists in this codebase.
_AGING_BUCKETS = ("current", "days_1_30", "days_31_60", "days_61_90", "days_90_plus", "no_due_date")

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
        # Short per-tenant cache (off by default): the dashboard is ~30 aggregate
        # queries; figures may lag real writes by at most the TTL.
        ttl = get_settings().report_cache_ttl_seconds
        key = (tenant.id, date_from, date_to)
        if ttl > 0:
            hit = _DASHBOARD_CACHE.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
        data = await self._compute_dashboard(tenant=tenant, date_from=date_from, date_to=date_to)
        if ttl > 0:
            if len(_DASHBOARD_CACHE) > 500:
                _DASHBOARD_CACHE.clear()
            _DASHBOARD_CACHE[key] = (time.monotonic() + ttl, data)
        return data

    async def _compute_dashboard(self, *, tenant: Tenant, date_from: date, date_to: date) -> dict:
        tenant_id = tenant.id
        return_period = date.today().strftime("%Y-%m")

        # Four independent read-only lanes (see parallel.py) — each KPI still
        # calls the SAME report-service method as its detailed report.
        async def lane_sales(sess: AsyncSession):
            sales = await SalesReportService(sess).get_sales_summary(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
            purchase = await PurchaseReportService(sess).get_purchase_summary(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
            top, _ = await SalesReportService(sess).get_product_wise_sales(
                tenant_id=tenant_id, date_from=date_from, date_to=date_to, page=1, page_size=_TOP_N,
            )
            return sales, purchase, top

        async def lane_parties(sess: AsyncSession):
            _, _, rec = await ReceivablesPayablesService(sess).get_receivables(tenant_id=tenant_id, page=1, page_size=1, customer_id=None)
            _, _, pay = await ReceivablesPayablesService(sess).get_payables(tenant_id=tenant_id, page=1, page_size=1, supplier_id=None)
            return rec, pay

        async def lane_aging(sess: AsyncSession):
            svc = DashboardService(sess)
            aging, top_customers = await svc._receivables_aging_and_top_customers(tenant_id)
            top_suppliers = await svc._top_suppliers(tenant_id)
            return aging, top_customers, top_suppliers

        async def lane_stock_gst(sess: AsyncSession):
            _, low = await InventoryReportService(sess).get_current_stock(tenant_id=tenant_id, page=1, page_size=1, status_filter=LOW_STOCK, search=None)
            _, out = await InventoryReportService(sess).get_current_stock(tenant_id=tenant_id, page=1, page_size=1, status_filter=OUT_OF_STOCK, search=None)
            return low, out

        async def lane_gst_payments(sess: AsyncSession):
            gst = await GstrService(sess).dashboard(tenant_id=tenant_id, return_period=return_period)
            svc = DashboardService(sess)
            coll = await svc._payment_total(tenant_id=tenant_id, party_type=PAYMENT_CUSTOMER, date_from=date_from, date_to=date_to)
            supp = await svc._payment_total(tenant_id=tenant_id, party_type=PAYMENT_SUPPLIER, date_from=date_from, date_to=date_to)
            return gst, coll, supp

        async def lane_pipeline(sess: AsyncSession):
            svc = DashboardService(sess)
            return await svc._pipeline_counts(tenant_id), await svc._payment_exceptions(tenant_id)

        (
            (sales_summary, purchase_summary, top_products),
            (receivables_summary_row, payables_summary_row),
            (aging, top_customers, top_suppliers),
            (low_stock_total, out_of_stock_total),
            (gst_dashboard, collections, supplier_payments),
            (pipeline, payment_exceptions),
        ) = await run_lanes(
            self._session, tenant_id,
            [lane_sales, lane_parties, lane_aging, lane_stock_gst, lane_gst_payments, lane_pipeline],
        )
        receivables_summary = receivables_summary_row
        payables_summary = payables_summary_row

        return {
            "period": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
            "sales": {
                "net_sales": sales_summary["net_sales"], "invoice_total": sales_summary["invoice_total"],
                "invoice_count": sales_summary["invoice_count"], "top_products": top_products,
            },
            "purchase": {"net_purchase": purchase_summary["net_purchase"], "invoice_count": purchase_summary["invoice_count"]},
            "receivables": {"total_outstanding": receivables_summary["total_receivables"], "aging": aging, "top_customers": top_customers},
            "payables": {"total_outstanding": payables_summary["total_payables"], "top_suppliers": top_suppliers},
            "inventory": {"low_stock_item_count": low_stock_total, "out_of_stock_item_count": out_of_stock_total, "inventory_value": None},
            "gst": {
                "return_period": return_period, "output_gst": gst_dashboard["output_gst"], "input_gst": gst_dashboard["input_gst"],
                "net_gst_position": gst_dashboard["net_gst_position"],
            },
            "collections": {"customer_collections": collections, "supplier_payments": supplier_payments},
            "pipeline": pipeline,
            "payment_exceptions": payment_exceptions,
        }

    # --- Receivables aging + top customers/suppliers (best-effort, see
    # module docstring on due_date derivation) --------------------------

    async def _receivables_aging_and_top_customers(self, tenant_id: uuid.UUID) -> tuple[dict, list[dict]]:
        rows = (
            await self._session.execute(
                select(
                    SalesInvoice.customer_id, Customer.name, SalesInvoice.invoice_date, Customer.payment_terms_days,
                    (SalesInvoice.grand_total - SalesInvoice.paid_amount),
                )
                .join(Customer, Customer.id == SalesInvoice.customer_id)
                .where(SalesInvoice.tenant_id == tenant_id, SalesInvoice.status == SINV_POSTED, SalesInvoice.payment_status != "PAID")
            )
        ).all()

        today = date.today()
        aging = {bucket: _ZERO for bucket in _AGING_BUCKETS}
        by_customer: dict[uuid.UUID, dict] = {}
        for customer_id, customer_name, invoice_date, terms_days, outstanding in rows:
            if terms_days:
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
            else:
                aging["no_due_date"] += outstanding

            entry = by_customer.setdefault(customer_id, {"customer_id": str(customer_id), "customer_name": customer_name, "outstanding": _ZERO})
            entry["outstanding"] += outstanding

        top_customers = sorted(by_customer.values(), key=lambda r: r["outstanding"], reverse=True)[:_TOP_N]
        return aging, top_customers

    async def _top_suppliers(self, tenant_id: uuid.UUID) -> list[dict]:
        rows = (
            await self._session.execute(
                select(PurchaseInvoice.supplier_id, Supplier.name, func.sum(PurchaseInvoice.grand_total - PurchaseInvoice.paid_amount))
                .join(Supplier, Supplier.id == PurchaseInvoice.supplier_id)
                .where(PurchaseInvoice.tenant_id == tenant_id, PurchaseInvoice.status == PINV_POSTED, PurchaseInvoice.payment_status != "PAID")
                .group_by(PurchaseInvoice.supplier_id, Supplier.name)
                .order_by(func.sum(PurchaseInvoice.grand_total - PurchaseInvoice.paid_amount).desc())
                .limit(_TOP_N)
            )
        ).all()
        return [{"supplier_id": str(supplier_id), "supplier_name": name, "outstanding": outstanding} for supplier_id, name, outstanding in rows]

    # --- Order -> Delivery -> Invoice -> Collection pipeline (§11) -----
    # Definitions used here (no prior codebase concept of "pending
    # invoice"/"pending DC" exists to reuse, so these are the most direct
    # reading of each status field already on the respective table):
    #   open_sales_orders    = SalesOrder not yet fully fulfilled/cancelled
    #   pending_delivery     = DeliveryChallan created but not yet confirmed (DRAFT)
    #   unpaid_invoices      = POSTED SalesInvoice not yet fully paid
    async def _pipeline_counts(self, tenant_id: uuid.UUID) -> dict:
        open_sales_orders = (await self._session.execute(
            select(func.count()).select_from(SalesOrder).where(
                SalesOrder.tenant_id == tenant_id, SalesOrder.status.in_((SO_CONFIRMED, SO_PARTIALLY_FULFILLED)),
            )
        )).scalar_one()
        pending_delivery = (await self._session.execute(
            select(func.count()).select_from(DeliveryChallan).where(DeliveryChallan.tenant_id == tenant_id, DeliveryChallan.status == DC_DRAFT)
        )).scalar_one()
        unpaid_invoices = (await self._session.execute(
            select(func.count()).select_from(SalesInvoice).where(
                SalesInvoice.tenant_id == tenant_id, SalesInvoice.status == SINV_POSTED, SalesInvoice.payment_status != "PAID",
            )
        )).scalar_one()
        return {"open_sales_orders": open_sales_orders, "pending_delivery_challans": pending_delivery, "unpaid_invoices": unpaid_invoices}

    async def _payment_exceptions(self, tenant_id: uuid.UUID) -> dict:
        unallocated = (await self._session.execute(
            select(func.count()).select_from(Payment).where(
                Payment.tenant_id == tenant_id, Payment.status == PAYMENT_POSTED, Payment.unallocated_amount > 0,
            )
        )).scalar_one()
        cheque_pending = (await self._session.execute(
            select(func.count()).select_from(Payment).where(
                Payment.tenant_id == tenant_id, Payment.payment_method == PAYMENT_METHOD_CHEQUE, Payment.cheque_status == CHEQUE_PENDING,
            )
        )).scalar_one()
        cheque_bounced = (await self._session.execute(
            select(func.count()).select_from(Payment).where(
                Payment.tenant_id == tenant_id, Payment.payment_method == PAYMENT_METHOD_CHEQUE, Payment.cheque_status == CHEQUE_BOUNCED,
            )
        )).scalar_one()
        return {"unallocated_payments": unallocated, "cheques_pending": cheque_pending, "cheques_bounced": cheque_bounced}

    # --- Action Required / Alert Center (§17) ---------------------------
    # Pure read-time aggregation over already-authoritative sources — no
    # new alert/notification table. Each item names its own source so the
    # frontend can link straight to the right screen.
    async def get_alerts(self, *, tenant_id: uuid.UUID) -> list[dict]:
        alerts: list[dict] = []

        _, low_stock_count = await InventoryReportService(self._session).get_current_stock(tenant_id=tenant_id, page=1, page_size=1, status_filter=LOW_STOCK, search=None)
        if low_stock_count:
            alerts.append({
                "severity": "WARNING", "category": "INVENTORY", "title": f"{low_stock_count} product(s) low on stock",
                "description": "Below their configured reorder level.", "source_module": "inventory", "action_view": "Inventory",
            })
        _, out_of_stock_count = await InventoryReportService(self._session).get_current_stock(tenant_id=tenant_id, page=1, page_size=1, status_filter=OUT_OF_STOCK, search=None)
        if out_of_stock_count:
            alerts.append({
                "severity": "CRITICAL", "category": "INVENTORY", "title": f"{out_of_stock_count} product(s) out of stock",
                "description": "Zero available quantity.", "source_module": "inventory", "action_view": "Inventory",
            })

        aging, _ = await self._receivables_aging_and_top_customers(tenant_id)
        if aging["days_90_plus"] > 0:
            alerts.append({
                "severity": "CRITICAL", "category": "RECEIVABLES", "title": "Receivables overdue 90+ days",
                "description": f"₹{aging['days_90_plus']:,.2f} outstanding for more than 90 days past due.",
                "source_module": "customer_receipts", "action_view": "CustomerReceiptManagement",
            })
        elif aging["days_61_90"] > 0:
            alerts.append({
                "severity": "WARNING", "category": "RECEIVABLES", "title": "Receivables overdue 61-90 days",
                "description": f"₹{aging['days_61_90']:,.2f} outstanding, 61-90 days past due.",
                "source_module": "customer_receipts", "action_view": "CustomerReceiptManagement",
            })

        exceptions = await self._payment_exceptions(tenant_id)
        if exceptions["cheques_bounced"]:
            alerts.append({
                "severity": "CRITICAL", "category": "PAYMENTS", "title": f"{exceptions['cheques_bounced']} bounced cheque(s)",
                "description": "Requires follow-up with the party.", "source_module": "payments", "action_view": "CustomerReceiptManagement",
            })
        if exceptions["cheques_pending"]:
            alerts.append({
                "severity": "WARNING", "category": "PAYMENTS", "title": f"{exceptions['cheques_pending']} cheque(s) pending clearance",
                "description": "Not yet marked cleared or bounced.", "source_module": "payments", "action_view": "CustomerReceiptManagement",
            })
        if exceptions["unallocated_payments"]:
            alerts.append({
                "severity": "WARNING", "category": "PAYMENTS", "title": f"{exceptions['unallocated_payments']} payment(s) with unallocated amount",
                "description": "Posted but not fully allocated to an invoice.", "source_module": "payments", "action_view": "CustomerReceiptManagement",
            })

        severity_rank = {"CRITICAL": 0, "WARNING": 1, "INFO": 2, "SUCCESS": 3}
        alerts.sort(key=lambda a: severity_rank.get(a["severity"], 9))
        return alerts

    # --- Recent Transactions (§19) --------------------------------------
    # A simple, capped union of the most recent document of each type —
    # not a general activity feed / audit-log reader.
    async def get_recent_transactions(self, *, tenant_id: uuid.UUID, limit: int = _RECENT_TRANSACTIONS_LIMIT) -> list[dict]:
        items: list[dict] = []

        sales_rows = (await self._session.execute(
            select(SalesInvoice.invoice_number, SalesInvoice.invoice_date, SalesInvoice.grand_total, SalesInvoice.status, Customer.name, SalesInvoice.created_at)
            .join(Customer, Customer.id == SalesInvoice.customer_id)
            .where(SalesInvoice.tenant_id == tenant_id).order_by(SalesInvoice.created_at.desc()).limit(limit)
        )).all()
        for number, doc_date, amount, status, party, created_at in sales_rows:
            items.append({
                "type": "SALES_INVOICE", "reference": number, "date": doc_date.isoformat(), "party": party,
                "amount": amount, "status": status, "sort_key": created_at,
            })

        purchase_rows = (await self._session.execute(
            select(PurchaseInvoice.purchase_invoice_number, PurchaseInvoice.document_date, PurchaseInvoice.grand_total, PurchaseInvoice.status, Supplier.name, PurchaseInvoice.created_at)
            .join(Supplier, Supplier.id == PurchaseInvoice.supplier_id)
            .where(PurchaseInvoice.tenant_id == tenant_id).order_by(PurchaseInvoice.created_at.desc()).limit(limit)
        )).all()
        for number, doc_date, amount, status, party, created_at in purchase_rows:
            items.append({
                "type": "PURCHASE_INVOICE", "reference": number, "date": doc_date.isoformat(), "party": party,
                "amount": amount, "status": status, "sort_key": created_at,
            })

        payment_rows = (await self._session.execute(
            select(Payment.payment_number, Payment.payment_date, Payment.amount, Payment.status, Payment.party_type, Customer.name, Supplier.name, Payment.created_at)
            .outerjoin(Customer, Customer.id == Payment.customer_id)
            .outerjoin(Supplier, Supplier.id == Payment.supplier_id)
            .where(Payment.tenant_id == tenant_id).order_by(Payment.created_at.desc()).limit(limit)
        )).all()
        for number, doc_date, amount, status, party_type, customer_name, supplier_name, created_at in payment_rows:
            items.append({
                "type": "CUSTOMER_RECEIPT" if party_type == PAYMENT_CUSTOMER else "SUPPLIER_PAYMENT",
                "reference": number, "date": doc_date.isoformat(), "party": customer_name or supplier_name or party_type.title(),
                "amount": amount, "status": status, "sort_key": created_at,
            })

        items.sort(key=lambda i: i["sort_key"], reverse=True)
        for item in items:
            del item["sort_key"]
        return items[:limit]

    async def _payment_total(self, *, tenant_id: uuid.UUID, party_type: str, date_from: date, date_to: date) -> Decimal:
        result = await self._session.execute(
            select(func.coalesce(func.sum(Payment.amount), _ZERO)).where(
                Payment.tenant_id == tenant_id, Payment.party_type == party_type, Payment.status == PAYMENT_POSTED,
                Payment.payment_date >= date_from, Payment.payment_date <= date_to,
            )
        )
        return result.scalar_one()
