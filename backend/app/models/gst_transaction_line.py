import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class GstTransactionLine(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """GST transaction line (PROMPT-026 §22) — one HSN-level detail row
    of a `GstTransaction`, copied verbatim from the source document's own
    line (`sales_invoice_line`, `purchase_invoice_line`, etc.). Exists so
    the HSN/SAC Summary section of GSTR-1 (§28) can be computed by a
    GROUP BY on this table instead of re-joining back to whichever of the
    six different source line tables produced the parent transaction.
    """

    __tablename__ = "gst_transaction_line"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    gst_transaction_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("gst_transaction.id"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    hsn_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    taxable_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cess_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    line_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
