import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class PurchaseInvoiceLine(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Purchase Invoice line item (Data Dictionary: purchase_invoice_line,
    domain PURCHASE; PROMPT-019). Mirrors `SalesInvoiceLine`'s shape.

    `source_goods_receipt_line_id` (proposed, nullable): links a
    GR-based invoice line back to the specific GR line it bills, the
    same per-line traceability `sales_invoice_line.source_delivery_
    challan_line_id` established.

    `returned_quantity` (proposed addition): cumulative quantity already
    returned via CONFIRMED Purchase Returns against this invoice line.
    Only ever incremented by `PurchaseReturnService.confirm_return` —
    mirrors `sales_invoice_line.returned_quantity`'s identical pattern.

    `source_purchase_order_line_id` (PROMPT-022, migration 0024,
    proposed): set only for a `PURCHASE_ORDER_PURCHASE_INVOICE` line —
    which PO line the user requested this quantity against. The line
    STILL always carries `source_goods_receipt_line_id` too (a PO line's
    requested quantity is fanned out across its own contributing GR
    lines, one `purchase_invoice_line` row per contributing GR line) —
    invoice-before-receipt is not supported by either invoice type.
    """

    __tablename__ = "purchase_invoice_line"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    purchase_invoice_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_invoice.id"), nullable=False, index=True
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
    source_goods_receipt_line_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("goods_receipt_line.id"), nullable=True
    )
    source_purchase_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_order_line.id"), nullable=True
    )
    returned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
