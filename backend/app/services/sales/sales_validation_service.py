"""Sales & Billing shared validation (PROMPT-011).

§17/§18: before any future Sales line/document can be accepted, the
customer and product it references must be validated the same way every
time — reusing CustomerService/ProductService (PROMPT-007/009) rather than
each future document-type prompt re-querying/re-checking ownership and
status itself. Never trust customer_id/product_id ownership from the
client (§17/§18) — these always resolve via the authenticated tenant_id.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import (
    SALES_CUSTOMER_INACTIVE,
    SALES_CUSTOMER_NOT_FOUND,
    SALES_PRODUCT_INACTIVE,
    SALES_PRODUCT_NOT_FOUND,
)
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.customer import Customer
from app.models.product import Product
from app.models.unit_of_measure import UnitOfMeasure
from app.services.customers.customer_service import CustomerService
from app.services.products.product_service import ProductService


@dataclass(frozen=True)
class ValidatedCustomer:
    customer: Customer
    is_b2b: bool  # §16: derived from GSTIN presence, same rule as FR-CUST-03


async def validate_customer_for_sale(
    session: AsyncSession, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, require_active: bool = True
) -> ValidatedCustomer:
    service = CustomerService(session)
    try:
        customer = await service.get_customer(tenant_id=tenant_id, customer_id=customer_id)
    except NotFoundError as exc:
        # Re-raised under this module's own error code so a future Sales
        # endpoint's error catalogue is self-describing, while keeping the
        # same cross-tenant-is-404 behavior (§17.2/§59).
        raise NotFoundError("Customer not found", code=SALES_CUSTOMER_NOT_FOUND) from exc

    if require_active and customer.status != "ACTIVE":
        raise ValidationAppError(
            "This customer cannot be used for this transaction.", code=SALES_CUSTOMER_INACTIVE
        )

    return ValidatedCustomer(customer=customer, is_b2b=customer.gstin is not None)


@dataclass(frozen=True)
class ValidatedProduct:
    product: Product
    base_uom: UnitOfMeasure


async def validate_product_for_sale(
    session: AsyncSession, *, tenant_id: uuid.UUID, product_id: uuid.UUID, require_active: bool = True
) -> ValidatedProduct:
    service = ProductService(session)
    try:
        product, base_uom, _ = await service.get_product(tenant_id=tenant_id, product_id=product_id)
    except NotFoundError as exc:
        raise NotFoundError("Product not found", code=SALES_PRODUCT_NOT_FOUND) from exc

    if require_active and product.status != "ACTIVE":
        raise ValidationAppError("This product is inactive.", code=SALES_PRODUCT_INACTIVE)

    return ValidatedProduct(product=product, base_uom=base_uom)
