"""Company Profile endpoints — `GET/PATCH /tenant`.

Reuses the existing `configuration.view`/`configuration.manage` permission
codes rather than inventing new ones (`tenant.*`): a tenant's own company
profile is conceptually the same "organization-wide settings" area as the
Configuration Center (invoice template config), and every tenant already
has Owner/Manager seeded with both codes — no new migration needed to
backfill a brand-new permission onto existing tenants' roles.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.exceptions import AuthorizationError
from app.core.permissions import CONFIGURATION_MANAGE, CONFIGURATION_VIEW
from app.db.session import get_db_session
from app.models.tenant import Tenant
from app.schemas.tenant import UpdateTenantProfileRequest
from app.services.tenant.tenant_profile_service import TenantProfileService

router = APIRouter(prefix="/tenant", tags=["tenant"])


def _require_tenant(context: AuthenticatedContext):
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


def _to_response(tenant: Tenant) -> dict:
    return {
        "id": str(tenant.id),
        "tenant_code": tenant.tenant_code,
        "business_name": tenant.business_name,
        "gstin": tenant.gstin,
        "state_code": tenant.state_code,
        "address_line1": tenant.address_line1,
        "city": tenant.city,
        "pin_code": tenant.pin_code,
        "pan": tenant.pan,
        "business_type": tenant.business_type,
        "phone": tenant.phone,
        "email": tenant.email,
        "website": tenant.website,
        "bank_name": tenant.bank_name,
        "bank_account_number": tenant.bank_account_number,
        "bank_account_holder_name": tenant.bank_account_holder_name,
        "bank_ifsc": tenant.bank_ifsc,
        "bank_branch_name": tenant.bank_branch_name,
        "bank_account_type": tenant.bank_account_type,
        "bank_upi_id": tenant.bank_upi_id,
        "financial_year_start_month": tenant.financial_year_start_month,
        "status": tenant.status,
        "row_version": tenant.row_version,
    }


def _meta() -> dict:
    return {"correlation_id": get_correlation_id()}


@router.get("")
async def get_tenant_profile(
    context: AuthenticatedContext = Depends(require_permission(CONFIGURATION_VIEW)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    tenant = await TenantProfileService(session).get(tenant_id=tenant_id)
    return {"data": _to_response(tenant), "meta": _meta()}


@router.patch("")
async def update_tenant_profile(
    request: Request,
    payload: UpdateTenantProfileRequest,
    context: AuthenticatedContext = Depends(require_permission(CONFIGURATION_MANAGE)),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"
    tenant = await TenantProfileService(session).update(
        tenant_id=tenant_id, actor_user_id=context.user_id, payload=payload, ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_response(tenant), "meta": _meta()}
