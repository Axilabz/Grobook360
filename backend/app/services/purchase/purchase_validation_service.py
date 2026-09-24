"""Purchase shared validation (PROMPT-019 §19/§20).

Mirrors `app.services.sales.sales_validation_service`'s exact role for
the Sales domain: before any Purchase line/document can be accepted, the
supplier and product it references must be validated the same way every
time — reusing `SupplierService`/`ProductService` (PROMPT-008/009)
rather than each future Purchase document-type prompt re-querying/
re-checking ownership and status itself. Never trust supplier_id/
product_id ownership from the client — these always resolve via the
authenticated tenant_id.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import (
    PURCH_PRODUCT_INACTIVE,
    PURCH_PRODUCT_NOT_FOUND,
    PURCH_SUPPLIER_INACTIVE,
    PURCH_SUPPLIER_NOT_FOUND,
)
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.product import Product
from app.models.supplier import Supplier
from app.models.unit_of_measure import UnitOfMeasure
from app.services.products.product_service import ProductService
from app.services.suppliers.supplier_service import SupplierService


@dataclass(frozen=True)
class ValidatedSupplier:
    supplier: Supplier


async def validate_supplier_for_purchase(
    session: AsyncSession, *, tenant_id: uuid.UUID, supplier_id: uuid.UUID, require_active: bool = True
) -> ValidatedSupplier:
    service = SupplierService(session)
    try:
        supplier = await service.get_supplier(tenant_id=tenant_id, supplier_id=supplier_id)
    except NotFoundError as exc:
        raise NotFoundError("Supplier not found", code=PURCH_SUPPLIER_NOT_FOUND) from exc

    if require_active and supplier.status != "ACTIVE":
        raise ValidationAppError(
            "This supplier cannot be used for this transaction.", code=PURCH_SUPPLIER_INACTIVE
        )

    return ValidatedSupplier(supplier=supplier)


@dataclass(frozen=True)
class ValidatedPurchaseProduct:
    product: Product
    base_uom: UnitOfMeasure


async def validate_product_for_purchase(
    session: AsyncSession, *, tenant_id: uuid.UUID, product_id: uuid.UUID, require_active: bool = True
) -> ValidatedPurchaseProduct:
    service = ProductService(session)
    try:
        product, base_uom, _ = await service.get_product(tenant_id=tenant_id, product_id=product_id)
    except NotFoundError as exc:
        raise NotFoundError("Product not found", code=PURCH_PRODUCT_NOT_FOUND) from exc

    if require_active and product.status != "ACTIVE":
        raise ValidationAppError("This product is inactive.", code=PURCH_PRODUCT_INACTIVE)

    return ValidatedPurchaseProduct(product=product, base_uom=base_uom)
