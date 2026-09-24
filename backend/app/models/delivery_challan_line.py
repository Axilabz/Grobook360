import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class DeliveryChallanLine(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Delivery Challan line item (Data Dictionary: delivery_challan_item,
    domain SALES; PROMPT-014). §9's field list is quantity/traceability
    only — no price/GST columns, matching the header.

    `ordered_quantity`/`previously_delivered_quantity`/`remaining_quantity`
    are snapshots, refreshed to live values from `sales_order_line` at
    CONFIRM time (the moment they become historically true) — see
    `DeliveryChallanService.confirm_challan`. At DRAFT time they reflect
    whatever was true when the line was added/edited, which is
    informational only since DRAFT never affects stock or fulfillment.

    `id` on `stock_ledger_entry.source_id` (source_type='DELIVERY_CHALLAN')
    references THIS line's id, not the header's — see
    `delivery_challan_service.py`'s module docstring for why per-line
    source references were required for the existing
    `uq_stock_ledger_entry_source (tenant_id, source_type, source_id)`
    constraint to work correctly for a multi-line document.

    `invoiced_quantity` (PROMPT-015 addition, migration 0017): cumulative
    quantity already billed via POSTED Sales Invoices against this
    delivery line. Only ever incremented by
    `SalesInvoiceService.post_invoice` — never written from anywhere in
    this file. `current_delivery_quantity - invoiced_quantity` is
    "invoiceable quantity" (§24), always derived, never stored
    separately, mirroring `sales_order_line.delivered_quantity`'s
    identical pattern one level up the chain.
    """

    __tablename__ = "delivery_challan_line"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    challan_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("delivery_challan.id"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_sales_order_line_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_order_line.id"), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("product.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hsn_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    uom_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("unit_of_measure.id"), nullable=False)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    previously_delivered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
    current_delivery_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    invoiced_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
