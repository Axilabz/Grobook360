import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class StockAdjustment(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Controlled stock adjustment header (Data Dictionary: stock_adjustment,
    domain INVENTORY; PROMPT-010).

    Referenced by exactly one stock_ledger_entry as
    source_type='STOCK_ADJUSTMENT'. DRAFT/approved_by/approved_at exist per
    the approved schema, but this MVP self-approves atomically at creation
    (creator == approver) — no source defines a separate reviewer role. See
    PROMPT-010-NOTES.md.
    """

    __tablename__ = "stock_adjustment"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    adjustment_number: Mapped[str] = mapped_column(String(50), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("location.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
