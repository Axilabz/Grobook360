import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class UserRole(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """User-role assignment (Data Dictionary: user_role, domain SECURITY)."""

    __tablename__ = "user_role"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "role_id", name="uq_user_role_assignment"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("role.id"), nullable=False, index=True
    )
