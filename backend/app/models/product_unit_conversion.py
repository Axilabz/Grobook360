import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class ProductUnitConversion(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Product-specific UOM conversion (Data Dictionary: product_unit_conversion,
    domain MASTER; PROMPT-009).

    UNIQUE(tenant_id, product_id, from_uom_id, to_uom_id) and
    CHECK(from_uom_id <> to_uom_id) are proposed additions beyond the Data
    Dictionary — see migration 0010's docstring.
    """

    __tablename__ = "product_unit_conversion"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("product.id"), nullable=False, index=True
    )
    from_uom_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("unit_of_measure.id"), nullable=False)
    to_uom_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("unit_of_measure.id"), nullable=False)
    conversion_factor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
