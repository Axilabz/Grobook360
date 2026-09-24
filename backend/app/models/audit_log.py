import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPKMixin, utcnow


class AuditLog(UUIDPKMixin, Base):
    """Immutable audit trail (Data Dictionary: audit_log, domain SECURITY).

    Deliberately has no row_version and no updated_by/updated_at: audit records are
    append-only and must never be edited (Table Register IMMUTABLE/APPEND-ONLY=YES).
    Enforced at the database level by a BEFORE UPDATE/DELETE trigger
    (`trg_audit_log_immutable`, migration 0012) that unconditionally raises.
    Migration 0001's `REVOKE UPDATE, DELETE ... FROM PUBLIC` is kept alongside it
    for defense-in-depth but does not by itself enforce anything, since the
    application's DB role owns this table and table ownership in PostgreSQL
    bypasses the owner's own grant/revoke restrictions — only the trigger fires
    regardless of ownership.
    """

    __tablename__ = "audit_log"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    before_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    device_info: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
