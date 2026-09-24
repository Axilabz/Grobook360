import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

DRAFT = "DRAFT"
POSTED = "POSTED"
CANCELLED = "CANCELLED"

PURCHASE_INVOICE_STATUSES = frozenset({DRAFT, POSTED, CANCELLED})
# PROMPT-022 §33-35: a POSTED invoice IS now cancellable — a DIRECT
# invoice's cancellation reverses its own Stock IN via a compensating
# Stock OUT; a GR/PO-sourced invoice's cancellation never touches stock
# (only releases its bookkeeping claim on the source GR line(s)' own
# `invoiced_quantity`) — see `PurchaseInvoiceService.cancel_invoice`.
CANCELLABLE_STATUSES = frozenset({DRAFT, POSTED})

# §12/§6: the three controlled sourcing paths this prompt implements.
# PURCHASE_ORDER_PURCHASE_INVOICE (PROMPT-022, "Supported Flow 2") lets
# one invoice consolidate eligible quantity across MULTIPLE confirmed
# Goods Receipts under a single Purchase Order — every one of its lines
# still traces to a specific `goods_receipt_line` via `source_goods_
# receipt_line_id` (never invoice-before-receipt; see PROMPT-022-NOTES.md
# Open Decision #2), the header's `source_purchase_order_id` is purely a
# traceability/eligibility-computation convenience, not a second
# "invoice against raw PO quantity" path.
DIRECT_PURCHASE_INVOICE = "DIRECT_PURCHASE_INVOICE"
GOODS_RECEIPT_PURCHASE_INVOICE = "GOODS_RECEIPT_PURCHASE_INVOICE"
PURCHASE_ORDER_PURCHASE_INVOICE = "PURCHASE_ORDER_PURCHASE_INVOICE"

INVOICE_TYPES = frozenset({DIRECT_PURCHASE_INVOICE, GOODS_RECEIPT_PURCHASE_INVOICE, PURCHASE_ORDER_PURCHASE_INVOICE})
# Both GR-sourced and PO-consolidated invoices bill quantity that was
# already received — neither ever creates a Stock IN of its own (§12
# Scenario A). Only a DIRECT invoice can create one (Scenario B).
NO_STOCK_IMPACT_INVOICE_TYPES = frozenset({GOODS_RECEIPT_PURCHASE_INVOICE, PURCHASE_ORDER_PURCHASE_INVOICE})


class PurchaseInvoice(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Purchase Invoice header (Data Dictionary: purchase_invoice, domain
    PURCHASE; PROMPT-019) — mirrors `SalesInvoice`'s central §2 rule,
    inverted: a DIRECT invoice (no source GR) creates its own Stock IN at
    posting time; a GOODS_RECEIPT-sourced invoice creates NONE (the
    source GR already did) — the double-stock-IN prevention is
    structural (§12), verified by a dedicated test.

    `source_goods_receipt_id` (baseline, nullable): NULL for a direct or
    PO-consolidated invoice, set for a single-GR-based one.
    `source_purchase_order_id` (PROMPT-022, migration 0024, proposed):
    NULL unless `invoice_type == PURCHASE_ORDER_PURCHASE_INVOICE` — an
    invoice referencing a PO WITHOUT going through any GR at all
    (invoice-before-receipt) is still NOT supported; see PROMPT-022-
    NOTES.md Open Decision #2.

    `supplier_invoice_number`: baseline, nullable, its own Data
    Dictionary annotation says "Duplicate policy to confirm" — NOT
    enforced unique here (§46 open decision #26 / PROMPT-022 §67 Open
    Decision #7, explicitly flagged by the baseline itself, not
    invented) — `PurchaseInvoiceService` instead surfaces a non-blocking
    `duplicate_supplier_invoice_warning` flag.

    `supplier_invoice_date`/`due_date` (PROMPT-022, migration 0024,
    proposed): distinct from `document_date` (this application's own
    internal invoice date) per that prompt's own §5/§13 header-field
    list.
    """

    __tablename__ = "purchase_invoice"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    purchase_invoice_number: Mapped[str] = mapped_column(String(50), nullable=False)
    supplier_invoice_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    invoice_type: Mapped[str] = mapped_column(String(40), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("supplier.id"), nullable=False)
    supplier_gstin: Mapped[str | None] = mapped_column(CHAR(15), nullable=True)
    place_of_supply_state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    source_goods_receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("goods_receipt.id"), nullable=True
    )
    source_purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_order.id"), nullable=True
    )
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=DRAFT)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    taxable_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    sgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    igst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    # PROMPT-024 §15/§16: reconciliation CACHE columns, identical
    # discipline to sales_invoice's own two columns — authoritative
    # source is SUM(payment_allocation.allocated_amount) across every
    # currently-POSTED Payment allocated to this invoice. Only ever
    # written by PaymentService.
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNPAID")
    # PROMPT-025 §32: opaque accounting-journal reference (mirrors
    # sales_invoice/sales_return/credit_debit_note/payment's own
    # column) — the actual accounting boundary was deliberately
    # excluded from PROMPT-019 §14; this prompt closes that gap.
    accounting_posting_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gst_transaction_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
