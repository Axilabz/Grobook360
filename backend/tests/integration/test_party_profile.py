"""Party 360 Profile test catalogue — /api/v1/parties/{party_type}/{party_id}.

Follows test_customers.py's structure and helper style. Covers the
security-critical subset: correct data for a customer with no
transactions yet (empty states, not crashes), RBAC (a Salesperson has
customers.view but not suppliers.view — should see the customer profile
and be rejected on the supplier profile), tenant isolation, invalid
party_type rejection, and not-found for a real party_id in another
tenant.
"""

import uuid

import pytest

SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"
USERS_ENDPOINT = "/api/v1/users"
RESET_ENDPOINT = "/api/v1/auth/reset-password"
CUSTOMERS_ENDPOINT = "/api/v1/customers"
SUPPLIERS_ENDPOINT = "/api/v1/suppliers"

OWNER_PASSWORD = "SecurePass123"
OTHER_PASSWORD = "AnotherSecurePass456"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _unique_email() -> str:
    return f"party-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    from app.core.rate_limit import reset_rate_limits
    from app.core.login_lockout import reset_all

    reset_rate_limits()
    reset_all()
    yield


async def _signup_and_login_owner(client, business_name: str = "Party Test Co") -> dict:
    phone = _unique_phone()
    payload = {
        "organization": {
            "business_name": business_name, "address_line1": "1 Main St", "city": "Chennai",
            "state_code": "33", "pin_code": "600001", "gstin": None,
        },
        "owner": {"phone": phone, "email": _unique_email(), "password": OWNER_PASSWORD, "confirm_password": OWNER_PASSWORD},
    }
    signup_response = await client.post(SIGNUP_ENDPOINT, json=payload, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert signup_response.status_code == 201
    login_response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": OWNER_PASSWORD})
    assert login_response.status_code == 200
    return signup_response.json()["data"]


async def _create_user_and_login(client, *, role: str) -> None:
    from app.services.password_recovery.provider import ConsolePasswordRecoveryProvider

    phone = _unique_phone()
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "U", "phone": phone, "email": _unique_email(), "role": role}
    )
    assert create_response.status_code == 201
    reset_token = ConsolePasswordRecoveryProvider.outbox[-1].reset_link.split("token=")[1]
    reset_response = await client.post(
        RESET_ENDPOINT, json={"token": reset_token, "new_password": OTHER_PASSWORD, "confirm_password": OTHER_PASSWORD}
    )
    assert reset_response.status_code == 200
    login = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": OTHER_PASSWORD})
    assert login.status_code == 200


async def _create_customer(client, **overrides) -> dict:
    payload = {"name": "ABC Traders", "owner_name": "Ravi", "phone": _unique_phone()}
    payload.update(overrides)
    response = await client.post(CUSTOMERS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


async def _create_supplier(client, **overrides) -> dict:
    payload = {"name": "XYZ Distributors", "contact_person": "Kumar", "phone": _unique_phone()}
    payload.update(overrides)
    response = await client.post(SUPPLIERS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


# --- Happy path: empty-state profile (no transactions yet) ---


async def test_customer_profile_empty_state(client):
    await _signup_and_login_owner(client)
    customer = await _create_customer(client, name="Fresh Customer")

    response = await client.get(f"/api/v1/parties/customer/{customer['id']}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["header"]["party_type"] == "customer"
    assert data["header"]["name"] == "Fresh Customer"
    assert data["kpis"]["total_sales"] == "0"
    assert data["kpis"]["invoice_count"] == 0
    assert data["kpis"]["last_transaction_date"] is None
    assert data["top_products"] == []
    assert data["recent_transactions"] == []
    assert data["payment_history"] == []


async def test_supplier_profile_empty_state(client):
    await _signup_and_login_owner(client)
    supplier = await _create_supplier(client, name="Fresh Supplier")

    response = await client.get(f"/api/v1/parties/supplier/{supplier['id']}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["header"]["party_type"] == "supplier"
    assert data["header"]["name"] == "Fresh Supplier"
    assert data["kpis"]["total_purchases"] == "0"
    assert data["kpis"]["invoice_count"] == 0


# --- Validation ---


async def test_invalid_party_type_rejected(client):
    await _signup_and_login_owner(client)
    customer = await _create_customer(client)
    response = await client.get(f"/api/v1/parties/vendor/{customer['id']}")
    assert response.status_code == 422


async def test_customer_id_not_found_returns_404(client):
    await _signup_and_login_owner(client)
    response = await client.get(f"/api/v1/parties/customer/{uuid.uuid4()}")
    assert response.status_code == 404


# --- RBAC ---


async def test_unauthenticated_request_rejected(client):
    response = await client.get(f"/api/v1/parties/customer/{uuid.uuid4()}")
    assert response.status_code == 401


async def test_salesperson_can_view_customer_profile(client):
    await _signup_and_login_owner(client)
    customer = await _create_customer(client)
    await _create_user_and_login(client, role="SALESPERSON")

    response = await client.get(f"/api/v1/parties/customer/{customer['id']}")
    assert response.status_code == 200


async def test_salesperson_cannot_view_supplier_profile(client):
    """RBAC Alignment Phase: Supplier Management is now "No Access" for
    Salesperson (suppliers.view/create/update all removed) — a deliberate
    tightening from the prior FR-SUPP-05-derived "Limited" resolution this
    test used to assert. The Party 360 endpoint's per-party-type permission
    check must now deny Salesperson access to a supplier's profile too."""
    await _signup_and_login_owner(client)
    supplier = await _create_supplier(client)
    await _create_user_and_login(client, role="SALESPERSON")

    response = await client.get(f"/api/v1/parties/supplier/{supplier['id']}")
    assert response.status_code == 403


# --- Tenant isolation ---


async def test_tenant_isolation_on_party_profile(client):
    await _signup_and_login_owner(client, business_name="Tenant A Co")
    customer_a = await _create_customer(client, name="Tenant A Customer")

    await _signup_and_login_owner(client, business_name="Tenant B Co")
    response = await client.get(f"/api/v1/parties/customer/{customer_a['id']}")
    assert response.status_code == 404  # cross-tenant lookup reads as not-found, never a distinguishable error
