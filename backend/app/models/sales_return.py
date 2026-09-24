import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

# §13: the prompt's own recommended baseline, adopted verbatim. Named
# CONFIRMED (not "POSTED") since a Sales Return is an inventory-only
# document like Delivery Challan, not a billing document like Sales
# Invoice.
DRAFT = "DRAFT"
CONFIRMED = "CONFIRMED"
CANCELLED = "CANCELLED"

SALES_RETURN_STATUSES = frozenset({DRAFT, CONFIRMED, CANCELLED})

# §25/§47 open decisions #9-10: cancellation-after-confirmation (with
# stock reversal) is NOT implemented — mirrors Delivery Challan/Sales
# Invoice's identical resolution. Only DRAFT is cancellable.
CANCELLABLE_STATUSES = frozenset({DRAFT})

# §8/§47 open decision #2: no approved return-reason master exists in the
# FRD/Data Dictionary — this is the prompt's own suggested baseline
# taxonomy, adopted as a PROPOSED (not final) list. REASON_DESCRIPTION is
# required by the service layer when reason == OTHER.
DAMAGED = "DAMAGED"
WRONG_PRODUCT = "WRONG_PRODUCT"
EXCESS_QUANTITY = "EXCESS_QUANTITY"
QUALITY_ISSUE = "QUALITY_ISSUE"
CUSTOMER_REJECTION = "CUSTOMER_REJECTION"
OTHER = "OTHER"

RETURN_REASONS = frozenset({DAMAGED, WRONG_PRODUCT, EXCESS_QUANTITY, QUALITY_ISSUE, CUSTOMER_REJECTION, OTHER})


class SalesReturn(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Sales Return header (Data Dictionary: sales_return, domain SALES;
    PROMPT-016) — records goods physically returned by a customer against
    a specific Sales Invoice. §2's critical rule: confirming this document
    creates STOCK IN (never a Credit Note, never an accounting reversal —
    those are separate, out-of-scope boundaries; see
    `app/services/accounting/accounting_posting_service.py`'s
    `post_sales_return` and `app/services/sales/gst_reporting_service.py`'s
    `record_return_transaction`).

    `source_invoice_id` (baseline, NOT NULL): every Sales Return MUST
    reference a source Sales Invoice — §47 open decision #3 is answered by
    the approved Data Dictionary schema itself, not invented; there is no
    standalone/ad-hoc Sales Return creation path.

    `customer_gstin`/`billing_address`/`shipping_address`/
    `place_of_supply_state_code`: snapshots taken from the source invoice
    at creation time, same principle as every prior Sales document —
    needed to recompute GST treatment consistently at confirm time even if
    the Customer Master record changes later.

    `accounting_posting_reference`/`gst_transaction_reference`: opaque
    integration-boundary references (§21/§22), identical pattern to
    `sales_invoice`'s own two columns. Not foreign keys: neither a real
    ledger table nor a GST transaction table exists yet.

    No `credit_note_id` column: Credit Note is PROMPT-017's own scope
    (§22 explicit boundary) — a Sales Return never automatically creates
    one.
    """

    __tablename__ = "sales_return"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    return_number: Mapped[str] = mapped_column(String(50), nullable=False)
    return_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_invoice_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_invoice.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False)
    customer_gstin: Mapped[str | None] = mapped_column(CHAR(15), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    place_of_supply_state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=DRAFT)
    return_reason: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    total_return_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
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
