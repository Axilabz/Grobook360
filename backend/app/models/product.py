import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class Product(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Product master (Data Dictionary: product, domain MASTER; PROMPT-009).

    Fully specified by the approved baseline for this prompt's scope — no
    proposed field additions. Deliberately has NO category/subcategory/
    brand/product_type/description columns: absent from both the Data
    Dictionary and FR-PROD-01, so not part of the approved MVP model.

    `reorder_level`, `stock_qty_cache`, `batch_no`, `expiry_date` exist
    exactly as the approved schema defines them but have NO write path in
    this module — see app/services/products/product_service.py and
    migration 0010's docstring (FR-STK-05 / ASM-004 for the cache column;
    the FRD's own Scope Matrix marks Batch/Expiry as still-OPEN).

    `supplier_id`: proposed addition (migration 0030) — the product's
    preferred/primary supplier, nullable (not every product needs one
    recorded). Deliberately NOT paired with denormalized
    supplier_name/supplier_phone columns — the API joins `supplier` at
    read time instead, so those values are always current, never a stale
    copy (see migration 0030's own docstring for the full rationale).
    """

    __tablename__ = "product"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hsn_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    gst_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    base_uom_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("unit_of_measure.id"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supplier.id"), nullable=True, index=True
    )
    cost_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    selling_price: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    mrp: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
    stock_qty_cache: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False, default=0)
    batch_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
