import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class PurchaseOrderLine(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Purchase Order line item (Data Dictionary: purchase_order_line,
    domain PURCHASE; PROMPT-019).

    `received_quantity` (proposed addition): cumulative quantity already
    received via CONFIRMED Goods Receipts against this PO line. Only
    ever incremented by `GoodsReceiptService.confirm_receipt` — never
    written from anywhere in this file. `quantity - received_quantity`
    is "remaining quantity" (§8), always derived, never stored
    separately — identical pattern to `sales_order_line.delivered_
    quantity`.

    `hsn_code`: line-level HSN snapshot, same as every Sales document
    line.
    """

    __tablename__ = "purchase_order_line"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_order.id"), nullable=False, index=True
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
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
