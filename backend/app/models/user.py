import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class User(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Application user (Data Dictionary: user, domain SECURITY).

    tenant_id is nullable: a Platform Administrator user may be tenant-independent
    (Data Dictionary + FRD Module 11). Ordinary tenant users must have tenant_id set;
    that constraint belongs to the future user-creation service (PROMPT-002), not to
    the column definition itself.

    created_by/updated_by are self-referential FKs to user.id and therefore nullable
    for the same bootstrap reason as Tenant (the first user has no creating user).
    """

    __tablename__ = "user"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=True, index=True
    )
    # Proposed schema addition (PROMPT-005 — see PROMPT-005-NOTES.md): not in
    # Database Design v3.0, not captured at PROMPT-002 sign-up. Nullable
    # because existing sign-up-created users have none; required at the
    # application layer for users created through this prompt's User
    # Management flow.
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
