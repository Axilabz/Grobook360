"""TEST-REG-008 (duplicate registration): unit-tested directly against
SignUpService rather than through the HTTP layer + env-var settings
monkeypatching, since flipping the process-wide cached Settings singleton
mid-suite is fragile and unnecessary — the scope parameter is passed
explicitly to the service method under test.
"""

import uuid

import pytest

from app.core.error_codes import REG_DUPLICATE_REGISTRATION
from app.core.exceptions import ConflictError
from app.core.security import hash_password
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.signup import OrganizationDetails, OwnerAccountDetails, SignUpRequest
from app.services.gst.provider import NullGSTProvider
from app.services.signup.signup_service import SignUpService


def _phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _signup_request(phone: str) -> SignUpRequest:
    return SignUpRequest(
        organization=OrganizationDetails(
            business_name="Test Co",
            address_line1="1 Main St",
            city="Chennai",
            state_code="33",
            pin_code="600001",
            gstin=None,
        ),
        owner=OwnerAccountDetails(
            name="Test Owner", phone=phone, email="owner@example.com", password="SecurePass123", confirm_password="SecurePass123"
        ),
    )


async def test_platform_scope_rejects_duplicate_phone(db_session):
    phone = _phone()

    # Seed an existing user with this phone under a throwaway tenant.
    existing_tenant = Tenant(business_name="Existing Tenant")
    db_session.add(existing_tenant)
    await db_session.flush()
    db_session.add(
        User(tenant_id=existing_tenant.id, email="existing@example.com", phone=phone, password_hash=hash_password("x"), status="ACTIVE")
    )
    await db_session.flush()

    service = SignUpService(db_session, NullGSTProvider())
    with pytest.raises(ConflictError) as exc_info:
        await service.create_tenant_and_owner(_signup_request(phone), phone_uniqueness_scope="platform")

    assert exc_info.value.error_code == REG_DUPLICATE_REGISTRATION


async def test_tenant_scope_does_not_check_uniqueness_at_signup(db_session):
    # With tenant-scoped uniqueness, there is no existing tenant to conflict
    # with yet at sign-up time — the same phone must not be rejected.
    phone = _phone()
    existing_tenant = Tenant(business_name="Existing Tenant 2")
    db_session.add(existing_tenant)
    await db_session.flush()
    db_session.add(
        User(tenant_id=existing_tenant.id, email="existing2@example.com", phone=phone, password_hash=hash_password("x"), status="ACTIVE")
    )
    await db_session.flush()

    service = SignUpService(db_session, NullGSTProvider())
    tenant, owner = await service.create_tenant_and_owner(_signup_request(phone), phone_uniqueness_scope="tenant")

    assert tenant.id is not None
    assert owner.phone == phone
