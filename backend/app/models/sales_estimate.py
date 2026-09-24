import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CHAR, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

# §12: adopted verbatim from the prompt's own recommended baseline since
# the approved Data Dictionary only says "Controlled lifecycle" without
# enumerating values. CANCELLED added for the .../cancel endpoint §25
# itself suggests. See PROMPT-012-NOTES.md.
DRAFT = "DRAFT"
SENT = "SENT"
ACCEPTED = "ACCEPTED"
REJECTED = "REJECTED"
EXPIRED = "EXPIRED"
CANCELLED = "CANCELLED"
CONVERTED = "CONVERTED"

ESTIMATE_STATUSES = frozenset({DRAFT, SENT, ACCEPTED, REJECTED, EXPIRED, CANCELLED, CONVERTED})

# Terminal statuses: no further transition is possible from any of these.
TERMINAL_STATUSES = frozenset({REJECTED, EXPIRED, CANCELLED, CONVERTED})

# Convert-eligible statuses (§12/§21, open decision resolved — see
# PROMPT-012-NOTES.md): no customer self-service portal exists to drive
# ACCEPTED externally, so DRAFT/SENT/ACCEPTED are all conversion-eligible
# rather than gating on ACCEPTED alone.
CONVERTIBLE_STATUSES = frozenset({DRAFT, SENT, ACCEPTED})


class SalesEstimate(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Sales Estimate header (Data Dictionary: estimate, domain SALES;
    PROMPT-012). See migration 0014's docstring for the full field-by-field
    schema assessment (proposed additions: valid_until_date,
    customer_gstin/billing_address/place_of_supply_state_code snapshots,
    cgst_total/sgst_total/igst_total, notes, converted_at).
    """

    __tablename__ = "sales_estimate"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    estimate_number: Mapped[str] = mapped_column(String(50), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False)
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=DRAFT)
    customer_gstin: Mapped[str | None] = mapped_column(CHAR(15), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    place_of_supply_state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    taxable_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    sgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    igst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
