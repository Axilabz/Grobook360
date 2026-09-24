import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

# FR-STK-04/§13: the five movement types this prompt implements. Direction
# is folded into the type name (no separate ambiguous "direction" column —
# §56). Extending this set (SALES, PURCHASE, SALES_RETURN, PURCHASE_RETURN,
# DELIVERY_CHALLAN, TRANSFER) is for the future Sales/Purchase prompts that
# actually need them, via their own migration against
# ck_stock_ledger_entry_movement_type.
OPENING_STOCK = "OPENING_STOCK"
STOCK_IN = "STOCK_IN"
STOCK_OUT = "STOCK_OUT"
ADJUSTMENT_IN = "ADJUSTMENT_IN"
ADJUSTMENT_OUT = "ADJUSTMENT_OUT"

MOVEMENT_TYPES = frozenset({OPENING_STOCK, STOCK_IN, STOCK_OUT, ADJUSTMENT_IN, ADJUSTMENT_OUT})

# +1 = increases stock, -1 = decreases stock.
MOVEMENT_DIRECTION: dict[str, int] = {
    OPENING_STOCK: 1,
    STOCK_IN: 1,
    ADJUSTMENT_IN: 1,
    STOCK_OUT: -1,
    ADJUSTMENT_OUT: -1,
}


class StockLedgerEntry(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Authoritative stock movement (Data Dictionary: stock_ledger_entry,
    domain INVENTORY, IMMUTABLE/APPEND-ONLY; PROMPT-010).

    `quantity`/`uom_id` are exactly what the caller entered. `base_quantity`
    is a proposed addition — see migration 0011's docstring — that same
    movement normalized to the product's base UOM via Product Master's own
    conversion table, so balance aggregation never needs a per-row
    conversion join.

    Immutable once created: the database revokes UPDATE/DELETE for the
    application role (see migration 0011), mirroring audit_log. Corrections
    must use a compensating movement, never an edit.
    """

    __tablename__ = "stock_ledger_entry"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("product.id"), nullable=False, index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("location.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    uom_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("unit_of_measure.id"), nullable=False)
    base_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    batch_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
