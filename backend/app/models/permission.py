from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class Permission(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Global permission catalogue (Data Dictionary: permission, domain SECURITY).

    Not tenant-scoped: the catalogue of possible permission codes (e.g.
    "customer.read") is platform-wide; which permissions a tenant's roles hold is
    governed by role_permission, which IS tenant-scoped via role.tenant_id.
    """

    __tablename__ = "permission"

    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
