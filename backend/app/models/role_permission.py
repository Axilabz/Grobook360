import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class RolePermission(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Role-permission assignment (Data Dictionary: role_permission, domain SECURITY).

    DOCUMENT CONFLICT (flagged, not silently resolved): the Data Dictionary's
    detailed column list for role_permission omits tenant_id, but the Table
    Register marks role_permission TENANT SCOPED = YES and Constraints & Indexes
    requires idx_role_permission_tenant ON (tenant_id). tenant_id is included here
    per the majority of sources and for consistency with every other SECURITY-domain
    table; see PROMPT-001 response notes for this open item.
    """

    __tablename__ = "role_permission"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permission_assignment"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("role.id"), nullable=False, index=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("permission.id"), nullable=False, index=True
    )
