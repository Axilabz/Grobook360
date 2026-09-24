import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class AuthSession(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Server-side session/revocation record (proposed schema addition — PROMPT-003).

    Not present in Database Design & Data Dictionary v3.0 (auth wasn't designed
    yet when that baseline was written). Required because PROMPT-001's JWT is
    stateless — without a server-side record, logout cannot actually invalidate
    an issued token before its natural expiry (PROMPT-003 S12/S21). See
    PROMPT-003-NOTES.md.
    """

    __tablename__ = "auth_session"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True
    )
    token_jti: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    device_info: Mapped[str | None] = mapped_column(String(500), nullable=True)
