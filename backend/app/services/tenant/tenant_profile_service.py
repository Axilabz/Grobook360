"""Company Profile service — read/update the authenticated tenant's own row.

No lazy-provisioning needed (unlike InvoiceTemplateConfiguration or
IntegrationConfiguration): every tenant already has exactly one `tenant`
row, created at sign-up.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import check_row_version
from app.core.exceptions import NotFoundError
from app.models.tenant import Tenant
from app.schemas.tenant import UpdateTenantProfileRequest
from app.services.audit.audit_service import AuditService

_PROFILE_FIELDS = (
    "business_name", "gstin", "state_code", "address_line1", "city", "pin_code",
    "pan", "business_type", "phone", "email", "website",
    "bank_name", "bank_account_number", "bank_account_holder_name", "bank_ifsc", "bank_branch_name",
    "bank_account_type", "bank_upi_id",
)


def _snapshot(tenant: Tenant) -> dict:
    return {field: getattr(tenant, field) for field in _PROFILE_FIELDS}


class TenantProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, *, tenant_id: uuid.UUID) -> Tenant:
        result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("Tenant not found")
        return tenant

    async def update(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, payload: UpdateTenantProfileRequest, ip_address: str | None,
    ) -> Tenant:
        tenant = await self.get(tenant_id=tenant_id)
        check_row_version(tenant, payload.expected_row_version)

        before = _snapshot(tenant)

        tenant.business_name = payload.business_name
        tenant.gstin = payload.gstin
        tenant.state_code = payload.state_code
        tenant.address_line1 = payload.address_line1
        tenant.city = payload.city
        tenant.pin_code = payload.pin_code
        tenant.pan = payload.pan
        tenant.business_type = payload.business_type
        tenant.phone = payload.phone
        tenant.email = payload.email
        tenant.website = payload.website
        tenant.bank_name = payload.bank_name
        tenant.bank_account_number = payload.bank_account_number
        tenant.bank_account_holder_name = payload.bank_account_holder_name
        tenant.bank_ifsc = payload.bank_ifsc
        tenant.bank_branch_name = payload.bank_branch_name
        tenant.bank_account_type = payload.bank_account_type
        tenant.bank_upi_id = payload.bank_upi_id
        tenant.updated_by = actor_user_id
        tenant.row_version += 1

        after = _snapshot(tenant)
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="TENANT_PROFILE_UPDATED",
            entity_type="tenant", entity_id=tenant.id, before=before, after=after, ip_address=ip_address,
        )
        return tenant
