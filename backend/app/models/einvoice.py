import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

# §15: the prompt's own recommended status model, adopted verbatim —
# shared vocabulary with `eway_bill.status` (see that model for the
# identical rationale).
NOT_APPLICABLE = "NOT_APPLICABLE"
READY = "READY"
QUEUED = "QUEUED"
PROCESSING = "PROCESSING"
GENERATED = "GENERATED"
FAILED = "FAILED"
CANCEL_REQUESTED = "CANCEL_REQUESTED"
CANCELLED = "CANCELLED"
STATUS_UNKNOWN = "STATUS_UNKNOWN"

EINVOICE_STATUSES = frozenset(
    {NOT_APPLICABLE, READY, QUEUED, PROCESSING, GENERATED, FAILED, CANCEL_REQUESTED, CANCELLED, STATUS_UNKNOWN}
)

# §11/§38: PROCESSING means "an operation is currently in flight against
# this row" — `EInvoiceService.generate`/`.cancel` locks the row
# (SELECT ... FOR UPDATE) and refuses to start a second operation while
# in this set, exactly like every prior Sales document's confirm/post
# concurrency guard.
LOCKED_STATUSES = frozenset({PROCESSING, CANCEL_REQUESTED})
# §16: only a successfully GENERATED e-invoice can be cancelled.
CANCELLABLE_STATUSES = frozenset({GENERATED, STATUS_UNKNOWN})


class Einvoice(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """E-Invoice integration record (PROMPT-018 §13) — the authoritative,
    audit-grade record of one Sales Invoice's e-invoicing lifecycle.
    `sales_invoice_id` is UNIQUE per tenant: a Sales Invoice gets AT MOST
    one e-invoice record — a cancelled IRN's invoice cannot receive a
    second IRN (§17: corrections use Credit Note/Debit Note/a new
    invoice, never a second IRN against the same invoice).

    `sales_invoice`'s own reserved `irn`/`ack_number`/`ack_date`/
    `einvoice_status`/`qr_code_data` columns (migration 0017, PROMPT-015
    — explicitly "reserved for PROMPT-018") are kept in sync as a
    fast-read DENORMALIZED SNAPSHOT for list-screen display; THIS table
    is the authoritative source of truth.

    `signed_invoice_data`/`signed_qr_data`: the provider's own signed
    payloads, preserved byte-for-byte (§14 explicit requirement — never
    regenerated or altered). Visual QR rendering belongs to the
    print/preview layer, not this table.

    `applicability_result`: a JSON snapshot of the last applicability
    evaluation (`{"applicable": bool, "reason": str, "evaluated_at":
    iso8601, "missing_fields": [...]}`) — §8 explicit output shape.
    """

    __tablename__ = "einvoice"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    sales_invoice_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_invoice.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=READY)
    applicability_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    irn: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ack_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ack_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_invoice_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    signed_qr_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_response_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_response_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_operation_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
