import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

EINVOICE = "EINVOICE"
EWAY_BILL = "EWAY_BILL"
ENTITY_TYPES = frozenset({EINVOICE, EWAY_BILL})

GENERATE = "GENERATE"
CANCEL = "CANCEL"
STATUS_CHECK = "STATUS_CHECK"
OPERATION_TYPES = frozenset({GENERATE, CANCEL, STATUS_CHECK})

PENDING = "PENDING"
IN_PROGRESS = "IN_PROGRESS"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"
OPERATION_STATUSES = frozenset({PENDING, IN_PROGRESS, SUCCEEDED, FAILED, UNKNOWN})


class IntegrationOperation(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Integration operation log (PROMPT-018 §29) — the operational
    history of every GENERATE/CANCEL/STATUS_CHECK attempt against an
    `einvoice`/`eway_bill` row. This is NOT the idempotency mechanism
    itself (the existing `idempotency_key` table + `IdempotencyService`
    already handles "same HTTP request retried with the same
    client-supplied Idempotency-Key" verbatim) — it is the audit/
    reconciliation trail, and the evidence a concurrent request checks
    (via the parent `einvoice`/`eway_bill` row's own `status`, read under
    a row lock) before starting a second operation (§11/§38).

    `status=UNKNOWN` is the §24 "critical scenario" state: the request
    was sent, but no confirmed response was received (timeout/network
    interruption) — `EInvoiceService`/`EWayBillService` MUST reconcile
    (call `get_irn_status`/`get_eway_bill_status`) before allowing a
    fresh GENERATE against the same entity, never blindly retry.
    """

    __tablename__ = "integration_operation"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    operation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PENDING)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    response_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
