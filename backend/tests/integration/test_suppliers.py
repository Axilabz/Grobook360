"""PROMPT-008 test catalogue for /api/v1/suppliers.

Follows test_customers.py's structure and helper style exactly. Covers the
security-critical subset of PROMPT-008 S54/S55 (tenant isolation, RBAC,
GSTIN validation/duplicate, concurrency) — SUPPLIER-API ids noted alongside
each test for traceability.
"""

import uuid

import pytest

SUPPLIERS_ENDPOINT = "/api/v1/suppliers"
SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"
USERS_ENDPOINT = "/api/v1/users"
RESET_ENDPOINT = "/api/v1/auth/reset-password"

OWNER_PASSWORD = "SecurePass123"
SALESPERSON_PASSWORD = "AnotherSecurePass456"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _unique_email() -> str:
    return f"supp-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    from app.core.rate_limit import reset_rate_limits
    from app.core.login_lockout import reset_all

    reset_rate_limits()
    reset_all()
    yield


async def _signup_and_login_owner(client) -> dict:
    phone = _unique_phone()
    payload = {
        "organization": {
            "business_name": "Supplier Test Co",
            "address_line1": "1 Main St",
            "city": "Chennai",
            "state_code": "33",
            "pin_code": "600001",
            "gstin": None,
        },
        "owner": {"phone": phone, "email": _unique_email(), "password": OWNER_PASSWORD, "confirm_password": OWNER_PASSWORD},
    }
    signup_response = await client.post(SIGNUP_ENDPOINT, json=payload, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert signup_response.status_code == 201

    login_response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": OWNER_PASSWORD})
    assert login_response.status_code == 200
    return signup_response.json()["data"]


async def _create_salesperson_and_login(client) -> None:
    from app.services.password_recovery.provider import ConsolePasswordRecoveryProvider

    phone = _unique_phone()
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "SP", "phone": phone, "email": _unique_email(), "role": "SALESPERSON"}
    )
    assert create_response.status_code == 201
    reset_token = ConsolePasswordRecoveryProvider.outbox[-1].reset_link.split("token=")[1]
    reset_response = await client.post(
        RESET_ENDPOINT, json={"token": reset_token, "new_password": SALESPERSON_PASSWORD, "confirm_password": SALESPERSON_PASSWORD}
    )
    assert reset_response.status_code == 200
    login = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": SALESPERSON_PASSWORD})
    assert login.status_code == 200


def _valid_supplier_payload(**overrides) -> dict:
    payload = {
        "name": "Sunrise Distributors",
        "contact_person": "Vijay Rao",
        "phone": _unique_phone(),
        "email": _unique_email(),
    }
    payload.update(overrides)
    return payload


# --- SUPPLIER-API-010/011/012/013: create ---


async def test_supplier_api_010_valid_creation(client):
    await _signup_and_login_owner(client)
    response = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["name"] == "Sunrise Distributors"
    assert data["status"] == "ACTIVE"
    assert data["supplier_code"].startswith("SUPP-")
    assert data["balance"] in ("0.00", "0")
    # FR-SUPP-02: no credit_limit/region/gps_location fields exist at all.
    assert "credit_limit" not in data
    assert "region" not in data
    assert "gps_location" not in data


async def test_supplier_api_011_missing_required_field(client):
    await _signup_and_login_owner(client)
    response = await client.post(SUPPLIERS_ENDPOINT, json={"name": "No Phone Co", "contact_person": "X"})
    assert response.status_code == 422


async def test_supplier_api_012_invalid_gstin(client):
    await _signup_and_login_owner(client)
    response = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload(gstin="NOTVALIDGSTIN1"))
    assert response.status_code == 422


async def test_supplier_api_gstin_state_derivation(client):
    await _signup_and_login_owner(client)
    response = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload(gstin="33ABCDE1234F1Z5"))
    assert response.status_code == 201
    assert response.json()["data"]["state_code"] == "33"


async def test_supplier_api_gstin_state_mismatch_rejected(client):
    await _signup_and_login_owner(client)
    response = await client.post(
        SUPPLIERS_ENDPOINT, json=_valid_supplier_payload(gstin="33ABCDE1234F1Z5", state_code="27")
    )
    assert response.status_code == 422


async def test_supplier_api_013_duplicate_gstin(client):
    await _signup_and_login_owner(client)
    gstin = "33ABCDE1234F1Z5"
    first = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload(gstin=gstin))
    assert first.status_code == 201
    second = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload(gstin=gstin))
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "SUPP-002"


async def test_supplier_api_015_invalid_phone(client):
    await _signup_and_login_owner(client)
    response = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload(phone="12345"))
    assert response.status_code == 422


async def test_supplier_api_016_invalid_email(client):
    await _signup_and_login_owner(client)
    response = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload(email="not-an-email"))
    assert response.status_code == 422


async def test_supplier_api_018_unauthorized_creation_no_session(client):
    response = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    assert response.status_code == 401


async def test_supplier_api_019_tenant_id_not_client_controlled(client):
    await _signup_and_login_owner(client)
    response = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload(tenant_id=str(uuid.uuid4())))
    assert response.status_code == 201  # extraneous field silently ignored


# --- SUPPLIER-API-001/002/003: list / tenant isolation ---


async def test_supplier_api_001_003_list_and_tenant_isolation(client):
    await _signup_and_login_owner(client)
    created = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    tenant_a_id = created.json()["data"]["id"]

    list_a = await client.get(SUPPLIERS_ENDPOINT)
    assert list_a.status_code == 200
    assert tenant_a_id in {item["id"] for item in list_a.json()["data"]}

    await _signup_and_login_owner(client)  # second, independent tenant
    list_b = await client.get(SUPPLIERS_ENDPOINT)
    tenant_b_ids = {item["id"] for item in list_b.json()["data"]}
    assert tenant_a_id not in tenant_b_ids


async def test_supplier_api_002_unauthorized_list(client):
    response = await client.get(SUPPLIERS_ENDPOINT)
    assert response.status_code == 401


async def test_supplier_api_004_search(client):
    await _signup_and_login_owner(client)
    await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload(name="Findme Distributors"))
    response = await client.get(SUPPLIERS_ENDPOINT, params={"search": "Findme"})
    names = [item["name"] for item in response.json()["data"]]
    assert "Findme Distributors" in names


async def test_supplier_api_005_filtering_gst_registered(client):
    await _signup_and_login_owner(client)
    await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload(gstin="33ABCDE1234F1Z5"))
    await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())

    response = await client.get(SUPPLIERS_ENDPOINT, params={"gst_registered": True})
    assert all(item["gstin"] is not None for item in response.json()["data"])


async def test_supplier_api_006_pagination(client):
    await _signup_and_login_owner(client)
    for _ in range(3):
        await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    response = await client.get(SUPPLIERS_ENDPOINT, params={"page": 1, "page_size": 2})
    body = response.json()
    assert len(body["data"]) == 2
    assert body["pagination"]["total_items"] >= 3


# --- SUPPLIER-API-007/008/009: detail ---


async def test_supplier_api_007_authorized_detail(client):
    await _signup_and_login_owner(client)
    created = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    supplier_id = created.json()["data"]["id"]
    response = await client.get(f"{SUPPLIERS_ENDPOINT}/{supplier_id}")
    assert response.status_code == 200


async def test_supplier_api_008_not_found(client):
    await _signup_and_login_owner(client)
    response = await client.get(f"{SUPPLIERS_ENDPOINT}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SUPP-001"


async def test_supplier_api_009_cross_tenant_detail_not_found(client):
    await _signup_and_login_owner(client)
    created = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    supplier_id = created.json()["data"]["id"]

    await _signup_and_login_owner(client)  # second tenant
    response = await client.get(f"{SUPPLIERS_ENDPOINT}/{supplier_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SUPP-001"  # same as not-found, not distinguishable


# --- SUPPLIER-API-020/021/022/023/024: update ---


async def test_supplier_api_020_valid_update(client):
    await _signup_and_login_owner(client)
    created = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    data = created.json()["data"]
    response = await client.patch(
        f"{SUPPLIERS_ENDPOINT}/{data['id']}",
        json={"name": "Sunrise Wholesale", "expected_row_version": data["row_version"]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Sunrise Wholesale"


async def test_supplier_api_021_invalid_update(client):
    await _signup_and_login_owner(client)
    created = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    data = created.json()["data"]
    response = await client.patch(
        f"{SUPPLIERS_ENDPOINT}/{data['id']}",
        json={"gstin": "BADGSTIN", "expected_row_version": data["row_version"]},
    )
    assert response.status_code == 422


async def test_supplier_api_022_update_by_salesperson_denied(client):
    # RBAC Alignment Phase: Supplier Management is now "No Access" for
    # Salesperson (suppliers.update removed along with .view/.create) —
    # this test used to assert the FR-SUPP-05-derived positive case; the
    # new target matrix deliberately tightens it to a 403.
    await _signup_and_login_owner(client)
    created = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    data = created.json()["data"]

    await _create_salesperson_and_login(client)
    response = await client.patch(
        f"{SUPPLIERS_ENDPOINT}/{data['id']}",
        json={"name": "Edited By Salesperson", "expected_row_version": data["row_version"]},
    )
    assert response.status_code == 403


async def test_supplier_api_023_cross_tenant_update_not_found(client):
    await _signup_and_login_owner(client)
    created = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    data = created.json()["data"]

    await _signup_and_login_owner(client)
    response = await client.patch(
        f"{SUPPLIERS_ENDPOINT}/{data['id']}",
        json={"name": "Hijacked", "expected_row_version": data["row_version"]},
    )
    assert response.status_code == 404


async def test_supplier_api_024_stale_row_version(client):
    await _signup_and_login_owner(client)
    created = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    data = created.json()["data"]

    response = await client.patch(
        f"{SUPPLIERS_ENDPOINT}/{data['id']}",
        json={"name": "First Edit", "expected_row_version": data["row_version"]},
    )
    assert response.status_code == 200

    stale_response = await client.patch(
        f"{SUPPLIERS_ENDPOINT}/{data['id']}",
        json={"name": "Stale Edit", "expected_row_version": data["row_version"]},
    )
    assert stale_response.status_code == 412


# --- SUPPLIER-API-025/026/027/028: status ---


async def test_supplier_api_025_026_activate_deactivate(client):
    await _signup_and_login_owner(client)
    created = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    data = created.json()["data"]

    deactivate = await client.post(
        f"{SUPPLIERS_ENDPOINT}/{data['id']}/deactivate", json={"expected_row_version": data["row_version"]}
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["data"]["status"] == "INACTIVE"

    activate = await client.post(
        f"{SUPPLIERS_ENDPOINT}/{data['id']}/activate",
        json={"expected_row_version": deactivate.json()["data"]["row_version"]},
    )
    assert activate.status_code == 200
    assert activate.json()["data"]["status"] == "ACTIVE"


async def test_supplier_api_027_unauthorized_status_change_by_salesperson(client):
    # FR-SUPP-05: only Owner/Manager may deactivate — Salesperson rejected.
    await _signup_and_login_owner(client)
    created = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    data = created.json()["data"]

    await _create_salesperson_and_login(client)
    response = await client.post(
        f"{SUPPLIERS_ENDPOINT}/{data['id']}/deactivate", json={"expected_row_version": data["row_version"]}
    )
    assert response.status_code == 403


async def test_supplier_api_028_deactivation_preserves_record(client):
    await _signup_and_login_owner(client)
    created = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    data = created.json()["data"]
    await client.post(f"{SUPPLIERS_ENDPOINT}/{data['id']}/deactivate", json={"expected_row_version": data["row_version"]})

    response = await client.get(f"{SUPPLIERS_ENDPOINT}/{data['id']}")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "INACTIVE"


async def test_supplier_manager_can_view_and_create(client):
    await _signup_and_login_owner(client)
    from app.services.password_recovery.provider import ConsolePasswordRecoveryProvider

    phone = _unique_phone()
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "Mgr", "phone": phone, "email": _unique_email(), "role": "MANAGER"}
    )
    assert create_response.status_code == 201
    reset_token = ConsolePasswordRecoveryProvider.outbox[-1].reset_link.split("token=")[1]
    await client.post(RESET_ENDPOINT, json={"token": reset_token, "new_password": SALESPERSON_PASSWORD, "confirm_password": SALESPERSON_PASSWORD})
    await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": SALESPERSON_PASSWORD})

    response = await client.post(SUPPLIERS_ENDPOINT, json=_valid_supplier_payload())
    assert response.status_code == 201
    list_response = await client.get(SUPPLIERS_ENDPOINT)
    assert list_response.status_code == 200
