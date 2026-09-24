"""PROMPT-011 tests for the Sales & Billing foundation:
sales_validation_service and the Inventory post_movement integration
contract future Sales document prompts will call.
"""

import uuid
from decimal import Decimal

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.customer import Customer
from app.models.product import Product
from app.models.stock_ledger_entry import STOCK_IN, STOCK_OUT
from app.models.tenant import Tenant
from app.models.unit_of_measure import UnitOfMeasure
from app.models.user import User
from app.services.inventory.inventory_service import InventoryService
from app.services.sales.sales_validation_service import (
    validate_customer_for_sale,
    validate_product_for_sale,
)


async def _make_tenant(session) -> Tenant:
    tenant = Tenant(business_name=f"Sales Foundation Co {uuid.uuid4().hex[:6]}")
    session.add(tenant)
    await session.flush()
    return tenant


async def _make_actor(session, tenant: Tenant) -> User:
    # product.updated_by/created_by are real FKs to user.id — a random
    # UUID actor_user_id would violate that constraint at flush time.
    user = User(
        tenant_id=tenant.id,
        email=f"actor-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        status="ACTIVE",
    )
    session.add(user)
    await session.flush()
    return user


async def _make_customer(session, tenant: Tenant, *, status: str = "ACTIVE") -> Customer:
    customer = Customer(
        tenant_id=tenant.id,
        customer_code=f"CUST-{uuid.uuid4().hex[:6]}",
        name="Test Customer",
        owner_name="Owner",
        status=status,
    )
    session.add(customer)
    await session.flush()
    return customer


async def _make_unit(session, tenant: Tenant, code: str = "PCS") -> UnitOfMeasure:
    unit = UnitOfMeasure(tenant_id=tenant.id, code=code, name=code.title())
    session.add(unit)
    await session.flush()
    return unit


async def _make_product(session, tenant: Tenant, unit: UnitOfMeasure, *, status: str = "ACTIVE") -> Product:
    product = Product(
        tenant_id=tenant.id,
        sku=f"SKU-{uuid.uuid4().hex[:6]}".upper(),
        name="Test Product",
        base_uom_id=unit.id,
        status=status,
    )
    session.add(product)
    await session.flush()
    return product


# --- sales_validation_service ---


async def test_validate_customer_for_sale_success(db_session):
    tenant = await _make_tenant(db_session)
    customer = await _make_customer(db_session, tenant)

    result = await validate_customer_for_sale(db_session, tenant_id=tenant.id, customer_id=customer.id)
    assert result.customer.id == customer.id
    assert result.is_b2b is False  # no GSTIN


async def test_validate_customer_for_sale_not_found(db_session):
    tenant = await _make_tenant(db_session)
    with pytest.raises(NotFoundError):
        await validate_customer_for_sale(db_session, tenant_id=tenant.id, customer_id=uuid.uuid4())


async def test_validate_customer_for_sale_cross_tenant_not_found(db_session):
    tenant_a = await _make_tenant(db_session)
    tenant_b = await _make_tenant(db_session)
    customer = await _make_customer(db_session, tenant_a)

    with pytest.raises(NotFoundError):
        await validate_customer_for_sale(db_session, tenant_id=tenant_b.id, customer_id=customer.id)


async def test_validate_customer_for_sale_inactive_rejected(db_session):
    tenant = await _make_tenant(db_session)
    customer = await _make_customer(db_session, tenant, status="INACTIVE")

    with pytest.raises(ValidationAppError):
        await validate_customer_for_sale(db_session, tenant_id=tenant.id, customer_id=customer.id)


async def test_validate_product_for_sale_success(db_session):
    tenant = await _make_tenant(db_session)
    unit = await _make_unit(db_session, tenant)
    product = await _make_product(db_session, tenant, unit)

    result = await validate_product_for_sale(db_session, tenant_id=tenant.id, product_id=product.id)
    assert result.product.id == product.id
    assert result.base_uom.id == unit.id


async def test_validate_product_for_sale_inactive_rejected(db_session):
    tenant = await _make_tenant(db_session)
    unit = await _make_unit(db_session, tenant)
    product = await _make_product(db_session, tenant, unit, status="INACTIVE")

    with pytest.raises(ValidationAppError):
        await validate_product_for_sale(db_session, tenant_id=tenant.id, product_id=product.id)


async def test_validate_product_for_sale_cross_tenant_not_found(db_session):
    tenant_a = await _make_tenant(db_session)
    tenant_b = await _make_tenant(db_session)
    unit = await _make_unit(db_session, tenant_a)
    product = await _make_product(db_session, tenant_a, unit)

    with pytest.raises(NotFoundError):
        await validate_product_for_sale(db_session, tenant_id=tenant_b.id, product_id=product.id)


# --- Inventory post_movement as the Sales integration contract ---


async def test_sales_style_stock_out_via_post_movement(db_session):
    """Simulates what a future Delivery Challan / direct Sales Invoice
    posting will do: call InventoryService.post_movement with its own
    source_type/source_id, never touching the ledger/cache directly."""
    tenant = await _make_tenant(db_session)
    actor = await _make_actor(db_session, tenant)
    unit = await _make_unit(db_session, tenant)
    product = await _make_product(db_session, tenant, unit)

    service = InventoryService(db_session)
    location = await service.ensure_default_location(tenant.id)

    # Seed stock the way opening-stock would.
    await service.post_movement(
        tenant_id=tenant.id,
        actor_user_id=actor.id,
        product=product,
        location=location,
        movement_type=STOCK_IN,
        quantity=Decimal("50"),
        uom=unit,
        source_type="OPENING_STOCK",
        source_id=product.id,
        audit_action="OPENING_STOCK_CREATED",
        audit_extra=None,
        ip_address=None,
    )
    assert product.stock_qty_cache == Decimal("50.000")

    fake_invoice_id = uuid.uuid4()
    await service.post_movement(
        tenant_id=tenant.id,
        actor_user_id=actor.id,
        product=product,
        location=location,
        movement_type=STOCK_OUT,
        quantity=Decimal("12"),
        uom=unit,
        source_type="SALES_INVOICE",
        source_id=fake_invoice_id,
        audit_action="STOCK_MOVEMENT_CREATED",
        audit_extra={"note": "simulated direct sales invoice stock-out"},
        ip_address=None,
    )
    assert product.stock_qty_cache == Decimal("38.000")


async def test_sales_style_stock_out_respects_negative_stock_policy(db_session):
    tenant = await _make_tenant(db_session)
    actor = await _make_actor(db_session, tenant)
    unit = await _make_unit(db_session, tenant)
    product = await _make_product(db_session, tenant, unit)

    service = InventoryService(db_session)
    location = await service.ensure_default_location(tenant.id)

    with pytest.raises(ConflictError):
        await service.post_movement(
            tenant_id=tenant.id,
            actor_user_id=actor.id,
            product=product,
            location=location,
            movement_type=STOCK_OUT,
            quantity=Decimal("5"),
            uom=unit,
            source_type="SALES_INVOICE",
            source_id=uuid.uuid4(),
            audit_action="STOCK_MOVEMENT_CREATED",
            audit_extra=None,
            ip_address=None,
        )
