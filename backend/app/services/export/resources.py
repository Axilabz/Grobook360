"""Export resource registry — the ALLOWLIST of what "resource" strings the
export API accepts (Global Export Framework, cross-cutting prompt).

This is the single place a client-supplied `resource` identifier is
resolved. The frontend NEVER names a database table — only one of these
pre-approved keys (§17 of the source prompt: "never allow the frontend
to provide arbitrary database table names"). Each adapter wraps an
ALREADY-EXISTING service's own list query (never a new, parallel query)
so business logic is never duplicated, and inherits that service's own
tenant-scoping/search/filter behavior exactly as the on-screen grid does.

Adding a new resource to the framework (extending coverage beyond the
initial 7 below) is a mechanical recipe:
  1. Add a `ResourceAdapter` here, wrapping that module's own list_*
     service method and mapping its result rows to `ExportColumn`s.
  2. Add a `<module>.export` permission (permissions.py + a migration
     backfilling it onto OWNER/MANAGER, following 0031's own pattern).
  3. Wire `<ExportButton resource="...">` into that module's screen.
No other framework code needs to change.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import (
    CUSTOMERS_EXPORT,
    CUSTOMER_RECEIPT_EXPORT,
    PRODUCTS_EXPORT,
    PURCHASE_INVOICE_EXPORT,
    SALES_INVOICE_EXPORT,
    SUPPLIERS_EXPORT,
    SUPPLIER_PAYMENT_EXPORT,
)
from app.services.export.columns import ExportColumn, field
from app.services.customers.customer_service import CustomerService
from app.services.suppliers.supplier_service import SupplierService
from app.services.products.product_service import ProductService
from app.services.sales.sales_invoice_service import SalesInvoiceService
from app.services.purchase.purchase_invoice_service import PurchaseInvoiceService
from app.services.payments.payment_service import PaymentService, CUSTOMER as PARTY_CUSTOMER, SUPPLIER as PARTY_SUPPLIER


@dataclass(frozen=True)
class ExportFilters:
    search: str | None = None
    status: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    party_id: uuid.UUID | None = None  # customer_id / supplier_id, resource-dependent


@dataclass(frozen=True)
class ResourceAdapter:
    key: str
    title: str  # human-readable report title, e.g. "Sales Invoices"
    export_permission: str
    columns: list[ExportColumn]
    # Returns (rows, total_items) — rows already mapped to plain dicts
    # matching `columns`' own extractor keys. `row_cap` is the hard max
    # rows this call will ever return (also serves as the SQL LIMIT, so
    # an oversized ALL_FILTERED export is bounded at the query level,
    # never fetched-then-truncated in Python).
    fetch: Callable[[AsyncSession, uuid.UUID, ExportFilters, int, int], Awaitable[tuple[list[dict], int]]]


async def _fetch_customers(session, tenant_id, filters: ExportFilters, page_size: int, page: int):
    result = await CustomerService(session).list_customers(
        tenant_id=tenant_id, page=page, page_size=page_size, search=filters.search,
        status_filter=filters.status, state_code_filter=None, gst_registered=None,
    )
    rows = [
        {
            "customer_code": c.customer_code, "name": c.name, "owner_name": c.owner_name, "phone": c.phone,
            "email": c.email, "gstin": c.gstin, "state_code": c.state_code, "city": c.city, "pincode": c.pincode,
            "credit_limit": c.credit_limit, "balance": c.balance, "status": c.status,
            "created_at": c.created_at.date() if c.created_at else None,
        }
        for c in result.items
    ]
    return rows, result.total_items


async def _fetch_suppliers(session, tenant_id, filters: ExportFilters, page_size: int, page: int):
    result = await SupplierService(session).list_suppliers(
        tenant_id=tenant_id, page=page, page_size=page_size, search=filters.search,
        status_filter=filters.status, state_code_filter=None, gst_registered=None,
    )
    rows = [
        {
            "supplier_code": s.supplier_code, "name": s.name, "contact_person": s.contact_person, "phone": s.phone,
            "email": s.email, "gstin": s.gstin, "state_code": s.state_code, "city": s.city, "pincode": s.pincode,
            "credit_terms_days": s.credit_terms_days, "balance": s.balance, "status": s.status,
            "created_at": s.created_at.date() if s.created_at else None,
        }
        for s in result.items
    ]
    return rows, result.total_items


async def _fetch_products(session, tenant_id, filters: ExportFilters, page_size: int, page: int):
    result = await ProductService(session).list_products(
        tenant_id=tenant_id, page=page, page_size=page_size, search=filters.search, status_filter=filters.status,
    )
    rows = [
        {
            "sku": p.sku, "name": p.name, "hsn_code": p.hsn_code, "gst_rate": p.gst_rate,
            "base_uom": u.code, "supplier": sup.name if sup else None,
            "cost_price": p.cost_price, "selling_price": p.selling_price, "mrp": p.mrp,
            "stock_qty_cache": p.stock_qty_cache, "status": p.status,
        }
        for p, u, sup in result.items
    ]
    return rows, result.total_items


async def _fetch_sales_invoices(session, tenant_id, filters: ExportFilters, page_size: int, page: int):
    result = await SalesInvoiceService(session).list_invoices(
        tenant_id=tenant_id, page=page, page_size=page_size, search=filters.search, status_filter=filters.status,
        invoice_type_filter=None, customer_id=filters.party_id, date_from=filters.date_from, date_to=filters.date_to,
    )
    rows = [
        {
            "invoice_number": inv.invoice_number, "invoice_date": inv.invoice_date, "customer_name": customer_name,
            "status": inv.status, "grand_total": inv.grand_total, "tax_total": inv.tax_total,
            "paid_amount": inv.paid_amount, "payment_status": inv.payment_status,
        }
        for inv, customer_name, _dc in result.items
    ]
    return rows, result.total_items


async def _fetch_purchase_invoices(session, tenant_id, filters: ExportFilters, page_size: int, page: int):
    result = await PurchaseInvoiceService(session).list_invoices(
        tenant_id=tenant_id, page=page, page_size=page_size, search=filters.search, status_filter=filters.status,
        invoice_type_filter=None, supplier_id=filters.party_id, date_from=filters.date_from, date_to=filters.date_to,
    )
    rows = [
        {
            "purchase_invoice_number": inv.purchase_invoice_number, "invoice_date": inv.invoice_date,
            "supplier_name": supplier_name, "status": inv.status, "grand_total": inv.grand_total,
            "tax_total": inv.tax_total, "paid_amount": inv.paid_amount, "payment_status": inv.payment_status,
        }
        for inv, supplier_name, _grn, _po in result.items
    ]
    return rows, result.total_items


def _make_payment_fetcher(party_type: str):
    async def _fetch(session, tenant_id, filters: ExportFilters, page_size: int, page: int):
        result = await PaymentService(session).list_payments(
            tenant_id=tenant_id, party_type=party_type, page=page, page_size=page_size, search=filters.search,
            status_filter=filters.status, party_id=filters.party_id, payment_method_filter=None,
            date_from=filters.date_from, date_to=filters.date_to,
        )
        rows = [
            {
                "payment_number": p.payment_number, "payment_date": p.payment_date, "party_name": party_name,
                "payment_method": p.payment_method, "amount": p.amount, "allocated_amount": p.allocated_amount,
                "unallocated_amount": p.unallocated_amount, "status": p.status,
                "reference_number": p.reference_number,
            }
            for p, party_name in result.items
        ]
        return rows, result.total_items
    return _fetch


RESOURCES: dict[str, ResourceAdapter] = {
    "customers": ResourceAdapter(
        key="customers", title="Customers", export_permission=CUSTOMERS_EXPORT,
        columns=[
            field("customer_code", "Customer Code", "text", 16), field("name", "Customer Name", "text", 28),
            field("owner_name", "Owner Name", "text", 20), field("phone", "Phone", "text", 14),
            field("email", "Email", "text", 26), field("gstin", "GSTIN", "text", 17),
            field("state_code", "State Code", "text", 10), field("city", "City", "text", 16),
            field("pincode", "Pincode", "text", 10), field("credit_limit", "Credit Limit", "currency", 14),
            field("balance", "Balance", "currency", 14), field("status", "Status", "text", 10),
            field("created_at", "Created On", "date", 12),
        ],
        fetch=_fetch_customers,
    ),
    "suppliers": ResourceAdapter(
        key="suppliers", title="Suppliers", export_permission=SUPPLIERS_EXPORT,
        columns=[
            field("supplier_code", "Supplier Code", "text", 16), field("name", "Supplier Name", "text", 28),
            field("contact_person", "Contact Person", "text", 20), field("phone", "Phone", "text", 14),
            field("email", "Email", "text", 26), field("gstin", "GSTIN", "text", 17),
            field("state_code", "State Code", "text", 10), field("city", "City", "text", 16),
            field("pincode", "Pincode", "text", 10), field("credit_terms_days", "Credit Terms (Days)", "number", 14),
            field("balance", "Balance", "currency", 14), field("status", "Status", "text", 10),
            field("created_at", "Created On", "date", 12),
        ],
        fetch=_fetch_suppliers,
    ),
    "products": ResourceAdapter(
        key="products", title="Products", export_permission=PRODUCTS_EXPORT,
        columns=[
            field("sku", "SKU", "text", 16), field("name", "Product Name", "text", 28),
            field("hsn_code", "HSN", "text", 10), field("gst_rate", "GST %", "percent", 8),
            field("base_uom", "Unit", "text", 8), field("supplier", "Supplier", "text", 24),
            field("cost_price", "Cost Price", "currency", 12), field("selling_price", "Selling Price", "currency", 14),
            field("mrp", "MRP", "currency", 12), field("stock_qty_cache", "Stock Qty", "number", 10),
            field("status", "Status", "text", 10),
        ],
        fetch=_fetch_products,
    ),
    "sales_invoices": ResourceAdapter(
        key="sales_invoices", title="Sales Invoices", export_permission=SALES_INVOICE_EXPORT,
        columns=[
            field("invoice_number", "Invoice Number", "text", 18), field("invoice_date", "Invoice Date", "date", 12),
            field("customer_name", "Customer", "text", 26), field("status", "Status", "text", 12),
            field("grand_total", "Grand Total", "currency", 14), field("tax_total", "GST Amount", "currency", 12),
            field("paid_amount", "Paid Amount", "currency", 14), field("payment_status", "Payment Status", "text", 14),
        ],
        fetch=_fetch_sales_invoices,
    ),
    "purchase_invoices": ResourceAdapter(
        key="purchase_invoices", title="Purchase Invoices", export_permission=PURCHASE_INVOICE_EXPORT,
        columns=[
            field("purchase_invoice_number", "Invoice Number", "text", 18), field("invoice_date", "Invoice Date", "date", 12),
            field("supplier_name", "Supplier", "text", 26), field("status", "Status", "text", 12),
            field("grand_total", "Grand Total", "currency", 14), field("tax_total", "GST Amount", "currency", 12),
            field("paid_amount", "Paid Amount", "currency", 14), field("payment_status", "Payment Status", "text", 14),
        ],
        fetch=_fetch_purchase_invoices,
    ),
    "customer_receipts": ResourceAdapter(
        key="customer_receipts", title="Customer Receipts", export_permission=CUSTOMER_RECEIPT_EXPORT,
        columns=[
            field("payment_number", "Receipt Number", "text", 18), field("payment_date", "Date", "date", 12),
            field("party_name", "Customer", "text", 26), field("payment_method", "Method", "text", 12),
            field("amount", "Amount", "currency", 14), field("allocated_amount", "Allocated", "currency", 14),
            field("unallocated_amount", "Unallocated", "currency", 14), field("status", "Status", "text", 12),
            field("reference_number", "Reference", "text", 18),
        ],
        fetch=_make_payment_fetcher(PARTY_CUSTOMER),
    ),
    "supplier_payments": ResourceAdapter(
        key="supplier_payments", title="Supplier Payments", export_permission=SUPPLIER_PAYMENT_EXPORT,
        columns=[
            field("payment_number", "Payment Number", "text", 18), field("payment_date", "Date", "date", 12),
            field("party_name", "Supplier", "text", 26), field("payment_method", "Method", "text", 12),
            field("amount", "Amount", "currency", 14), field("allocated_amount", "Allocated", "currency", 14),
            field("unallocated_amount", "Unallocated", "currency", 14), field("status", "Status", "text", 12),
            field("reference_number", "Reference", "text", 18),
        ],
        fetch=_make_payment_fetcher(PARTY_SUPPLIER),
    ),
}


def get_resource(key: str) -> ResourceAdapter | None:
    return RESOURCES.get(key)
