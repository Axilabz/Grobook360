import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

# §13 of PROMPT-013 deliberately withheld PARTIALLY_FULFILLED/FULFILLED
# until a real Delivery Challan existed to drive them (see that prompt's
# NOTES). PROMPT-014 (Delivery Challan) is that prompt: migration 0016
# widens `ck_sales_order_status` to allow these two additional values, set
# by `SalesOrderService.apply_delivery` as Delivery Challans are confirmed
# against this order's lines — never set directly by any Sales Order
# endpoint itself.
DRAFT = "DRAFT"
CONFIRMED = "CONFIRMED"
PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
FULFILLED = "FULFILLED"
CANCELLED = "CANCELLED"

SALES_ORDER_STATUSES = frozenset({DRAFT, CONFIRMED, PARTIALLY_FULFILLED, FULFILLED, CANCELLED})

# PROMPT-014 §21/§45 open decision: whether a fully FULFILLED order can
# still be cancelled. Resolved as no (nothing left to cancel — every unit
# already physically dispatched); PARTIALLY_FULFILLED remains cancellable
# so the undelivered remainder can still be called off. FULFILLED is now
# the only status that's actually terminal in practice, though CANCELLED
# remains the formal terminal marker.
TERMINAL_STATUSES = frozenset({CANCELLED})

# §21 PROMPT-013 + §45 open decision above: DRAFT/CONFIRMED/
# PARTIALLY_FULFILLED may all be cancelled; FULFILLED may not.
CANCELLABLE_STATUSES = frozenset({DRAFT, CONFIRMED, PARTIALLY_FULFILLED})

# §12 PROMPT-014: which Sales Order statuses may still accept a new
# Delivery Challan. FULFILLED (nothing left) and CANCELLED (order voided)
# are excluded; DRAFT is excluded too — an order must be CONFIRMED (i.e.
# accepted for fulfillment, per PROMPT-013 §20) before anything can be
# dispatched against it.
DELIVERY_ELIGIBLE_STATUSES = frozenset({CONFIRMED, PARTIALLY_FULFILLED})


class SalesOrder(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Sales Order header (Data Dictionary: sales_order, domain SALES;
    PROMPT-013). Mirrors `SalesEstimate`'s shape exactly, plus:

    - `shipping_address` (proposed addition, nullable): §8 lists Billing
      AND Shipping Address as separate header fields, but Customer Master
      (PROMPT-007) has only one address field — nothing to snapshot that
      doesn't already collapse into billing_address. Defaults to the
      customer's address at creation time and can be overridden per order.
    - `source_estimate_id` (nullable, UNIQUE): §16's conversion-integrity
      requirement — one Estimate converts to at most one Sales Order,
      enforced at the DB level, not just by frontend button disabling.

    No `round_off` column: §17/§45 Q17 list it as "where approved" and an
    explicit open decision; no approved source defines a round-off rule,
    so none is added (see PROMPT-013-NOTES.md — do not silently invent).
    "Terms and Conditions" (§8) is folded into `notes`, mirroring
    SalesEstimate's identical resolution rather than adding a second
    near-duplicate free-text column.
    """

    __tablename__ = "sales_order"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    order_number: Mapped[str] = mapped_column(String(50), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=DRAFT)
    customer_gstin: Mapped[str | None] = mapped_column(CHAR(15), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    place_of_supply_state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    source_estimate_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_estimate.id"), nullable=True
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    taxable_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    sgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    igst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Set only by cancel_order (migration 0037) — mirrors einvoice/eway_bill's
    # own cancellation_reason precedent (PROMPT-018).
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
