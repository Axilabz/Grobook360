import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class CreditDebitNoteLine(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Credit/Debit Note line item (Data Dictionary: credit_debit_note_line,
    domain SALES; PROMPT-017). Mirrors `SalesReturnLine`'s financial shape
    exactly, plus `source_invoice_line_id` (proposed addition, NOT NULL) —
    §17/§18's core eligibility/pricing requirement: a note line MUST
    reference the specific Sales Invoice line it adjusts so eligible
    remaining quantity/value can be computed and historical pricing
    preserved.

    `unit_price`/`discount_amount`/`gst_rate` are NOT accepted from the
    client: they are derived from the ORIGINATING Sales Invoice line's
    own already-billed pricing, with that line's absolute
    `discount_amount` converted to an equivalent discount PERCENTAGE so
    it scales correctly when the adjustment quantity is smaller than the
    full invoiced quantity — identical proration technique to Sales
    Return's own line pricing (PROMPT-016), and to PROMPT-015's DC-based
    invoice line pricing before that.

    `id` on `stock_ledger_entry.source_id` never applies to this table —
    Credit/Debit Note creates NO stock movement of any kind (§2/§3/§22).
    """

    __tablename__ = "credit_debit_note_line"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    credit_debit_note_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("credit_debit_note.id"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_invoice_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_invoice_line.id"), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("product.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hsn_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    uom_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("unit_of_measure.id"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cess_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    line_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
