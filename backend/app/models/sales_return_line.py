import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class SalesReturnLine(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Sales Return line item (Data Dictionary: sales_return_line, domain
    SALES; PROMPT-016). Mirrors `SalesInvoiceLine`'s financial shape,
    plus `source_invoice_line_id` (proposed addition, NOT NULL) — §6/§12's
    core traceability requirement: a return line MUST reference the
    specific Sales Invoice line it returns against so Returnable Quantity
    (§7 = invoiced quantity - previously returned quantity) can be
    computed and validated.

    `unit_price`/`discount_amount`/`gst_rate` are NOT accepted from the
    client (§15/§16/§17 open decisions #15-17, resolved the same way
    PROMPT-015 resolved DC-based invoice line pricing): they are derived
    from the ORIGINATING Sales Invoice line's own already-billed pricing,
    with that line's absolute `discount_amount` converted to an
    equivalent discount PERCENTAGE so it scales correctly when the return
    quantity is smaller than the full invoiced quantity (partial return)
    — see `sales_return_service.py`'s module docstring for the exact
    formula, identical in shape to the Delivery-Challan-to-Invoice
    proration PROMPT-015 already established.

    `id` on `stock_ledger_entry.source_id` (source_type='SALES_RETURN')
    references THIS line's id, not the header's — same per-line
    duplicate-movement-protection reasoning as every prior stock-moving
    Sales document line.
    """

    __tablename__ = "sales_return_line"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    sales_return_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_return.id"), nullable=False, index=True
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
