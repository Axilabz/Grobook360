import uuid

from sqlalchemy import ForeignKey, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class UnitOfMeasure(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Unit of measure (Data Dictionary: unit_of_measure, domain MASTER; PROMPT-009).

    Tenant-scoped controlled master, created because product.base_uom_id is
    a mandatory FK to it — no prior prompt built this table.
    """

    __tablename__ = "unit_of_measure"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    precision: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
