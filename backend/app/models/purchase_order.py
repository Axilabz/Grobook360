import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

# §9: the prompt's own suggested baseline status model, adopted verbatim
# — mirrors Sales Order's identical DRAFT->CONFIRMED->PARTIALLY_X->
# FULLY_X->CANCELLED shape (PROMPT-013/014).
DRAFT = "DRAFT"
CONFIRMED = "CONFIRMED"
PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
FULLY_RECEIVED = "FULLY_RECEIVED"
CANCELLED = "CANCELLED"

PURCHASE_ORDER_STATUSES = frozenset({DRAFT, CONFIRMED, PARTIALLY_RECEIVED, FULLY_RECEIVED, CANCELLED})

# §10 mandatory rule: a Purchase Order NEVER moves stock at any status
# transition — enforced structurally by `purchase_order_service.py`
# never importing InventoryService, exactly like `sales_order_service.py`.
CANCELLABLE_STATUSES = frozenset({DRAFT, CONFIRMED, PARTIALLY_RECEIVED})
RECEIPT_ELIGIBLE_STATUSES = frozenset({CONFIRMED, PARTIALLY_RECEIVED})


class PurchaseOrder(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Purchase Order header (Data Dictionary: purchase_order, domain
    PURCHASE; PROMPT-019) — the first Purchase document type. Mirrors
    `SalesOrder`'s shape closely: never moves stock (§10), tracks
    fulfillment (here: receipt) via `PurchaseOrderLine.received_quantity`
    updated only by `GoodsReceiptService.confirm_receipt`.

    Proposed additions over the Data Dictionary v3.0 baseline (same
    "propose, document, implement" pattern as every Sales prompt):
    `supplier_gstin`/`billing_address`/`shipping_address`/
    `place_of_supply_state_code` (snapshots), `cgst_total`/`sgst_total`/
    `igst_total` (header GST split — baseline only has combined
    `tax_total`), `notes`. PROMPT-020 (migration 0022) additionally adds
    `supplier_reference`/`expected_delivery_date`/`payment_terms`/
    `delivery_terms` — all optional, per that prompt's own §48 Open
    Decisions #6/#7/#8/#9.
    """

    __tablename__ = "purchase_order"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    po_number: Mapped[str] = mapped_column(String(50), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("supplier.id"), nullable=False)
    supplier_gstin: Mapped[str | None] = mapped_column(CHAR(15), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    place_of_supply_state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(200), nullable=True)
    delivery_terms: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=DRAFT)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    taxable_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    sgst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    igst_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
