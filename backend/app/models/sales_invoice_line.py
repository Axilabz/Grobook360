import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class SalesInvoiceLine(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Sales Invoice line item (Data Dictionary: sales_invoice_item,
    domain SALES; PROMPT-015). Mirrors `SalesOrderLine`'s financial shape
    exactly, plus `source_delivery_challan_line_id` (proposed addition) —
    §24's per-DC-line invoiceable-quantity tracking needs a stable link
    one level up the chain, the same pattern `delivery_challan_line.
    source_sales_order_line_id` already established.

    For a DELIVERY_CHALLAN_SALES_INVOICE, `unit_price`/`discount_amount`/
    `gst_rate` are NOT copied verbatim from the source Delivery Challan
    line (which has none — a Delivery Challan carries no pricing at all,
    per PROMPT-014). They are derived from the ORIGINATING Sales Order
    line's own already-agreed pricing snapshot, proportionally recomputed
    for the (possibly smaller, if partially invoicing) quantity being
    billed now — see `sales_invoice_service.py`'s module docstring for
    the exact proration formula.

    `returned_quantity` (PROMPT-016 addition, migration 0018): cumulative
    quantity already returned via CONFIRMED Sales Returns against this
    invoice line. Only ever incremented by
    `SalesReturnService.confirm_return` — never written from anywhere in
    this file. `quantity - returned_quantity` is "returnable quantity"
    (§7), always derived, never stored separately, mirroring
    `delivery_challan_line.invoiced_quantity`'s identical pattern one
    level up the chain.

    `credited_quantity` / `debited_quantity` (PROMPT-017 addition,
    migration 0019): cumulative quantity already adjusted via POSTED
    Credit Notes / Debit Notes against this invoice line. Only ever
    incremented by `CreditDebitNoteService.post_note`, per `note_type`.
    `quantity - credited_quantity` is "creditable quantity" (§15/§17);
    the debited-quantity cap is a deliberately conservative placeholder
    for Debit Note (§53 open decision #10/#28 — the true eligibility rule
    for a Debit Note is NOT confirmed by any approved source).
    """

    __tablename__ = "sales_invoice_line"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_invoice.id"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
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
    source_delivery_challan_line_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("delivery_challan_line.id"), nullable=True
    )
    returned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
    credited_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
    debited_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
