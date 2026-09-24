"""Supplier Management endpoints (PROMPT-008).

Mirrors app/api/v1/customers.py's shape: thin router, permission-code
authorization, tenant context resolved server-side only (never from the
request body), service layer does the real work.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.exceptions import AuthorizationError
from app.core.permissions import (
    SUPPLIERS_ACTIVATE,
    SUPPLIERS_CREATE,
    SUPPLIERS_DEACTIVATE,
    SUPPLIERS_UPDATE,
    SUPPLIERS_VIEW,
)
from app.db.session import get_db_session
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supplier import Supplier
from app.schemas.supplier import (
    ActivateDeactivateSupplierRequest,
    CreateSupplierRequest,
    SupplierDetail,
    SupplierListItem,
    UpdateSupplierRequest,
)
from app.schemas.envelopes import Pagination
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.suppliers.supplier_service import SupplierService

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


def _to_list_item(supplier: Supplier) -> SupplierListItem:
    return SupplierListItem(
        id=str(supplier.id),
        supplier_code=supplier.supplier_code,
        name=supplier.name,
        contact_person=supplier.contact_person,
        phone=supplier.phone,
        email=supplier.email,
        gstin=supplier.gstin,
        state_code=supplier.state_code,
        address=supplier.address,
        city=supplier.city,
        pincode=supplier.pincode,
        credit_terms_days=supplier.credit_terms_days,
        balance=str(supplier.balance),
        status=supplier.status,
        created_at=supplier.created_at.isoformat(),
        updated_at=supplier.updated_at.isoformat(),
        row_version=supplier.row_version,
    )


def _to_detail(supplier: Supplier) -> SupplierDetail:
    return SupplierDetail(**_to_list_item(supplier).model_dump())


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    # Platform Administrator has no tenant_id — Suppliers is "No" access for
    # Platform Admin (FRD Table 7), so this router is structurally
    # unreachable for platform accounts regardless.
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


@router.get("")
async def list_suppliers(
    request: Request,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    status: str | None = None,
    state_code: str | None = None,
    gst_registered: bool | None = None,
    context: AuthenticatedContext = Depends(require_permission(SUPPLIERS_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)

    service = SupplierService(session)
    result = await service.list_suppliers(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        search=search,
        status_filter=status,
        state_code_filter=state_code,
        gst_registered=gst_registered,
    )

    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_to_list_item(s).model_dump() for s in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/{supplier_id}")
async def get_supplier(
    supplier_id: uuid.UUID,
    context: AuthenticatedContext = Depends(require_permission(SUPPLIERS_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = SupplierService(session)
    supplier = await service.get_supplier(tenant_id=tenant_id, supplier_id=supplier_id)
    return {"data": _to_detail(supplier).model_dump(), "meta": _meta()}


@router.post("", status_code=201)
async def create_supplier(
    request: Request,
    payload: CreateSupplierRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(SUPPLIERS_CREATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """PROMPT-028 §17/§48: `Idempotency-Key` is OPTIONAL (mirrors
    `customers.py`'s identical addition) — existing online callers never
    sent one and keep working unchanged; the offline Supplier quick-add
    sync path sends its own `client_transaction_id` as this header so a
    duplicate replay returns the ORIGINAL response instead of creating a
    second supplier."""
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    async def _execute() -> dict:
        service = SupplierService(session)
        supplier = await service.create_supplier(
            tenant_id=tenant_id,
            actor_user_id=context.user_id,
            name=payload.name,
            contact_person=payload.contact_person,
            phone=payload.phone,
            email=payload.email,
            gstin=payload.gstin,
            state_code=payload.state_code,
            address=payload.address,
            city=payload.city,
            pincode=payload.pincode,
            credit_terms_days=payload.credit_terms_days,
            ip_address=client_ip,
        )
        return {"data": _to_detail(supplier).model_dump(), "meta": _meta()}

    if not idempotency_key:
        response_body = await _execute()
        await session.commit()
        return response_body

    idempotency = IdempotencyService(session)
    request_payload = payload.model_dump(mode="json")
    check_result = await idempotency.check(idempotency_key=idempotency_key, endpoint="POST /api/v1/suppliers", payload=request_payload)
    if check_result.existing_response is not None:
        _, body = check_result.existing_response
        return body

    response_body = await _execute()
    await idempotency.store(
        idempotency_key=idempotency_key, endpoint="POST /api/v1/suppliers", payload=request_payload,
        tenant_id=tenant_id, response_status=201, response_body=response_body,
    )
    await session.commit()
    return response_body


@router.patch("/{supplier_id}")
async def update_supplier(
    request: Request,
    supplier_id: uuid.UUID,
    payload: UpdateSupplierRequest,
    context: AuthenticatedContext = Depends(require_permission(SUPPLIERS_UPDATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    update_fields = payload.model_dump(exclude={"expected_row_version"}, exclude_unset=True)

    service = SupplierService(session)
    supplier = await service.update_supplier(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        supplier_id=supplier_id,
        expected_row_version=payload.expected_row_version,
        ip_address=client_ip,
        **update_fields,
    )
    await session.commit()
    return {"data": _to_detail(supplier).model_dump(), "meta": _meta()}


@router.post("/{supplier_id}/activate")
async def activate_supplier(
    request: Request,
    supplier_id: uuid.UUID,
    payload: ActivateDeactivateSupplierRequest,
    context: AuthenticatedContext = Depends(require_permission(SUPPLIERS_ACTIVATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = SupplierService(session)
    supplier = await service.activate_supplier(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        supplier_id=supplier_id,
        expected_row_version=payload.expected_row_version,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_detail(supplier).model_dump(), "meta": _meta()}


@router.post("/{supplier_id}/deactivate")
async def deactivate_supplier(
    request: Request,
    supplier_id: uuid.UUID,
    payload: ActivateDeactivateSupplierRequest,
    context: AuthenticatedContext = Depends(require_permission(SUPPLIERS_DEACTIVATE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    service = SupplierService(session)
    supplier = await service.deactivate_supplier(
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        supplier_id=supplier_id,
        expected_row_version=payload.expected_row_version,
        ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_detail(supplier).model_dump(), "meta": _meta()}
