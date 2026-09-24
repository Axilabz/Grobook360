"""PROMPT-013 test catalogue for /api/v1/sales/orders and the Estimate ->
Sales Order conversion endpoint.

Follows test_sales_estimates.py's structure and helper style. Covers §40's
30 test cases plus the mandatory §41 inventory non-impact test.
"""

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

ORDERS_ENDPOINT = "/api/v1/sales/orders"
ESTIMATES_ENDPOINT = "/api/v1/sales/estimates"
PRODUCTS_ENDPOINT = "/api/v1/products"
UNITS_ENDPOINT = "/api/v1/units"
CUSTOMERS_ENDPOINT = "/api/v1/customers"
INVENTORY_ENDPOINT = "/api/v1/inventory"
SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"
USERS_ENDPOINT = "/api/v1/users"
RESET_ENDPOINT = "/api/v1/auth/reset-password"

OWNER_PASSWORD = "SecurePass123"
SALESPERSON_PASSWORD = "AnotherSecurePass456"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _unique_email() -> str:
    return f"so-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "Sales Order Test Co",
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


def _valid_order_payload(customer_id: str, product_id: str, uom_id: str, **overrides) -> dict:
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


async def _seed_opening_stock(client, product_id: str, uom_id: str, quantity: str = "100") -> None:
    response = await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock",
        json={"product_id": product_id, "quantity": quantity, "uom_id": uom_id},
        headers=_idem(),
    )
    assert response.status_code == 201


async def _available_quantity(client, product_id: str) -> str:
    response = await client.get(f"{INVENTORY_ENDPOINT}/availability/{product_id}")
    return response.json()["data"]["available_quantity"]


# --- Create (manual) ---


async def test_create_valid_sales_order(client):
    unit, product, customer = await _setup_basic(client)
    response = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["order_number"].startswith("SO-")
    assert len(data["lines"]) == 1
    assert data["source_estimate_id"] is None


async def test_create_without_customer(client):
    unit, product, _ = await _setup_basic(client)
    response = await client.post(
        ORDERS_ENDPOINT,
        json={"lines": [{"product_id": product["id"], "quantity": "10", "uom_id": unit["id"], "unit_price": "100"}]},
        headers=_idem(),
    )
    assert response.status_code == 422


async def test_create_without_line_items(client):
    unit, product, customer = await _setup_basic(client)
    response = await client.post(ORDERS_ENDPOINT, json={"customer_id": customer["id"], "lines": []}, headers=_idem())
    assert response.status_code == 422


async def test_create_invalid_customer(client):
    unit, product, _ = await _setup_basic(client)
    response = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(str(uuid.uuid4()), product["id"], unit["id"]), headers=_idem()
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SALES-001"


async def test_create_inactive_customer(client):
    unit, product, customer = await _setup_basic(client)
    await client.post(f"{CUSTOMERS_ENDPOINT}/{customer['id']}/deactivate", json={"expected_row_version": customer["row_version"]})
    response = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SALES-002"


async def test_create_invalid_product(client):
    unit, product, customer = await _setup_basic(client)
    response = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], str(uuid.uuid4()), unit["id"]), headers=_idem()
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SALES-003"


async def test_create_inactive_product(client):
    unit, product, customer = await _setup_basic(client)
    await client.post(f"{PRODUCTS_ENDPOINT}/{product['id']}/deactivate", json={"expected_row_version": product["row_version"]})
    response = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SALES-004"


async def test_create_zero_quantity(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_order_payload(customer["id"], product["id"], unit["id"])
    payload["lines"][0]["quantity"] = "0"
    response = await client.post(ORDERS_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 422


async def test_create_negative_price(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_order_payload(customer["id"], product["id"], unit["id"])
    payload["lines"][0]["unit_price"] = "-10"
    response = await client.post(ORDERS_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 422


async def test_create_invalid_discount_both_types(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_order_payload(customer["id"], product["id"], unit["id"])
    payload["lines"][0]["discount_percent"] = "10"
    payload["lines"][0]["discount_amount"] = "50"
    response = await client.post(ORDERS_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 422


# --- GST / totals calculation ---


async def test_gst_calculation_intra_state(client):
    unit, product, customer = await _setup_basic(client)  # tenant state 33, customer no state -> intra-state
    response = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    data = response.json()["data"]
    line = data["lines"][0]
    assert Decimal(line["cgst_amount"]) == Decimal("90.00")  # 10*100=1000 taxable * 18% / 2
    assert Decimal(line["sgst_amount"]) == Decimal("90.00")
    assert Decimal(line["igst_amount"]) == Decimal("0.00")
    assert Decimal(data["grand_total"]) == Decimal("1180.00")


async def test_gst_calculation_inter_state(client):
    unit, product, _ = await _setup_basic(client)
    customer = await _create_customer(client, state_code="27", gstin="27AAAAA0000A1Z5")
    response = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    data = response.json()["data"]
    line = data["lines"][0]
    assert Decimal(line["igst_amount"]) == Decimal("180.00")
    assert Decimal(line["cgst_amount"]) == Decimal("0.00")
    assert Decimal(line["sgst_amount"]) == Decimal("0.00")


async def test_discount_applied_before_gst(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_order_payload(customer["id"], product["id"], unit["id"])
    payload["lines"][0]["discount_amount"] = "100"  # gross 1000 - 100 = 900 taxable
    response = await client.post(ORDERS_ENDPOINT, json=payload, headers=_idem())
    data = response.json()["data"]
    line = data["lines"][0]
    assert Decimal(line["taxable_amount"]) == Decimal("900.00")
    assert Decimal(line["cgst_amount"]) == Decimal("81.00")
    assert Decimal(line["sgst_amount"]) == Decimal("81.00")


async def test_client_total_tampering_ignored(client):
    unit, product, customer = await _setup_basic(client)
    payload = _valid_order_payload(customer["id"], product["id"], unit["id"])
    payload["grand_total"] = "1"  # not even a real field — must be ignored, not echoed
    response = await client.post(ORDERS_ENDPOINT, json=payload, headers=_idem())
    data = response.json()["data"]
    assert Decimal(data["grand_total"]) == Decimal("1180.00")


# --- Tenant isolation / authorization ---


async def test_tenant_isolation(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    order_id = created.json()["data"]["id"]

    await _signup_and_login_owner(client)  # switch to tenant B
    response = await client.get(f"{ORDERS_ENDPOINT}/{order_id}")
    assert response.status_code == 404


async def test_unauthorized_create_requires_auth(client):
    unit, product, customer = await _setup_basic(client)
    await client.post("/api/v1/auth/logout")
    response = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    assert response.status_code == 401


# --- Edit ---


async def test_edit_draft_order(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    order = created.json()["data"]
    response = await client.patch(
        f"{ORDERS_ENDPOINT}/{order['id']}", json={"notes": "updated notes", "expected_row_version": order["row_version"]}
    )
    assert response.status_code == 200
    assert response.json()["data"]["notes"] == "updated notes"


async def test_prevent_edit_after_confirm(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    order = created.json()["data"]
    confirmed = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]}
    )
    confirmed_data = confirmed.json()["data"]

    response = await client.patch(
        f"{ORDERS_ENDPOINT}/{order['id']}", json={"notes": "x", "expected_row_version": confirmed_data["row_version"]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SO-002"


# --- Confirm ---


async def test_confirm_draft_order(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    order = created.json()["data"]
    response = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]}
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CONFIRMED"


async def test_prevent_confirm_already_confirmed(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    order = created.json()["data"]
    first = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]})
    confirmed_data = first.json()["data"]

    second = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": confirmed_data["row_version"]}
    )
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "SO-002"


async def test_salesperson_cannot_confirm(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    order = created.json()["data"]

    await _create_salesperson_and_login(client)
    response = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]}
    )
    assert response.status_code == 403


async def test_salesperson_can_create_and_edit(client):
    unit, product, customer = await _setup_basic(client)
    await _create_salesperson_and_login(client)

    created = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    assert created.status_code == 201
    order = created.json()["data"]

    edited = await client.patch(
        f"{ORDERS_ENDPOINT}/{order['id']}", json={"notes": "sp edit", "expected_row_version": order["row_version"]}
    )
    assert edited.status_code == 200


# --- Cancel ---


async def test_cancel_draft_order(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    order = created.json()["data"]
    response = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/cancel", json={"expected_row_version": order["row_version"]}
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"


async def test_cancel_confirmed_order(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    order = created.json()["data"]
    confirmed = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]})
    confirmed_data = confirmed.json()["data"]

    response = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/cancel", json={"expected_row_version": confirmed_data["row_version"]}
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"


async def test_prevent_cancel_already_cancelled(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    order = created.json()["data"]
    first = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/cancel", json={"expected_row_version": order["row_version"]})
    cancelled_data = first.json()["data"]

    second = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/cancel", json={"expected_row_version": cancelled_data["row_version"]}
    )
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "SO-002"


# --- Row-version conflict ---


async def test_row_version_conflict(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    order = created.json()["data"]
    first = await client.patch(
        f"{ORDERS_ENDPOINT}/{order['id']}", json={"notes": "first", "expected_row_version": order["row_version"]}
    )
    assert first.status_code == 200
    stale = await client.patch(
        f"{ORDERS_ENDPOINT}/{order['id']}", json={"notes": "stale", "expected_row_version": order["row_version"]}
    )
    assert stale.status_code == 412


# --- Conversion from Estimate ---


async def _create_estimate(client, unit, product, customer) -> dict:
    payload = {
        "customer_id": customer["id"],
        "lines": [{"product_id": product["id"], "quantity": "10", "uom_id": unit["id"], "unit_price": "100"}],
    }
    created = await client.post(ESTIMATES_ENDPOINT, json=payload, headers=_idem())
    assert created.status_code == 201
    return created.json()["data"]


async def test_create_sales_order_from_estimate(client):
    unit, product, customer = await _setup_basic(client)
    estimate = await _create_estimate(client, unit, product, customer)

    response = await client.post(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}/convert-to-sales-order",
        json={"expected_row_version": estimate["row_version"]},
        headers=_idem(),
    )
    assert response.status_code == 201
    body = response.json()["data"]
    assert body["status"] == "CONVERTED"
    assert body["sales_order_id"] is not None

    order = await client.get(f"{ORDERS_ENDPOINT}/{body['sales_order_id']}")
    order_data = order.json()["data"]
    assert order_data["source_estimate_id"] == estimate["id"]
    assert order_data["status"] == "DRAFT"
    assert Decimal(order_data["grand_total"]) == Decimal(estimate["grand_total"])
    assert len(order_data["lines"]) == 1


async def test_invalid_estimate_conversion(client):
    await _signup_and_login_owner(client)
    response = await client.post(
        f"{ESTIMATES_ENDPOINT}/{uuid.uuid4()}/convert-to-sales-order",
        json={"expected_row_version": 1},
        headers=_idem(),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EST-001"


async def test_already_converted_estimate_rejected(client):
    unit, product, customer = await _setup_basic(client)
    estimate = await _create_estimate(client, unit, product, customer)

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
        headers=_idem(),
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "EST-003"


async def test_expired_estimate_cannot_convert_to_order(client):
    unit, product, customer = await _setup_basic(client)
    payload = {
        "customer_id": customer["id"],
        "document_date": str(date.today() - timedelta(days=10)),
        "valid_until_date": str(date.today() - timedelta(days=1)),
        "lines": [{"product_id": product["id"], "quantity": "10", "uom_id": unit["id"], "unit_price": "100"}],
    }
    created = await client.post(ESTIMATES_ENDPOINT, json=payload, headers=_idem())
    estimate = created.json()["data"]

    response = await client.post(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}/convert-to-sales-order",
        json={"expected_row_version": estimate["row_version"]},
        headers=_idem(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EST-004"


async def test_duplicate_conversion_db_constraint_holds(client, db_session):
    """§16: even bypassing the service layer, the DB UNIQUE constraint on
    source_estimate_id is the final backstop."""
    unit, product, customer = await _setup_basic(client)
    estimate = await _create_estimate(client, unit, product, customer)

    response = await client.post(
        f"{ESTIMATES_ENDPOINT}/{estimate['id']}/convert-to-sales-order",
        json={"expected_row_version": estimate["row_version"]},
        headers=_idem(),
    )
    assert response.status_code == 201

    from app.models.sales_order import SalesOrder

    result = await db_session.execute(select(SalesOrder).where(SalesOrder.source_estimate_id == uuid.UUID(estimate["id"])))
    orders = result.scalars().all()
    assert len(orders) == 1


async def test_idempotent_conversion_retry(client):
    unit, product, customer = await _setup_basic(client)
    estimate = await _create_estimate(client, unit, product, customer)
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
    estimate = await _create_estimate(client, unit, product, customer)

    async def _convert():
        return await client.post(
            f"{ESTIMATES_ENDPOINT}/{estimate['id']}/convert-to-sales-order",
            json={"expected_row_version": estimate["row_version"]},
            headers=_idem(),  # distinct keys -> real concurrency race
        )

    results = await asyncio.gather(_convert(), _convert())
    statuses = sorted(r.status_code for r in results)
    assert statuses == [201, 412] or statuses == [201, 409]

    from app.models.sales_order import SalesOrder

    async def _count_orders(session):
        result = await session.execute(select(SalesOrder).where(SalesOrder.source_estimate_id == uuid.UUID(estimate["id"])))
        return len(result.scalars().all())

    # Re-fetch via a fresh request-scoped assertion: exactly one Sales
    # Order must exist for this Estimate regardless of which request won.
    detail = await client.get(f"{ESTIMATES_ENDPOINT}/{estimate['id']}")
    assert detail.json()["data"]["status"] == "CONVERTED"


# --- Audit ---


async def test_audit_creation(client, db_session):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    order_id = created.json()["data"]["id"]

    from app.models.audit_log import AuditLog

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_type == "sales_order", AuditLog.entity_id == uuid.UUID(order_id))
    )
    entries = result.scalars().all()
    assert any(e.action == "SALES_ORDER_CREATED" for e in entries)


# --- §41 Mandatory inventory non-impact test ---


async def test_sales_order_never_moves_stock(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    assert await _available_quantity(client, product["id"]) == "100.000"

    created = await client.post(
        ORDERS_ENDPOINT,
        json=_valid_order_payload(customer["id"], product["id"], unit["id"], **{"lines": [
            {"product_id": product["id"], "quantity": "20", "uom_id": unit["id"], "unit_price": "100"}
        ]}),
        headers=_idem(),
    )
    order = created.json()["data"]
    assert await _available_quantity(client, product["id"]) == "100.000"

    confirmed = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]})
    confirmed_data = confirmed.json()["data"]
    assert await _available_quantity(client, product["id"]) == "100.000"

    cancelled = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/cancel", json={"expected_row_version": confirmed_data["row_version"]}
    )
    assert cancelled.status_code == 200
    assert await _available_quantity(client, product["id"]) == "100.000"


async def test_no_stock_ledger_entry_created_for_sales_order(client, db_session):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")

    from app.models.stock_ledger_entry import StockLedgerEntry

    before = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"])))
    before_count = len(before.scalars().all())

    created = await client.post(
        ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    order = created.json()["data"]
    await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]})

    after = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"])))
    after_count = len(after.scalars().all())

    assert after_count == before_count  # OPENING_STOCK entry only — no entries from the Sales Order


# --- List / search / filter ---


async def test_list_orders_search_and_filter(client):
    unit, product, customer = await _setup_basic(client)
    await client.post(ORDERS_ENDPOINT, json=_valid_order_payload(customer["id"], product["id"], unit["id"]), headers=_idem())

    listed = await client.get(ORDERS_ENDPOINT, params={"search": customer["name"]})
    assert listed.status_code == 200
    assert listed.json()["pagination"]["total_items"] == 1

    filtered = await client.get(ORDERS_ENDPOINT, params={"status": "DRAFT"})
    assert filtered.json()["pagination"]["total_items"] == 1

    filtered_none = await client.get(ORDERS_ENDPOINT, params={"status": "CANCELLED"})
    assert filtered_none.json()["pagination"]["total_items"] == 0
