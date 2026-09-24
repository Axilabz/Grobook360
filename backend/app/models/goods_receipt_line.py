import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class GoodsReceiptLine(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Goods Receipt line item (Data Dictionary: goods_receipt_line,
    domain PURCHASE; PROMPT-019). Mirrors `DeliveryChallanLine`'s shape:
    `ordered_quantity`/`previously_received_quantity`/`remaining_
    quantity` are snapshots refreshed to LIVE values from
    `purchase_order_line` at CONFIRM time (§9/§28) — see
    `GoodsReceiptService.confirm_receipt`.

    `id` on `stock_ledger_entry.source_id` (source_type='GOODS_RECEIPT')
    references THIS line's id, not the header's — same per-line
    duplicate-movement-protection reasoning as every stock-moving Sales
    document line (the existing `uq_stock_ledger_entry_source` unique
    constraint needs a per-movement-unique key for a multi-line
    document).

    `invoiced_quantity` (proposed addition): cumulative quantity already
    billed via POSTED Purchase Invoices against this GR line. Only ever
    incremented by `PurchaseInvoiceService.post_invoice` — mirrors
    `delivery_challan_line.invoiced_quantity`'s identical pattern.
    """

    __tablename__ = "goods_receipt_line"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("goods_receipt.id"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_purchase_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_order_line.id"), nullable=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("product.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hsn_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
    previously_received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
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
    invoiced_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
