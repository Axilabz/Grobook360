"""Product Master endpoints (PROMPT-009).

Mirrors app/api/v1/customers.py's shape: thin router, permission-code
authorization, tenant context resolved server-side only (never from the
request body), service layer does the real work. Unit conversions are a
nested sub-resource of a product (S43: "use an appropriate nested
resource... do not create duplicate APIs").
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.exceptions import AuthorizationError
from app.core.permissions import (
    PRODUCTS_ACTIVATE,
    PRODUCTS_CREATE,
    PRODUCTS_DEACTIVATE,
    PRODUCTS_UPDATE,
    PRODUCTS_VIEW,
)
from app.db.session import get_db_session
from app.models.product import Product
from app.models.product_unit_conversion import ProductUnitConversion
from app.models.supplier import Supplier
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.envelopes import Pagination
from app.schemas.product import (
    ActivateDeactivateProductRequest,
    CreateProductRequest,
    CreateProductUnitConversionRequest,
    ProductDetail,
    ProductListItem,
    ProductUnitConversionItem,
    SupplierRef,
    UnitRef,
    UpdateProductRequest,
)
from app.services.products.product_service import ProductService

router = APIRouter(prefix="/products", tags=["products"])


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


def _to_unit_ref(unit: UnitOfMeasure) -> UnitRef:
    return UnitRef(id=str(unit.id), code=unit.code, name=unit.name)


def _to_supplier_ref(supplier: Supplier | None) -> SupplierRef | None:
    if supplier is None:
        return None
    return SupplierRef(id=str(supplier.id), name=supplier.name, supplier_code=supplier.supplier_code, phone=supplier.phone)


def _to_list_item(product: Product, base_uom: UnitOfMeasure, supplier: Supplier | None) -> ProductListItem:
    return ProductListItem(
        id=str(product.id),
        sku=product.sku,
        name=product.name,
        hsn_code=product.hsn_code,
        gst_rate=str(product.gst_rate) if product.gst_rate is not None else None,
        base_uom=_to_unit_ref(base_uom),
        supplier=_to_supplier_ref(supplier),
        cost_price=str(product.cost_price),
        selling_price=str(product.selling_price),
        mrp=str(product.mrp),
        reorder_level=str(product.reorder_level),
        stock_qty_cache=str(product.stock_qty_cache),
        status=product.status,
        created_at=product.created_at.isoformat(),
        updated_at=product.updated_at.isoformat(),
        row_version=product.row_version,
    )


def _to_conversion_item(conversion: ProductUnitConversion, from_uom: UnitOfMeasure, to_uom: UnitOfMeasure) -> ProductUnitConversionItem:
    return ProductUnitConversionItem(
        id=str(conversion.id),
        from_uom=_to_unit_ref(from_uom),
        to_uom=_to_unit_ref(to_uom),
        conversion_factor=str(conversion.conversion_factor),
    )


async def _to_detail(
    service: ProductService, tenant_id: uuid.UUID, product: Product, base_uom: UnitOfMeasure, supplier: Supplier | None
) -> ProductDetail:
    conversions = await service.list_unit_conversions(tenant_id=tenant_id, product_id=product.id)
    return ProductDetail(
        **_to_list_item(product, base_uom, supplier).model_dump(),
        unit_conversions=[_to_conversion_item(c, f, t).model_dump() for c, f, t in conversions],
    )


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    # Platform Administrator has no tenant_id — Products is "No" access for
    # Platform Admin (FRD Table 7), so this router is structurally
    # unreachable for platform accounts regardless.
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


@router.get("")
async def list_products(
    request: Request,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    status: str | None = None,
    context: AuthenticatedContext = Depends(require_permission(PRODUCTS_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)

    service = ProductService(session)
    result = await service.list_products(tenant_id=tenant_id, page=page, page_size=page_size, search=search, status_filter=status)

    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(p, u, s).model_dump() for p, u, s in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/{product_id}")
async def get_product(
    product_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(PRODUCTS_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = ProductService(session)
    product, base_uom, supplier = await service.get_product(tenant_id=tenant_id, product_id=product_id)
    detail = await _to_detail(service, tenant_id, product, base_uom, supplier)
    return {"data": detail.model_dump(), "meta": _meta()}


@router.post("", status_code=201)
async def create_product(
    request: Request,
    payload: CreateProductRequest,
    context: AuthenticatedContext = Depends(require_permission(PRODUCTS_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = ProductService(session)
    product, base_uom, supplier = await service.create_product(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        sku=payload.sku,
        name=payload.name,
        hsn_code=payload.hsn_code,
        gst_rate=payload.gst_rate,
        base_uom_id=uuid.UUID(payload.base_uom_id),
        supplier_id=uuid.UUID(payload.supplier_id) if payload.supplier_id else None,
        cost_price=payload.cost_price,
        selling_price=payload.selling_price,
        mrp=payload.mrp,
        ip_address=client_ip,
    )
    await session.commit()
    detail = await _to_detail(service, tenant_id, product, base_uom, supplier)
    return {"data": detail.model_dump(), "meta": _meta()}


@router.patch("/{product_id}")
async def update_product(
    request: Request,
    product_id: uuid.UUID,
    payload: UpdateProductRequest,
    context: AuthenticatedContext = Depends(require_permission(PRODUCTS_UPDATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    update_fields = payload.model_dump(exclude={"expected_row_version"}, exclude_unset=True)

    service = ProductService(session)
    product, base_uom, supplier = await service.update_product(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        product_id=product_id,
        expected_row_version=payload.expected_row_version,
        ip_address=client_ip,
        **update_fields,
    )
    await session.commit()
    detail = await _to_detail(service, tenant_id, product, base_uom, supplier)
    return {"data": detail.model_dump(), "meta": _meta()}


@router.post("/{product_id}/activate")
async def activate_product(
    request: Request,
    product_id: uuid.UUID,
    payload: ActivateDeactivateProductRequest,
    context: AuthenticatedContext = Depends(require_permission(PRODUCTS_ACTIVATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = ProductService(session)
    product, base_uom, supplier = await service.activate_product(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        product_id=product_id,
        expected_row_version=payload.expected_row_version,
        ip_address=client_ip,
    )
    await session.commit()
    detail = await _to_detail(service, tenant_id, product, base_uom, supplier)
    return {"data": detail.model_dump(), "meta": _meta()}


@router.post("/{product_id}/deactivate")
async def deactivate_product(
    request: Request,
    product_id: uuid.UUID,
    payload: ActivateDeactivateProductRequest,
    context: AuthenticatedContext = Depends(require_permission(PRODUCTS_DEACTIVATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = ProductService(session)
    product, base_uom, supplier = await service.deactivate_product(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        product_id=product_id,
        expected_row_version=payload.expected_row_version,
        ip_address=client_ip,
    )
    await session.commit()
    detail = await _to_detail(service, tenant_id, product, base_uom, supplier)
    return {"data": detail.model_dump(), "meta": _meta()}


@router.post("/{product_id}/conversions", status_code=201)
async def create_unit_conversion(
    request: Request,
    product_id: uuid.UUID,
    payload: CreateProductUnitConversionRequest,
    context: AuthenticatedContext = Depends(require_permission(PRODUCTS_UPDATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = ProductService(session)
    conversion, from_uom, to_uom = await service.add_unit_conversion(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        product_id=product_id,
        from_uom_id=uuid.UUID(payload.from_uom_id),
        to_uom_id=uuid.UUID(payload.to_uom_id),
        conversion_factor=payload.conversion_factor,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_conversion_item(conversion, from_uom, to_uom).model_dump(), "meta": _meta()}
