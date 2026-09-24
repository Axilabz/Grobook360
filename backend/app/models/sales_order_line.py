import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class SalesOrderLine(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Sales Order line item (Data Dictionary: sales_order_item, domain
    SALES; PROMPT-013). Mirrors `SalesEstimateLine`'s shape exactly.

    `delivered_quantity` (PROMPT-014 addition, migration 0016): cumulative
    quantity actually dispatched via CONFIRMED Delivery Challans against
    this line. Starts at 0; only ever incremented by
    `SalesOrderService.apply_delivery`, called from
    `DeliveryChallanService.confirm_challan` inside that same transaction
    — never written from anywhere in this file. `quantity - delivered_quantity`
    is "remaining quantity" (§23), always derived, never stored separately
    (a stored remaining column would just be a second place the same fact
    could drift out of sync).
    """

    __tablename__ = "sales_order_line"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_order.id"), nullable=False, index=True
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
    delivered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
