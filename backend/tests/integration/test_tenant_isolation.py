"""Phase 1A: Organization A must never reach Organization B's records.

Two layers are tested separately because they are independent defences:

1. APPLICATION layer (what protects production today): two organizations, each
   with its own HTTP client/cookie jar, probe each other across several
   resource types and with spoofed tenant identifiers.
2. DATABASE layer (Row-Level Security): proves the `tenant_isolation_*` policies
   are *correct* by enforcing them inside a transaction that is rolled back.
   It deliberately does NOT assert that RLS is enforced for the application
   role - it is not (tables are owned by the app role and RLS is not FORCEd);
   see database/documentation/rls-status.md.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.main import app
from tests.integration.test_customers import _signup_and_login_owner, _valid_customer_payload
from tests.integration.test_suppliers import _valid_supplier_payload

CUSTOMERS = "/api/v1/customers"
SUPPLIERS = "/api/v1/suppliers"
USERS = "/api/v1/users"


@pytest.fixture(autouse=True)
def _reset_state():
    from app.core.login_lockout import reset_all
    from app.core.rate_limit import reset_rate_limits

    reset_rate_limits()
    reset_all()
    yield


@pytest.fixture
async def two_orgs():
    """Two signed-in organizations with independent cookie jars."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as a, AsyncClient(
        transport=transport, base_url="http://test"
    ) as b:
        org_a = await _signup_and_login_owner(a)
        org_b = await _signup_and_login_owner(b)
        yield a, b, org_a, org_b


async def test_list_never_contains_other_organizations_records(two_orgs):
    a, b, _, _ = two_orgs
    cust = (await a.post(CUSTOMERS, json=_valid_customer_payload(name="ORG-A-ONLY"))).json()["data"]["id"]
    sup = (await a.post(SUPPLIERS, json=_valid_supplier_payload(name="ORG-A-SUPPLIER"))).json()["data"]["id"]

    for endpoint, record_id in ((CUSTOMERS, cust), (SUPPLIERS, sup)):
        listing = await b.get(endpoint, params={"page_size": 100})
        assert listing.status_code == 200
        assert record_id not in {row["id"] for row in listing.json()["data"]}
        assert "ORG-A" not in listing.text


async def test_direct_access_by_id_is_indistinguishable_from_not_found(two_orgs):
    a, b, _, _ = two_orgs
    cust = (await a.post(CUSTOMERS, json=_valid_customer_payload())).json()["data"]["id"]
    missing = await b.get(f"{CUSTOMERS}/{uuid.uuid4()}")
    cross = await b.get(f"{CUSTOMERS}/{cust}")
    assert cross.status_code == missing.status_code == 404
    assert cross.json()["error"]["code"] == missing.json()["error"]["code"]


async def test_cross_tenant_write_and_state_change_are_rejected(two_orgs):
    a, b, _, _ = two_orgs
    created = (await a.post(CUSTOMERS, json=_valid_customer_payload(name="Untouched"))).json()["data"]
    cid = created["id"]

    patch = await b.patch(f"{CUSTOMERS}/{cid}", json={"name": "Hijacked", "expected_row_version": created["row_version"]})
    assert patch.status_code == 404
    deact = await b.post(f"{CUSTOMERS}/{cid}/deactivate", json={"expected_row_version": created["row_version"]})
    assert deact.status_code == 404

    still = (await a.get(f"{CUSTOMERS}/{cid}")).json()["data"]
    assert still["name"] == "Untouched" and still["status"] == "ACTIVE"


async def test_client_supplied_tenant_identifiers_are_ignored(two_orgs):
    a, b, org_a, org_b = two_orgs
    tenant_a, tenant_b = org_a["tenant_id"], org_b["tenant_id"]

    # body field, query parameter and headers all try to act as the other tenant
    created = await b.post(
        CUSTOMERS,
        params={"tenant_id": tenant_a},
        json=_valid_customer_payload(tenant_id=tenant_a, name="Spoof attempt"),
        headers={"X-Tenant-Id": tenant_a, "X-User-Id": str(uuid.uuid4())},
    )
    assert created.status_code in (201, 422)
    if created.status_code == 201:
        assert created.json()["data"].get("tenant_id") in (None, tenant_b)

    in_a = await a.get(CUSTOMERS, params={"page_size": 100, "tenant_id": tenant_b}, headers={"X-Tenant-Id": tenant_b})
    assert "Spoof attempt" not in in_a.text


async def test_user_directory_is_tenant_scoped(two_orgs):
    a, b, org_a, _ = two_orgs
    users_b = await b.get(USERS)
    assert users_b.status_code == 200
    assert org_a["owner_user_id"] not in {u["id"] for u in users_b.json()["data"]}


async def test_unauthenticated_and_forged_requests_get_no_data():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as anon:
        assert (await anon.get(CUSTOMERS)).status_code == 401
        forged = await anon.get(CUSTOMERS, headers={"Authorization": "Bearer not.a.jwt", "X-Tenant-Id": str(uuid.uuid4())})
        assert forged.status_code == 401


# --- database layer ----------------------------------------------------------


async def test_rls_policy_isolates_tenants_when_enforced():
    """The tenant_isolation_customer policy is correct once RLS is enforced.

    FORCE ROW LEVEL SECURITY is applied INSIDE a transaction that is always
    rolled back, so nothing persists and the production posture is unchanged.
    """
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(text("SELECT DISTINCT tenant_id FROM customer WHERE tenant_id IS NOT NULL LIMIT 2"))
        ).scalars().all()
        if len(rows) < 2:
            pytest.skip("needs customers in at least two tenants")
        tenant_a, tenant_b = rows

        try:
            await session.execute(text('ALTER TABLE "customer" FORCE ROW LEVEL SECURITY'))
            await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a)})
            visible = (await session.execute(text("SELECT DISTINCT tenant_id FROM customer"))).scalars().all()
            assert visible == [tenant_a]

            await session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_b)})
            visible = (await session.execute(text("SELECT DISTINCT tenant_id FROM customer"))).scalars().all()
            assert visible == [tenant_b]

            await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
            assert (await session.execute(text("SELECT count(*) FROM customer"))).scalar_one() == 0
        finally:
            await session.rollback()
