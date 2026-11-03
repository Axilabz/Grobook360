"""Tenant + Owner sign-up (PROMPT-002 S15).

One atomic transaction creates: Tenant, an "OWNER" Role scoped to that tenant,
the initial User, and the UserRole assignment, plus audit records. Any failure
rolls back the whole thing — no partial Tenant-without-Owner or
Owner-without-Tenant state is ever committed (BR-005/BR-006).

role_permission rows ARE now populated (PROMPT-006), using the default
permission set for OWNER — a formalization of the users.* surface PROMPT-005
already enforced via role checks, not a new business decision. See
PROMPT-006-NOTES.md.
"""

import uuid

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import REG_DUPLICATE_REGISTRATION, REG_GST_VERIFICATION_FAILURE
from app.core.exceptions import ConflictError
from app.core.security import hash_password
from app.db.base import utcnow
from app.db.tenant_context import set_tenant_context
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_role import UserRole
from app.schemas.signup import SignUpRequest
from app.services.audit.audit_service import AuditService
from app.services.gst.provider import GSTVerificationProvider
from app.services.rbac.permission_service import seed_role_permissions


_MAX_CODE_ATTEMPTS = 5


class SignUpService:
    def __init__(self, session: AsyncSession, gst_provider: GSTVerificationProvider) -> None:
        self._session = session
        self._gst_provider = gst_provider

    async def _next_tenant_code(self, attempt: int) -> str:
        # Platform-wide (not tenant-scoped, unlike customer_code/supplier_code
        # — a tenant's own code is itself the scope). Mirrors
        # CustomerService._next_customer_code's "count + attempt, retry on
        # IntegrityError" pattern — see the retry loop in
        # create_tenant_and_owner below.
        # Row-level security hides other tenants, so the platform-wide count
        # comes from a narrow SECURITY DEFINER function (aggregate only).
        count = (await self._session.execute(text("SELECT public.signup_tenant_count()"))).scalar_one()
        return f"TEN-{count + 1 + attempt:04d}"

    async def _check_phone_uniqueness_platform_wide(self, phone: str) -> None:
        in_use = (
            await self._session.execute(text("SELECT public.signup_phone_in_use(:p)"), {"p": phone})
        ).scalar_one()
        if in_use:
            raise ConflictError(
                "This phone number is already registered", code=REG_DUPLICATE_REGISTRATION
            )

    async def _verify_gstin_if_supplied(self, gstin: str | None) -> None:
        if gstin is None:
            return
        lookup = await self._gst_provider.lookup(gstin)
        if lookup.available and not lookup.verified:
            raise ConflictError(
                lookup.error_message or "GST verification failed",
                code=REG_GST_VERIFICATION_FAILURE,
            )
        # If the provider is unavailable (not configured — the current state,
        # since no production provider is selected per FRD OQ-003), sign-up
        # proceeds with the format-validated GSTIN only. This is a documented
        # assumption, not a silent business decision — see PROMPT-002-NOTES.md.

    async def create_tenant_and_owner(self, payload: SignUpRequest, *, phone_uniqueness_scope: str) -> tuple[Tenant, User]:
        await self._verify_gstin_if_supplied(payload.organization.gstin)

        if phone_uniqueness_scope == "platform":
            await self._check_phone_uniqueness_platform_wide(payload.owner.phone)
        # "tenant" scope: no existing tenant to conflict with yet at sign-up time;
        # nothing to check here by construction (see PROMPT-002-NOTES.md).

        # The tenant does not exist yet, so its id is chosen here and the RLS
        # context is set to it BEFORE the first insert: every row created below
        # must satisfy the policy for exactly this tenant (WITH CHECK).
        new_tenant_id = uuid.uuid4()
        await set_tenant_context(self._session, new_tenant_id)

        last_error: Exception | None = None
        tenant: Tenant | None = None
        for attempt in range(_MAX_CODE_ATTEMPTS):
            code = await self._next_tenant_code(attempt)
            tenant = Tenant(
                id=new_tenant_id,
                tenant_code=code,
                business_name=payload.organization.business_name,
                business_type=payload.organization.business_type,
                gstin=payload.organization.gstin,
                state_code=payload.organization.state_code,
                address_line1=payload.organization.address_line1,
                city=payload.organization.city,
                pin_code=payload.organization.pin_code,
            )
            try:
                async with self._session.begin_nested():
                    self._session.add(tenant)
                    await self._session.flush()  # assign tenant.id
                break
            except IntegrityError as exc:
                last_error = exc
                continue
        else:
            raise ConflictError("Could not allocate a unique tenant code. Please retry.") from last_error

        owner_role = Role(tenant_id=tenant.id, name="OWNER", description="Tenant owner — full administrative access")
        self._session.add(owner_role)
        await self._session.flush()
        await seed_role_permissions(self._session, tenant_id=tenant.id, role_id=owner_role.id, role_name="OWNER")

        owner_user = User(
            tenant_id=tenant.id,
            name=payload.owner.name,
            email=payload.owner.email,
            phone=payload.owner.phone,
            password_hash=hash_password(payload.owner.password),
            status="ACTIVE",
        )
        self._session.add(owner_user)
        await self._session.flush()

        user_role = UserRole(tenant_id=tenant.id, user_id=owner_user.id, role_id=owner_role.id)
        self._session.add(user_role)
        await self._session.flush()

        audit = AuditService(self._session)
        await audit.record(
            tenant_id=tenant.id,
            actor_user_id=owner_user.id,
            action="CREATE",
            entity_type="tenant",
            entity_id=tenant.id,
            after={"tenant_code": tenant.tenant_code, "business_name": tenant.business_name, "status": tenant.status},
        )
        await audit.record(
            tenant_id=tenant.id,
            actor_user_id=owner_user.id,
            action="CREATE",
            entity_type="user",
            entity_id=owner_user.id,
            after={"name": owner_user.name, "phone": owner_user.phone, "role": "OWNER"},
        )

        return tenant, owner_user
