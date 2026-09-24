import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

# §8: the prompt's own required controlled document types, matching the
# vocabulary already reserved in app.core.sales_constants since PROMPT-011.
CREDIT_NOTE = "CREDIT_NOTE"
DEBIT_NOTE = "DEBIT_NOTE"

NOTE_TYPES = frozenset({CREDIT_NOTE, DEBIT_NOTE})

# §9: the prompt's own recommended baseline, adopted verbatim.
DRAFT = "DRAFT"
POSTED = "POSTED"
CANCELLED = "CANCELLED"

CREDIT_DEBIT_NOTE_STATUSES = frozenset({DRAFT, POSTED, CANCELLED})

# §30/§53 open decisions #15-17: cancellation-after-posting (with
# accounting/GST reversal) is NOT implemented — mirrors Sales Return/
# Sales Invoice's identical resolution. Only DRAFT is cancellable.
CANCELLABLE_STATUSES = frozenset({DRAFT})


class CreditDebitNote(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Credit Note / Debit Note header (Data Dictionary: credit_debit_note,
    domain SALES; PROMPT-017) — a PURE FINANCIAL ADJUSTMENT document
    against a Sales Invoice. §2/§3/§22's critical rule: this document
    NEVER creates a stock movement, for either note type — verified by a
    dedicated test asserting zero new `stock_ledger_entry` rows, and
    structurally guaranteed by `credit_debit_note_service.py` never
    importing `InventoryService` at all.

    `note_type` distinguishes CREDIT_NOTE (generally reduces amount
    receivable) from DEBIT_NOTE (generally increases it) — both share
    this one table/line pair per the Data Dictionary baseline. `source_
    invoice_id` (baseline, NOT NULL): every note MUST reference a source
    Sales Invoice — no ad-hoc/standalone note, and no Sales-Return-
    sourced note either (§53 open decision #5 — the baseline schema has
    no such column, and no approved requirement confirms that path; see
    PROMPT-017-NOTES.md).

    `reason` is free text, NOT a CHECK-constrained enum (§4/§53 open
    decision #20 explicitly instructs against inventing a reason
    taxonomy here, unlike Sales Return's own prompt).

    `customer_gstin`/`billing_address`/`shipping_address`/
    `place_of_supply_state_code`: snapshots taken from the source invoice
    at creation time, same principle as every prior Sales document.

    `accounting_posting_reference`/`gst_transaction_reference`: opaque
    integration-boundary references (§20/§21), identical pattern to
    `sales_invoice`/`sales_return`'s own two columns. Not foreign keys:
    neither a real ledger table nor a GST transaction table exists yet.
    """

    __tablename__ = "credit_debit_note"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    note_number: Mapped[str] = mapped_column(String(50), nullable=False)
    note_type: Mapped[str] = mapped_column(String(20), nullable=False)
    note_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_invoice_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_invoice.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False)
    customer_gstin: Mapped[str | None] = mapped_column(CHAR(15), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    place_of_supply_state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=DRAFT)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    taxable_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    sgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    igst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    accounting_posting_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gst_transaction_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
