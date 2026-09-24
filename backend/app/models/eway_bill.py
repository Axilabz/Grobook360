import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

# §15 (extended to E-Way Bill per §21's parallel status needs) — same
# shared vocabulary as `einvoice.status`, see that model's docstring.
NOT_APPLICABLE = "NOT_APPLICABLE"
READY = "READY"
QUEUED = "QUEUED"
PROCESSING = "PROCESSING"
GENERATED = "GENERATED"
FAILED = "FAILED"
CANCEL_REQUESTED = "CANCEL_REQUESTED"
CANCELLED = "CANCELLED"
STATUS_UNKNOWN = "STATUS_UNKNOWN"

EWAY_BILL_STATUSES = frozenset(
    {NOT_APPLICABLE, READY, QUEUED, PROCESSING, GENERATED, FAILED, CANCEL_REQUESTED, CANCELLED, STATUS_UNKNOWN}
)

LOCKED_STATUSES = frozenset({PROCESSING, CANCEL_REQUESTED})
CANCELLABLE_STATUSES = frozenset({GENERATED, STATUS_UNKNOWN})

SALES_INVOICE_SOURCE = "SALES_INVOICE"


class EwayBill(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """E-Way Bill integration record (PROMPT-018 §21). `sales_invoice_id`
    is UNIQUE per tenant — this MVP scopes E-Way Bill generation to
    Sales-Invoice-sourced transactions only (§53 open decision: no
    consolidated/multi-document E-Way Bill support). `source_type` is
    kept as a forward-compatible descriptive field (currently always
    `'SALES_INVOICE'`) even though the FK itself is concrete, so a future
    prompt adding another source document type has a clear extension
    point without a breaking schema change.

    Transport fields (`transport_mode`/`vehicle_number`/
    `transporter_id`/`transporter_name`/`distance_km`) are captured at
    generation time — no separate Transporter Master exists yet (§53
    open decision #16, "Transporter/vehicle master requirements" —
    explicitly unresolved, plain text fields used as a placeholder).
    """

    __tablename__ = "eway_bill"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default=SALES_INVOICE_SOURCE)
    sales_invoice_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_invoice.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=READY)
    applicability_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    eway_bill_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transport_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vehicle_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    transporter_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    transporter_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_response_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_response_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_operation_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
