import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

# §11: "Do not create unnecessary Delivery Challan statuses" — only the
# three the prompt's own recommended baseline names. No fulfillment-style
# status lives here; that belongs to the source Sales Order (§23).
DRAFT = "DRAFT"
CONFIRMED = "CONFIRMED"
CANCELLED = "CANCELLED"

DELIVERY_CHALLAN_STATUSES = frozenset({DRAFT, CONFIRMED, CANCELLED})

# §11/§45 open decision #3: cancelling a CONFIRMED (stock-already-reduced)
# Delivery Challan would require a compensating STOCK_IN reversal, which
# the prompt explicitly says to implement ONLY if approved — no approved
# source authorizes it here. Resolved conservatively: only DRAFT (which
# never touched stock) may be cancelled in this prompt. See
# PROMPT-014-NOTES.md.
CANCELLABLE_STATUSES = frozenset({DRAFT})


class DeliveryChallan(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Delivery Challan header (Data Dictionary: delivery_challan, domain
    SALES; PROMPT-014). A pure dispatch/goods-movement document — unlike
    Estimate/Sales Order, it carries NO pricing or GST fields at all
    (§9's own header/line field list has none), since financial value is
    already fixed on the source Sales Order and will be invoiced later.

    `source_sales_order_id` is NOT NULL: this prompt implements ONLY the
    "create from Sales Order" flow (§12) — standalone Delivery Challans
    with no source order are explicitly not supported (open decision #11,
    resolved conservatively; see PROMPT-014-NOTES.md).

    `shipping_address` defaults to the source Sales Order's own shipping
    address at creation time but is independently editable (open decision
    #17 — "whether shipping address can differ from Sales Order" —
    resolved as yes, since goods can legitimately ship to a different dock
    than what was quoted).
    """

    __tablename__ = "delivery_challan"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    challan_number: Mapped[str] = mapped_column(String(50), nullable=False)
    challan_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_sales_order_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_order.id"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=DRAFT)
    billing_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    place_of_supply_state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    total_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
