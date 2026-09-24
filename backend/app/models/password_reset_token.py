import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class PasswordResetToken(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Password-reset token record (proposed schema addition — PROMPT-004).

    Not present in Database Design & Data Dictionary v3.0 (password recovery
    wasn't designed yet when that baseline was written). Only a SHA-256 digest
    of the token is stored, never the raw value (PROMPT-004 S10). A row is
    valid only while consumed_at IS NULL, revoked_at IS NULL, and
    expires_at > now() — see app/services/auth/password_reset_service.py.
    See PROMPT-004-NOTES.md.
    """

    __tablename__ = "password_reset_token"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    request_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
