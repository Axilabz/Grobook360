import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPKMixin, utcnow


class IdempotencyKey(UUIDPKMixin, Base):
    """Idempotent-request record (proposed schema addition — see PROMPT-002 notes).

    Not present in Database Design & Data Dictionary v3.0. Added because API
    Contract Specification v1.0 S10.1 requires storing "key + tenant +
    endpoint/operation + request fingerprint + resulting resource" for any
    idempotent create/financial operation, and no table exists for it. tenant_id
    is nullable because tenant sign-up itself is idempotent and has no tenant yet
    at request time.
    """

    __tablename__ = "idempotency_key"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
