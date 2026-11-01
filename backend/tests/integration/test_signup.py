"""PROMPT-002 S34 test catalogue for POST /api/v1/auth/sign-up.

Phone numbers are generated fresh per test (not hardcoded) because these tests
run against a real, persistent PostgreSQL database with no rollback between
separate pytest invocations — hardcoded values would collide across runs.
"""

import uuid

from sqlalchemy import select

from app.models.tenant import Tenant
from app.models.user import User

ENDPOINT = "/api/v1/auth/sign-up"


def _unique_phone() -> str:
    # 10 numeric digits, effectively unique per test run.
    return "9" + str(uuid.uuid4().int)[:9]


def _valid_payload(**overrides) -> dict:
    base = {
        "organization": {
            "business_name": "ABC Distributors",
            "address_line1": "12 Market Road",
            "city": "Chennai",
            "state_code": "33",
            "pin_code": "600001",
            "gstin": None,
        },
        "owner": {
            "name": "Test Owner",
            "phone": _unique_phone(),
            "email": "owner@example.com",
            "password": "SecurePass123",
            "confirm_password": "SecurePass123",
        },
    }
    for key, value in overrides.items():
        section, field = key.split(".")
        base[section][field] = value
    return base


def _idem_key() -> str:
    return str(uuid.uuid4())


async def test_reg_001_valid_gst_registered_business(client):
    payload = _valid_payload(**{"organization.gstin": "33AAAAA0000A1Z5"})
    response = await client.post(ENDPOINT, json=payload, headers={"Idempotency-Key": _idem_key()})
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["status"] == "CREATED"
    uuid.UUID(body["tenant_id"])
    uuid.UUID(body["owner_user_id"])


async def test_reg_002_valid_non_gst_business(client):
    payload = _valid_payload()
    response = await client.post(ENDPOINT, json=payload, headers={"Idempotency-Key": _idem_key()})
    assert response.status_code == 201


async def test_reg_003_missing_organization_name(client):
    payload = _valid_payload()
    del payload["organization"]["business_name"]
    response = await client.post(ENDPOINT, json=payload, headers={"Idempotency-Key": _idem_key()})
    assert response.status_code == 422


async def test_reg_004_invalid_phone(client):
    payload = _valid_payload(**{"owner.phone": "12345"})
    response = await client.post(ENDPOINT, json=payload, headers={"Idempotency-Key": _idem_key()})
    assert response.status_code == 422


async def test_reg_005_invalid_email(client):
    payload = _valid_payload(**{"owner.email": "not-an-email"})
    response = await client.post(ENDPOINT, json=payload, headers={"Idempotency-Key": _idem_key()})
    assert response.status_code == 422


async def test_reg_006_weak_password(client):
    payload = _valid_payload(**{"owner.password": "abc", "owner.confirm_password": "abc"})
    response = await client.post(ENDPOINT, json=payload, headers={"Idempotency-Key": _idem_key()})
    assert response.status_code == 422


async def test_reg_007_password_mismatch(client):
    payload = _valid_payload(**{"owner.confirm_password": "Different123"})
    response = await client.post(ENDPOINT, json=payload, headers={"Idempotency-Key": _idem_key()})
    assert response.status_code == 422


async def test_reg_008_invalid_gstin(client):
    payload = _valid_payload(**{"organization.gstin": "NOT-A-GSTIN"})
    response = await client.post(ENDPOINT, json=payload, headers={"Idempotency-Key": _idem_key()})
    assert response.status_code == 422


async def test_reg_011_repeated_request_same_idempotency_key_returns_original_result(client):
    key = _idem_key()
    payload = _valid_payload()

    first = await client.post(ENDPOINT, json=payload, headers={"Idempotency-Key": key})
    second = await client.post(ENDPOINT, json=payload, headers={"Idempotency-Key": key})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["data"]["tenant_id"] == second.json()["data"]["tenant_id"]
    assert first.json()["data"]["owner_user_id"] == second.json()["data"]["owner_user_id"]


async def test_reg_012_same_idempotency_key_different_payload_conflicts(client):
    key = _idem_key()
    payload1 = _valid_payload()
    payload2 = _valid_payload()

    first = await client.post(ENDPOINT, json=payload1, headers={"Idempotency-Key": key})
    assert first.status_code == 201

    second = await client.post(ENDPOINT, json=payload2, headers={"Idempotency-Key": key})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "REG-009"


async def test_reg_015_cross_tenant_isolation_two_signups_get_distinct_tenants(client):
    payload1 = _valid_payload()
    payload2 = _valid_payload()

    r1 = await client.post(ENDPOINT, json=payload1, headers={"Idempotency-Key": _idem_key()})
    r2 = await client.post(ENDPOINT, json=payload2, headers={"Idempotency-Key": _idem_key()})

    assert r1.json()["data"]["tenant_id"] != r2.json()["data"]["tenant_id"]


async def test_reg_016_password_never_in_response(client):
    payload = _valid_payload()
    response = await client.post(ENDPOINT, json=payload, headers={"Idempotency-Key": _idem_key()})
    assert "password" not in response.text.lower()
    assert payload["owner"]["password"] not in response.text


async def test_reg_017_missing_idempotency_key_rejected(client):
    payload = _valid_payload()
    response = await client.post(ENDPOINT, json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REG-001"


async def test_reg_018_audit_event_created(client, db_session):
    from app.models.audit_log import AuditLog

    payload = _valid_payload()
    response = await client.post(ENDPOINT, json=payload, headers={"Idempotency-Key": _idem_key()})
    tenant_id = uuid.UUID(response.json()["data"]["tenant_id"])

    result = await db_session.execute(select(AuditLog).where(AuditLog.tenant_id == tenant_id))
    entries = result.scalars().all()
    actions = {(e.action, e.entity_type) for e in entries}
    assert ("CREATE", "tenant") in actions
    assert ("CREATE", "user") in actions


async def test_tenant_and_owner_persisted_correctly(client, db_session):
    payload = _valid_payload()
    response = await client.post(ENDPOINT, json=payload, headers={"Idempotency-Key": _idem_key()})
    data = response.json()["data"]

    tenant = (
        await db_session.execute(select(Tenant).where(Tenant.id == uuid.UUID(data["tenant_id"])))
    ).scalar_one()
    owner = (
        await db_session.execute(select(User).where(User.id == uuid.UUID(data["owner_user_id"])))
    ).scalar_one()

    assert tenant.business_name == "ABC Distributors"
    assert owner.tenant_id == tenant.id
    assert owner.password_hash != payload["owner"]["password"]
