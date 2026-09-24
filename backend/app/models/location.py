import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class Location(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Business/inventory location (Data Dictionary: location, domain MASTER;
    PROMPT-010).

    §8: M1 supports only one active location. No management API/UI exists —
    a single "MAIN" location is lazily get-or-created per tenant by
    app/services/inventory/inventory_service.py.
    """

    __tablename__ = "location"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
