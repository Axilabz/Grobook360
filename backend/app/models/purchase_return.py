import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

DRAFT = "DRAFT"
CONFIRMED = "CONFIRMED"
CANCELLED = "CANCELLED"

PURCHASE_RETURN_STATUSES = frozenset({DRAFT, CONFIRMED, CANCELLED})
# PROMPT-023 §33-35: a CONFIRMED return can now also be cancelled, via a
# controlled reversal (compensating STOCK_IN) — mirrors Goods Receipt's
# own PROMPT-021 precedent exactly. A DRAFT cancellation remains a pure
# status flip (nothing ever moved stock for it, INVARIANT 2).
CANCELLABLE_STATUSES = frozenset({DRAFT, CONFIRMED})

# §20/§46 open decision #20: no approved return-reason master exists —
# same resolution as Sales Return (PROMPT-016), the prompt's own
# suggested baseline taxonomy adopted as PROPOSED, not final.
DAMAGED = "DAMAGED"
WRONG_PRODUCT = "WRONG_PRODUCT"
EXCESS_QUANTITY = "EXCESS_QUANTITY"
QUALITY_ISSUE = "QUALITY_ISSUE"
PRICE_DISPUTE = "PRICE_DISPUTE"
OTHER = "OTHER"

RETURN_REASONS = frozenset({DAMAGED, WRONG_PRODUCT, EXCESS_QUANTITY, QUALITY_ISSUE, PRICE_DISPUTE, OTHER})


class PurchaseReturn(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Purchase Return header (Data Dictionary: purchase_return, domain
    PURCHASE; PROMPT-019) — goods physically returned TO the supplier.
    §13's critical rule: confirmation creates STOCK OUT (the mirror
    image of Sales Return's STOCK IN, PROMPT-016).

    `source_purchase_invoice_id` (baseline, NOT NULL): every Purchase
    Return MUST reference a source Purchase Invoice — resolves §46 open
    decision #18 ("Purchase Return against Invoice only vs GR/other
    sources") by the approved schema itself: Invoice only, no ad-hoc
    return, identical resolution class to Sales Return's own NOT NULL
    `source_invoice_id`.
    """

    __tablename__ = "purchase_return"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    purchase_return_number: Mapped[str] = mapped_column(String(50), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("supplier.id"), nullable=False)
    supplier_gstin: Mapped[str | None] = mapped_column(CHAR(15), nullable=True)
    place_of_supply_state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    source_purchase_invoice_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_invoice.id"), nullable=False
    )
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
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
    # PROMPT-025 §32: opaque accounting-journal reference, same pattern
    # as every other posted document type.
    accounting_posting_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gst_transaction_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
