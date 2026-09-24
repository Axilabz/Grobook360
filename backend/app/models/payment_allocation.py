import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class PaymentAllocation(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Payment Allocation (PROMPT-024) — §2's structural enforcement that
    a Payment is NOT the same concept as how it is applied to an
    invoice. Exactly one of `sales_invoice_id`/`purchase_invoice_id` is
    set per row (DB CHECK, migration 0025), matching the parent
    Payment's own `party_type` (re-validated in `PaymentService`, never
    trusted from the client).

    A DRAFT payment's allocation rows exist only as a soft, non-
    authoritative preview of intent — they do NOT affect invoice
    `paid_amount` until the parent Payment is POSTED (mirrors the
    established "DRAFT never has financial/stock effect" rule used by
    every document type in this codebase). Rows are never deleted after
    posting; a REVERSED payment's allocation rows remain for audit
    history — `PaymentService`'s paid-amount recalculation only
    aggregates allocations whose PARENT payment is currently POSTED.
    """

    __tablename__ = "payment_allocation"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payment.id"), nullable=False, index=True)
    sales_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_invoice.id"), nullable=True
    )
    purchase_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_invoice.id"), nullable=True
    )
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
