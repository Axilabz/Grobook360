import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

DRAFT = "DRAFT"
CONFIRMED = "CONFIRMED"
CANCELLED = "CANCELLED"

GOODS_RECEIPT_STATUSES = frozenset({DRAFT, CONFIRMED, CANCELLED})

# PROMPT-021 §23-25: cancellation-after-confirmation now IS implemented,
# via a compensating Stock OUT reversal — unlike Delivery Challan/Sales
# Invoice/Sales Return/Purchase Invoice/Purchase Return, which all still
# deliberately resolve this the same way PROMPT-014 originally did
# (DRAFT-only). Goods Receipt is the first Purchase-side document to get
# real reversal support, gated by: (a) no downstream Purchase Invoice has
# been created against any line of this GR (`GoodsReceiptLine.
# invoiced_quantity == 0` for every line), and (b) the InventoryService's
# own negative-stock guard (if the received stock has already been
# consumed elsewhere, the compensating STOCK_OUT is rejected, not forced
# through). See `GoodsReceiptService.cancel_receipt`.
CANCELLABLE_STATUSES = frozenset({DRAFT, CONFIRMED})


class GoodsReceipt(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Goods Receipt header (Data Dictionary: goods_receipt, domain
    PURCHASE; PROMPT-019) — the FIRST Purchase document type that
    actually moves stock (§11: confirmation creates STOCK IN). Mirrors
    `DeliveryChallan`'s role in the Sales chain exactly (a pure
    dispatch/receipt record, source-order-required, first-to-touch-
    inventory document type).

    `source_purchase_order_id` (baseline, nullable): the Data Dictionary
    itself allows a GR without a source PO, but this foundation's own
    primary workflow (§3) only implements PO-sourced receipt — an
    ad-hoc/standalone GR is NOT exercised by any service method in this
    prompt (§46 open decision, flagged in PROMPT-019-NOTES.md, not
    silently assumed either way).

    `supplier_delivery_note` (PROMPT-021, migration 0023): a proposed,
    optional addition — the supplier's own delivery-note/challan
    reference number, per that prompt's own §5/§28 header-field list.
    """

    __tablename__ = "goods_receipt"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    grn_number: Mapped[str] = mapped_column(String(50), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("supplier.id"), nullable=False)
    supplier_gstin: Mapped[str | None] = mapped_column(CHAR(15), nullable=True)
    place_of_supply_state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    source_purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_order.id"), nullable=True
    )
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_delivery_note: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=DRAFT)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    total_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    taxable_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    sgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    igst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
