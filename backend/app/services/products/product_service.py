"""Product Master service (PROMPT-009).

Authorization is enforced by the router (require_permission) before these
methods run; this service assumes the caller is already authorized and
focuses on tenant scoping, validation, duplicate rules and concurrency —
mirroring app.services.customers.customer_service's shape.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.concurrency import check_row_version
from app.core.error_codes import (
    PROD_DUPLICATE_CONVERSION,
    PROD_DUPLICATE_SKU,
    PROD_INVALID_SUPPLIER,
    PROD_INVALID_UOM,
    PROD_NOT_FOUND,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.product import Product
from app.models.product_unit_conversion import ProductUnitConversion
from app.models.supplier import Supplier
from app.models.unit_of_measure import UnitOfMeasure
from app.services.audit.audit_service import AuditService


@dataclass(frozen=True)
class ProductPage:
    items: list[tuple[Product, UnitOfMeasure, Supplier | None]]  # (product, base_uom, supplier)
    total_items: int


def _snapshot(product: Product) -> dict:
    return {
        "sku": product.sku,
        "name": product.name,
        "hsn_code": product.hsn_code,
        "gst_rate": str(product.gst_rate) if product.gst_rate is not None else None,
        "base_uom_id": str(product.base_uom_id),
        "supplier_id": str(product.supplier_id) if product.supplier_id is not None else None,
        "cost_price": str(product.cost_price),
        "selling_price": str(product.selling_price),
        "mrp": str(product.mrp),
    }


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_unit_or_raise(self, tenant_id: uuid.UUID, unit_id: uuid.UUID) -> UnitOfMeasure:
        result = await self._session.execute(
            select(UnitOfMeasure).where(UnitOfMeasure.id == unit_id, UnitOfMeasure.tenant_id == tenant_id)
        )
        unit = result.scalar_one_or_none()
        if unit is None:
            raise ValidationAppError("Selected unit of measure does not exist.", code=PROD_INVALID_UOM)
        return unit

    async def _get_supplier_or_raise(self, tenant_id: uuid.UUID, supplier_id: uuid.UUID) -> Supplier:
        result = await self._session.execute(
            select(Supplier).where(Supplier.id == supplier_id, Supplier.tenant_id == tenant_id)
        )
        supplier = result.scalar_one_or_none()
        if supplier is None:
            raise ValidationAppError("Selected supplier does not exist.", code=PROD_INVALID_SUPPLIER)
        return supplier

    async def _check_duplicate_sku(
        self, tenant_id: uuid.UUID, sku: str, *, exclude_product_id: uuid.UUID | None = None
    ) -> None:
        stmt = select(Product).where(Product.tenant_id == tenant_id, Product.sku == sku)
        if exclude_product_id is not None:
            stmt = stmt.where(Product.id != exclude_product_id)
        existing = (await self._session.execute(stmt)).scalars().first()
        if existing is not None:
            raise ConflictError("A product with this code already exists.", code=PROD_DUPLICATE_SKU)

    async def list_products(
        self,
        *,
        tenant_id: uuid.UUID,
        page: int,
        page_size: int,
        search: str | None,
        status_filter: str | None,
    ) -> ProductPage:
        base = (
            select(Product, UnitOfMeasure, Supplier)
            .join(UnitOfMeasure, UnitOfMeasure.id == Product.base_uom_id)
            .outerjoin(Supplier, Supplier.id == Product.supplier_id)
            .where(Product.tenant_id == tenant_id)
        )

        if search:
            like = f"%{search}%"
            base = base.where(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.hsn_code.ilike(like)))
        if status_filter:
            base = base.where(Product.status == status_filter)

        count_stmt = select(func.count()).select_from(base.subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(Product.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        return ProductPage(items=[(row[0], row[1], row[2]) for row in rows], total_items=total_items)

    async def get_product(
        self, *, tenant_id: uuid.UUID, product_id: uuid.UUID
    ) -> tuple[Product, UnitOfMeasure, Supplier | None]:
        result = await self._session.execute(
            select(Product, UnitOfMeasure, Supplier)
            .join(UnitOfMeasure, UnitOfMeasure.id == Product.base_uom_id)
            .outerjoin(Supplier, Supplier.id == Product.supplier_id)
            .where(Product.id == product_id, Product.tenant_id == tenant_id)
        )
        row = result.first()
        if row is None:
            # Same message whether product_id doesn't exist at all or
            # belongs to another tenant (established pattern, PROMPT-005/007/008).
            raise NotFoundError("Product not found", code=PROD_NOT_FOUND)
        return row[0], row[1], row[2]

    async def list_unit_conversions(
        self, *, tenant_id: uuid.UUID, product_id: uuid.UUID
    ) -> list[tuple[ProductUnitConversion, UnitOfMeasure, UnitOfMeasure]]:
        from_uom = aliased(UnitOfMeasure)
        to_uom = aliased(UnitOfMeasure)
        result = await self._session.execute(
            select(ProductUnitConversion, from_uom, to_uom)
            .join(from_uom, from_uom.id == ProductUnitConversion.from_uom_id)
            .join(to_uom, to_uom.id == ProductUnitConversion.to_uom_id)
            .where(ProductUnitConversion.tenant_id == tenant_id, ProductUnitConversion.product_id == product_id)
            .order_by(ProductUnitConversion.created_at)
        )
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def create_product(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        sku: str,
        name: str,
        hsn_code: str | None,
        gst_rate: Decimal,
        base_uom_id: uuid.UUID,
        supplier_id: uuid.UUID | None,
        cost_price: Decimal,
        selling_price: Decimal,
        mrp: Decimal,
        ip_address: str | None,
    ) -> tuple[Product, UnitOfMeasure, Supplier | None]:
        await self._check_duplicate_sku(tenant_id, sku)
        base_uom = await self._get_unit_or_raise(tenant_id, base_uom_id)
        supplier = await self._get_supplier_or_raise(tenant_id, supplier_id) if supplier_id is not None else None

        product = Product(
            tenant_id=tenant_id,
            sku=sku,
            name=name,
            hsn_code=hsn_code,
            gst_rate=gst_rate,
            base_uom_id=base_uom.id,
            supplier_id=supplier.id if supplier is not None else None,
            cost_price=cost_price,
            selling_price=selling_price,
            mrp=mrp,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(product)
                await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError("A product with this code already exists.", code=PROD_DUPLICATE_SKU) from exc

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="PRODUCT_CREATED",
            entity_type="product",
            entity_id=product.id,
            after=_snapshot(product),
            ip_address=ip_address,
        )
        return product, base_uom, supplier

    async def update_product(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        product_id: uuid.UUID,
        expected_row_version: int,
        ip_address: str | None,
        **fields,
    ) -> tuple[Product, UnitOfMeasure, Supplier | None]:
        product, base_uom, supplier = await self.get_product(tenant_id=tenant_id, product_id=product_id)
        check_row_version(product, expected_row_version)
        before = _snapshot(product)

        new_sku = fields.get("sku", ...)
        if new_sku is not ... and new_sku != product.sku:
            await self._check_duplicate_sku(tenant_id, new_sku, exclude_product_id=product.id)
            product.sku = new_sku

        new_base_uom_id = fields.get("base_uom_id", ...)
        if new_base_uom_id is not ...:
            base_uom = await self._get_unit_or_raise(tenant_id, uuid.UUID(new_base_uom_id))
            product.base_uom_id = base_uom.id

        new_supplier_id = fields.get("supplier_id", ...)
        if new_supplier_id is not ...:
            if new_supplier_id is None:
                supplier = None
                product.supplier_id = None
            else:
                supplier = await self._get_supplier_or_raise(tenant_id, uuid.UUID(new_supplier_id))
                product.supplier_id = supplier.id

        for field_name in ("name", "hsn_code", "gst_rate", "cost_price", "selling_price", "mrp"):
            value = fields.get(field_name, ...)
            if value is not ...:
                setattr(product, field_name, value)

        product.updated_by = actor_user_id
        product.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="PRODUCT_UPDATED",
            entity_type="product",
            entity_id=product.id,
            before=before,
            after=_snapshot(product),
            ip_address=ip_address,
        )
        return product, base_uom, supplier

    async def _set_status(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        product_id: uuid.UUID,
        new_status: str,
        expected_row_version: int,
        ip_address: str | None,
    ) -> tuple[Product, UnitOfMeasure, Supplier | None]:
        product, base_uom, supplier = await self.get_product(tenant_id=tenant_id, product_id=product_id)
        check_row_version(product, expected_row_version)

        previous_status = product.status
        product.status = new_status
        product.updated_by = actor_user_id
        product.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="PRODUCT_ACTIVATED" if new_status == "ACTIVE" else "PRODUCT_DEACTIVATED",
            entity_type="product",
            entity_id=product.id,
            before={"status": previous_status},
            after={"status": new_status},
            ip_address=ip_address,
        )
        return product, base_uom, supplier

    async def activate_product(self, **kwargs) -> tuple[Product, UnitOfMeasure, Supplier | None]:
        return await self._set_status(new_status="ACTIVE", **kwargs)

    async def deactivate_product(self, **kwargs) -> tuple[Product, UnitOfMeasure, Supplier | None]:
        return await self._set_status(new_status="INACTIVE", **kwargs)

    async def add_unit_conversion(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        product_id: uuid.UUID,
        from_uom_id: uuid.UUID,
        to_uom_id: uuid.UUID,
        conversion_factor: Decimal,
        ip_address: str | None,
    ) -> tuple[ProductUnitConversion, UnitOfMeasure, UnitOfMeasure]:
        product, _, _ = await self.get_product(tenant_id=tenant_id, product_id=product_id)
        from_uom = await self._get_unit_or_raise(tenant_id, from_uom_id)
        to_uom = await self._get_unit_or_raise(tenant_id, to_uom_id)

        if from_uom.id == to_uom.id:
            raise ValidationAppError("Source and target unit must be different.", code=PROD_INVALID_UOM)

        existing = await self._session.execute(
            select(ProductUnitConversion).where(
                ProductUnitConversion.tenant_id == tenant_id,
                ProductUnitConversion.product_id == product.id,
                ProductUnitConversion.from_uom_id == from_uom.id,
                ProductUnitConversion.to_uom_id == to_uom.id,
            )
        )
        if existing.scalars().first() is not None:
            raise ConflictError(
                "A conversion between these units already exists for this product.", code=PROD_DUPLICATE_CONVERSION
            )

        conversion = ProductUnitConversion(
            tenant_id=tenant_id,
            product_id=product.id,
            from_uom_id=from_uom.id,
            to_uom_id=to_uom.id,
            conversion_factor=conversion_factor,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(conversion)
                await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError(
                "A conversion between these units already exists for this product.", code=PROD_DUPLICATE_CONVERSION
            ) from exc

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="PRODUCT_UNIT_CONVERSION_CREATED",
            entity_type="product_unit_conversion",
            entity_id=conversion.id,
            after={
                "product_id": str(product.id),
                "from_uom": from_uom.code,
                "to_uom": to_uom.code,
                "conversion_factor": str(conversion_factor),
            },
            ip_address=ip_address,
        )
        return conversion, from_uom, to_uom
