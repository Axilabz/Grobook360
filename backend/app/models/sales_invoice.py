import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CHAR, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

# §10: the prompt's own recommended baseline, adopted verbatim.
DRAFT = "DRAFT"
POSTED = "POSTED"
CANCELLED = "CANCELLED"

SALES_INVOICE_STATUSES = frozenset({DRAFT, POSTED, CANCELLED})
TERMINAL_STATUSES = frozenset({POSTED, CANCELLED})

# §11/§35/§45 open decisions #4-7: cancellation-after-posting (with
# accounting/stock/GST reversal) is NOT implemented — mirrors Delivery
# Challan's identical resolution in PROMPT-014. Only DRAFT is cancellable.
CANCELLABLE_STATUSES = frozenset({DRAFT})

# §9: the two controlled invoice types this prompt implements.
DIRECT_SALES_INVOICE = "DIRECT_SALES_INVOICE"
DELIVERY_CHALLAN_SALES_INVOICE = "DELIVERY_CHALLAN_SALES_INVOICE"

INVOICE_TYPES = frozenset({DIRECT_SALES_INVOICE, DELIVERY_CHALLAN_SALES_INVOICE})

B2B = "B2B"
B2C = "B2C"


class SalesInvoice(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Sales Invoice header (Data Dictionary: sales_invoice, domain SALES;
    PROMPT-015) — the authoritative billing transaction. Mirrors
    `SalesEstimate`/`SalesOrder`'s financial shape, plus:

    - `invoice_type` / `source_delivery_challan_id` / `source_sales_order_id`:
      §2's critical rule lives here — a DIRECT invoice creates its own
      Stock OUT at posting time; a DELIVERY_CHALLAN invoice creates NONE
      (the source Delivery Challan already did). `source_sales_order_id`
      is populated transitively (copied from the source DC) purely for
      convenient traceability/filtering — it is never itself the
      authority for anything.
    - `customer_type` ('B2B'/'B2C'): §8/§22 GST-reporting metadata,
      derived from GSTIN presence at creation time (same rule
      `ValidatedCustomer.is_b2b` already uses elsewhere).
    - `accounting_posting_reference` / `gst_transaction_reference`:
      opaque integration-boundary references (§21/§22) — see
      `app/services/accounting/accounting_posting_service.py` and
      `app/services/sales/gst_reporting_service.py`. Not foreign keys:
      neither a real ledger table nor a GST transaction table exists yet.
    - `irn` / `ack_number` / `ack_date` / `einvoice_status` /
      `qr_code_data`: e-Invoice integration boundary (§23), reserved for
      PROMPT-018, never written to here.

    No `round_off` column (§17/§52 open decision #17 — no approved rule).
    "Terms" folds into `notes`, identical resolution to every prior Sales
    document.
    """

    __tablename__ = "sales_invoice"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    invoice_type: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False)
    customer_gstin: Mapped[str | None] = mapped_column(CHAR(15), nullable=True)
    customer_type: Mapped[str] = mapped_column(String(10), nullable=False, default=B2C)
    billing_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    place_of_supply_state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    source_delivery_challan_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("delivery_challan.id"), nullable=True
    )
    source_sales_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_order.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=DRAFT)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    taxable_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    sgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    igst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    accounting_posting_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gst_transaction_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    irn: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ack_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ack_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    einvoice_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    qr_code_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PROMPT-024 §15/§16: reconciliation CACHE columns — the authoritative
    # source is SUM(payment_allocation.allocated_amount) across every
    # currently-POSTED Payment allocated to this invoice. Only ever
    # written by PaymentService, transactionally alongside the
    # allocation itself (same discipline as product.stock_qty_cache).
    # Never a manually-editable API field on this invoice (§15).
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNPAID")
