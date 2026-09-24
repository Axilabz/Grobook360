"""PROMPT-012 test catalogue for /api/v1/sales/estimates.

Follows test_products.py/test_inventory.py's structure and helper style.
Covers the security-critical subset of §39 (create validation, GST
calculation, tenant isolation, permission, status transitions, expiry,
conversion atomicity/idempotency/concurrency, audit, row-version).
"""

import asyncio
import uuid
from datetime import date, timedelta

import pytest

ESTIMATES_ENDPOINT = "/api/v1/sales/estimates"
PRODUCTS_ENDPOINT = "/api/v1/products"
UNITS_ENDPOINT = "/api/v1/units"
CUSTOMERS_ENDPOINT = "/api/v1/customers"
SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"
USERS_ENDPOINT = "/api/v1/users"
RESET_ENDPOINT = "/api/v1/auth/reset-password"

OWNER_PASSWORD = "SecurePass123"
SALESPERSON_PASSWORD = "AnotherSecurePass456"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _unique_email() -> str:
    return f"est-{uuid.uuid4().hex[:12]}@example.com"


def _unique_sku() -> str:
    return f"SKU-{uuid.uuid4().hex[:10].upper()}"


def _idem() -> dict:
    return {"Idempotency-Key": str(uuid.uuid4())}


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    from app.core.rate_limit import reset_rate_limits
    from app.core.login_lockout import reset_all

    reset_rate_limits()
    reset_all()
    yield


async def _signup_and_login_owner(client, state_code: str = "33") -> dict:
    phone = _unique_phone()
    payload = {
        "organization": {
            "business_name": "Estimate Test Co",
            "address_line1": "1 Main St",
            "city": "Chennai",
            "state_code": state_code,
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


async def _create_unit(client, code: str = "PCS", name: str = "Pieces") -> dict:
    response = await client.post(UNITS_ENDPOINT, json={"code": code, "name": name})
    assert response.status_code == 201
    return response.json()["data"]


async def _create_product(client, base_uom_id: str, **overrides) -> dict:
    payload = {
        "sku": _unique_sku(), "name": "Test Product", "base_uom_id": base_uom_id,
        "gst_rate": "18", "cost_price": "50", "selling_price": "100", "mrp": "120",
    }
    payload.update(overrides)
    response = await client.post(PRODUCTS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


async def _create_customer(client, **overrides) -> dict:
    payload = {"name": "Test Customer", "owner_name": "Owner", "phone": _unique_phone()}
    payload.update(overrides)
    response = await client.post(CUSTOMERS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


def _valid_estimate_payload(customer_id: str, product_id: str, uom_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "lines": [{"product_id": product_id, "quantity": "10", "uom_id": uom_id, "unit_price": "100"}],
    }
    payload.update(overrides)
    return payload


async def _setup_basic(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    product = await _create_product(client, unit["id"])
    customer = await _create_customer(client)
    return unit, product, customer


# --- Create ---


async def test_create_valid_estimate(client):
    unit, product, customer = await _setup_basic(client)
    response = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["estimate_number"].startswith("EST-")
    assert len(data["lines"]) == 1


async def test_create_without_customer(client):
    unit, product, _ = await _setup_basic(client)
    response = await client.post(
        ESTIMATES_ENDPOINT,
        json={"lines": [{"product_id": product["id"], "quantity": "10", "uom_id": unit["id"], "unit_price": "100"}]},
        headers=_idem(),
    )
    assert response.status_code == 422


async def test_create_without_line_items(client):
    unit, product, customer = await _setup_basic(client)
    response = await client.post(ESTIMATES_ENDPOINT, json={"customer_id": customer["id"], "lines": []}, headers=_idem())
    assert response.status_code == 422


async def test_create_invalid_customer(client):
    unit, product, _ = await _setup_basic(client)
    response = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(str(uuid.uuid4()), product["id"], unit["id"]), headers=_idem()
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SALES-001"


async def test_create_inactive_customer(client):
    unit, product, customer = await _setup_basic(client)
    await client.post(f"{CUSTOMERS_ENDPOINT}/{customer['id']}/deactivate", json={"expected_row_version": customer["row_version"]})
    response = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SALES-002"


async def test_create_invalid_product(client):
    unit, product, customer = await _setup_basic(client)
    response = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], str(uuid.uuid4()), unit["id"]), headers=_idem()
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SALES-003"


async def test_create_inactive_product(client):
    unit, product, customer = await _setup_basic(client)
    await client.post(f"{PRODUCTS_ENDPOINT}/{product['id']}/deactivate", json={"expected_row_version": product["row_version"]})
    response = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SALES-004"


async def test_create_zero_quantity(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_estimate_payload(customer["id"], product["id"], unit["id"])
    payload["lines"][0]["quantity"] = "0"
    response = await client.post(ESTIMATES_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 422


async def test_create_negative_quantity(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_estimate_payload(customer["id"], product["id"], unit["id"])
    payload["lines"][0]["quantity"] = "-5"
    response = await client.post(ESTIMATES_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 422


async def test_create_negative_price(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_estimate_payload(customer["id"], product["id"], unit["id"])
    payload["lines"][0]["unit_price"] = "-10"
    response = await client.post(ESTIMATES_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 422


async def test_create_invalid_discount_both_types(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_estimate_payload(customer["id"], product["id"], unit["id"])
    payload["lines"][0]["discount_percent"] = "10"
    payload["lines"][0]["discount_amount"] = "50"
    response = await client.post(ESTIMATES_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 422


async def test_create_invalid_validity_date(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_estimate_payload(customer["id"], product["id"], unit["id"])
    payload["document_date"] = str(date.today())
    payload["valid_until_date"] = str(date.today() - timedelta(days=1))
    response = await client.post(ESTIMATES_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 422


# --- GST calculation ---


async def test_gst_calculation_intra_state(client):
    unit, product, customer = await _setup_basic(client)  # tenant state 33, customer no state -> intra-state
    response = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    data = response.json()["data"]
    line = data["lines"][0]
    # 10 x 100 = 1000 taxable; 18% GST = 180; intra-state => 90/90 split
    assert data["subtotal"] == "1000.00"
    assert line["cgst_amount"] == "90.00"
    assert line["sgst_amount"] == "90.00"
    assert line["igst_amount"] == "0.00"
    assert data["grand_total"] == "1180.00"


async def test_gst_calculation_inter_state(client):
    await _signup_and_login_owner(client, state_code="33")
    unit = await _create_unit(client)
    product = await _create_product(client, unit["id"])
    customer = await _create_customer(client, state_code="27")  # different state -> inter-state
    response = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    data = response.json()["data"]
    line = data["lines"][0]
    assert line["cgst_amount"] == "0.00"
    assert line["sgst_amount"] == "0.00"
    assert line["igst_amount"] == "180.00"


async def test_discount_before_gst(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_estimate_payload(customer["id"], product["id"], unit["id"])
    payload["lines"][0]["discount_amount"] = "100"
    response = await client.post(ESTIMATES_ENDPOINT, json=payload, headers=_idem())
    line = response.json()["data"]["lines"][0]
    # Taxable = 1000 - 100 = 900; GST 18% = 162 (81/81 split)
    assert line["taxable_amount"] == "900.00"
    assert line["cgst_amount"] == "81.00"
    assert line["sgst_amount"] == "81.00"


async def test_client_total_tampering_ignored(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_estimate_payload(customer["id"], product["id"], unit["id"])
    payload["grand_total"] = "1"  # not a real field on the schema — silently ignored
    response = await client.post(ESTIMATES_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 201
    assert response.json()["data"]["grand_total"] == "1180.00"  # server-calculated, not "1"


# --- Tenant isolation / permission ---


async def test_tenant_isolation(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    estimate_id = created.json()["data"]["id"]

    await _signup_and_login_owner(client)
    response = await client.get(f"{ESTIMATES_ENDPOINT}/{estimate_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EST-001"


async def test_unauthorized_no_session(client):
    response = await client.get(ESTIMATES_ENDPOINT)
    assert response.status_code == 401


async def test_permission_denied_salesperson_cannot_convert(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    estimate = created.json()["data"]

    await _create_salesperson_and_login(client)
    response = await client.post(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}/convert-to-sales-order",
        json={"expected_row_version": estimate["row_version"]},
        headers=_idem(),
    )
    assert response.status_code == 403


async def test_salesperson_can_create_and_send(client):
    unit, product, customer = await _setup_basic(client)
    await _create_salesperson_and_login(client)
    created = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    assert created.status_code == 201
    estimate = created.json()["data"]
    sent = await client.post(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}/send", json={"expected_row_version": estimate["row_version"]}
    )
    assert sent.status_code == 200
    assert sent.json()["data"]["status"] == "SENT"


# --- Edit / status transitions ---


async def test_edit_draft(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    estimate = created.json()["data"]
    response = await client.patch(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}",
        json={"notes": "Updated notes", "expected_row_version": estimate["row_version"]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["notes"] == "Updated notes"


async def test_invalid_status_transition_edit_after_send(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    estimate = created.json()["data"]
    sent = await client.post(f"{ESTIMATES_ENDPOINT}/{estimate['id']}/send", json={"expected_row_version": estimate["row_version"]})
    sent_data = sent.json()["data"]

    response = await client.patch(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}",
        json={"notes": "should fail", "expected_row_version": sent_data["row_version"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EST-002"


async def test_invalid_status_transition_accept_without_send(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    estimate = created.json()["data"]
    response = await client.post(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}/accept", json={"expected_row_version": estimate["row_version"]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EST-002"


async def test_row_version_conflict(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    estimate = created.json()["data"]
    first = await client.patch(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}", json={"notes": "first", "expected_row_version": estimate["row_version"]}
    )
    assert first.status_code == 200
    stale = await client.patch(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}", json={"notes": "stale", "expected_row_version": estimate["row_version"]}
    )
    assert stale.status_code == 412


# --- Expiry ---


async def test_expired_estimate_cannot_be_converted(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_estimate_payload(customer["id"], product["id"], unit["id"])
    payload["document_date"] = str(date.today() - timedelta(days=10))
    payload["valid_until_date"] = str(date.today() - timedelta(days=1))
    created = await client.post(ESTIMATES_ENDPOINT, json=payload, headers=_idem())
    estimate = created.json()["data"]

    response = await client.post(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}/convert-to-sales-order",
        json={"expected_row_version": estimate["row_version"]},
        headers=_idem(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EST-004"


async def test_get_estimate_lazily_marks_expired(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_estimate_payload(customer["id"], product["id"], unit["id"])
    payload["document_date"] = str(date.today() - timedelta(days=10))
    payload["valid_until_date"] = str(date.today() - timedelta(days=1))
    created = await client.post(ESTIMATES_ENDPOINT, json=payload, headers=_idem())
    estimate_id = created.json()["data"]["id"]

    detail = await client.get(f"{ESTIMATES_ENDPOINT}/{estimate_id}")
    assert detail.json()["data"]["status"] == "EXPIRED"


# --- Conversion: valid / rejected / duplicate / concurrent / idempotent ---


async def _create_and_send_estimate(client, unit, product, customer) -> dict:
    created = await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    return created.json()["data"]


async def test_convert_valid_estimate(client):
    unit, product, customer = await _setup_basic(client)
    estimate = await _create_and_send_estimate(client, unit, product, customer)

    response = await client.post(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}/convert-to-sales-order",
        json={"expected_row_version": estimate["row_version"]},
        headers=_idem(),
    )
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["status"] == "CONVERTED"
    assert body["sales_order_id"] is not None
    assert body["converted_at"] is not None


async def test_convert_rejected_estimate(client):
    unit, product, customer = await _setup_basic(client)
    estimate = await _create_and_send_estimate(client, unit, product, customer)
    sent = await client.post(f"{ESTIMATES_ENDPOINT}/{estimate['id']}/send", json={"expected_row_version": estimate["row_version"]})
    sent_data = sent.json()["data"]
    rejected = await client.post(f"{ESTIMATES_ENDPOINT}/{estimate['id']}/reject", json={"expected_row_version": sent_data["row_version"]})
    rejected_data = rejected.json()["data"]

    response = await client.post(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}/convert-to-sales-order",
        json={"expected_row_version": rejected_data["row_version"]},
        headers=_idem(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EST-002"


async def test_duplicate_conversion_rejected(client):
    unit, product, customer = await _setup_basic(client)
    estimate = await _create_and_send_estimate(client, unit, product, customer)

    first = await client.post(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}/convert-to-sales-order",
        json={"expected_row_version": estimate["row_version"]},
        headers=_idem(),
    )
    assert first.status_code == 201

    detail = await client.get(f"{ESTIMATES_ENDPOINT}/{estimate['id']}")
    current_row_version = detail.json()["data"]["row_version"]

    second = await client.post(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}/convert-to-sales-order",
        json={"expected_row_version": current_row_version},
        headers=_idem(),  # different idempotency key -> hits business logic, not replay
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "EST-003"


async def test_idempotent_conversion_retry(client):
    unit, product, customer = await _setup_basic(client)
    estimate = await _create_and_send_estimate(client, unit, product, customer)
    key = str(uuid.uuid4())

    first = await client.post(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}/convert-to-sales-order",
        json={"expected_row_version": estimate["row_version"]},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 201

    second = await client.post(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}/convert-to-sales-order",
        json={"expected_row_version": estimate["row_version"]},
        headers={"Idempotency-Key": key},
    )
    assert second.status_code == 201
    assert second.json()["data"] == first.json()["data"]  # replayed, not re-executed


async def test_concurrent_conversion_only_one_succeeds(client):
    unit, product, customer = await _setup_basic(client)
    estimate = await _create_and_send_estimate(client, unit, product, customer)

    async def _convert():
        return await client.post(
            f"{ESTIMATES_ENDPOINT}/{estimate['id']}/convert-to-sales-order",
            json={"expected_row_version": estimate["row_version"]},
            headers=_idem(),  # distinct keys -> real concurrency race, not idempotent replay
        )

    results = await asyncio.gather(_convert(), _convert())
    statuses = sorted(r.status_code for r in results)
    assert statuses == [201, 412] or statuses == [201, 409]


# --- Audit ---


async def test_audit_creation(client, db_session):
    unit, product, customer = await _setup_basic(client)
    await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )

    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    result = await db_session.execute(select(AuditLog).where(AuditLog.action == "ESTIMATE_CREATED"))
    assert result.scalars().first() is not None


# --- List / search / filter ---


async def test_list_and_search(client):
    unit, product, customer = await _setup_basic(client)
    await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    response = await client.get(ESTIMATES_ENDPOINT, params={"search": customer["name"][:6]})
    assert response.status_code == 200
    assert len(response.json()["data"]) >= 1


async def test_filter_by_status(client):
    unit, product, customer = await _setup_basic(client)
    await client.post(
        ESTIMATES_ENDPOINT, json=_valid_estimate_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    response = await client.get(ESTIMATES_ENDPOINT, params={"status": "DRAFT"})
    assert response.status_code == 200
    assert all(item["status"] == "DRAFT" for item in response.json()["data"])
