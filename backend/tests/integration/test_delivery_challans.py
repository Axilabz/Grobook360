"""PROMPT-014 test catalogue for /api/v1/sales/delivery-challans and the
Sales Order delivery-eligibility endpoint.

Follows test_sales_orders.py's structure and helper style. Covers §41's 25
core test cases plus the mandatory §42 stock test, §43 partial-delivery
test, and §44 over-delivery test.
"""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

DC_ENDPOINT = "/api/v1/sales/delivery-challans"
ORDERS_ENDPOINT = "/api/v1/sales/orders"
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
    return f"dc-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "Delivery Challan Test Co",
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


async def _setup_basic(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    product = await _create_product(client, unit["id"])
    customer = await _create_customer(client)
    return unit, product, customer


async def _seed_opening_stock(client, product_id: str, uom_id: str, quantity: str = "1000") -> None:
    response = await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock",
        json={"product_id": product_id, "quantity": quantity, "uom_id": uom_id},
        headers=_idem(),
    )
    assert response.status_code == 201


async def _available_quantity(client, product_id: str) -> str:
    response = await client.get(f"{INVENTORY_ENDPOINT}/availability/{product_id}")
    return response.json()["data"]["available_quantity"]


async def _create_confirmed_sales_order(client, unit, product, customer, quantity: str = "60") -> dict:
    payload = {
        "customer_id": customer["id"],
        "lines": [{"product_id": product["id"], "quantity": quantity, "uom_id": unit["id"], "unit_price": "100"}],
    }
    created = await client.post(ORDERS_ENDPOINT, json=payload, headers=_idem())
    assert created.status_code == 201
    order = created.json()["data"]
    confirmed = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]})
    assert confirmed.status_code == 200
    return confirmed.json()["data"]


def _dc_payload(sales_order_id: str, so_line_id: str, quantity: str, **overrides) -> dict:
    payload = {
        "sales_order_id": sales_order_id,
        "lines": [{"sales_order_line_id": so_line_id, "quantity": quantity}],
    }
    payload.update(overrides)
    return payload


async def _get_eligibility(client, sales_order_id: str) -> dict:
    response = await client.get(f"{ORDERS_ENDPOINT}/{sales_order_id}/delivery-eligibility")
    assert response.status_code == 200
    return response.json()["data"]


# --- Create ---


async def test_create_valid_draft_challan(client):
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]

    response = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "20"), headers=_idem())
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["challan_number"].startswith("DC-")
    assert len(data["lines"]) == 1
    assert Decimal(data["lines"][0]["current_delivery_quantity"]) == Decimal("20")
    assert Decimal(data["lines"][0]["remaining_quantity"]) == Decimal("40")


async def test_create_invalid_sales_order(client):
    await _signup_and_login_owner(client)
    response = await client.post(
        DC_ENDPOINT, json=_dc_payload(str(uuid.uuid4()), str(uuid.uuid4()), "10"), headers=_idem()
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SO-001"


async def test_create_against_cancelled_sales_order(client):
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]
    cancelled = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/cancel", json={"expected_row_version": order["row_version"]})
    assert cancelled.status_code == 200

    response = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "10"), headers=_idem())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DC-002"


async def test_create_against_fulfilled_sales_order(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "20")
    so_line_id = order["lines"][0]["id"]

    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "20"), headers=_idem())
    challan = created.json()["data"]
    confirmed = await client.post(f"{DC_ENDPOINT}/{challan['id']}/confirm", json={"expected_row_version": challan["row_version"]}, headers=_idem())
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "CONFIRMED"

    so_check = await client.get(f"{ORDERS_ENDPOINT}/{order['id']}")
    assert so_check.json()["data"]["status"] == "FULFILLED"

    response = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "1"), headers=_idem())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DC-002"


async def test_create_inactive_product(client):
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]
    await client.post(f"{PRODUCTS_ENDPOINT}/{product['id']}/deactivate", json={"expected_row_version": product["row_version"]})

    response = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "10"), headers=_idem())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SALES-004"


async def test_create_invalid_quantity(client):
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]

    response = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "0"), headers=_idem())
    assert response.status_code == 422


async def test_create_quantity_exceeds_remaining(client):
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]

    response = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "61"), headers=_idem())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DC-004"


# --- Delivery eligibility ---


async def test_delivery_eligibility_reflects_remaining(client):
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "100")
    eligibility = await _get_eligibility(client, order["id"])
    assert eligibility["lines"][0]["ordered_quantity"] == "100.000"
    assert eligibility["lines"][0]["delivered_quantity"] == "0.000"
    assert eligibility["lines"][0]["remaining_quantity"] == "100.000"


# --- Partial / full delivery (§43/§5) ---


async def test_partial_delivery_across_multiple_challans(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "100")
    so_line_id = order["lines"][0]["id"]

    # DC #1: deliver 40
    dc1 = (await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "40"), headers=_idem())).json()["data"]
    conf1 = await client.post(f"{DC_ENDPOINT}/{dc1['id']}/confirm", json={"expected_row_version": dc1["row_version"]}, headers=_idem())
    assert conf1.status_code == 200
    assert await _available_quantity(client, product["id"]) == "960.000"
    so_after_1 = (await client.get(f"{ORDERS_ENDPOINT}/{order['id']}")).json()["data"]
    assert so_after_1["status"] == "PARTIALLY_FULFILLED"

    # DC #2: deliver 30
    dc2 = (await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "30"), headers=_idem())).json()["data"]
    conf2 = await client.post(f"{DC_ENDPOINT}/{dc2['id']}/confirm", json={"expected_row_version": dc2["row_version"]}, headers=_idem())
    assert conf2.status_code == 200
    assert await _available_quantity(client, product["id"]) == "930.000"
    eligibility = await _get_eligibility(client, order["id"])
    assert eligibility["lines"][0]["delivered_quantity"] == "70.000"
    assert eligibility["lines"][0]["remaining_quantity"] == "30.000"

    # DC #3: deliver remaining 30 -> SO becomes FULFILLED
    dc3 = (await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "30"), headers=_idem())).json()["data"]
    conf3 = await client.post(f"{DC_ENDPOINT}/{dc3['id']}/confirm", json={"expected_row_version": dc3["row_version"]}, headers=_idem())
    assert conf3.status_code == 200
    assert await _available_quantity(client, product["id"]) == "900.000"
    so_final = (await client.get(f"{ORDERS_ENDPOINT}/{order['id']}")).json()["data"]
    assert so_final["status"] == "FULFILLED"


# --- Over-delivery (§44) ---


async def test_over_delivery_rejected(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "100")
    so_line_id = order["lines"][0]["id"]

    dc1 = (await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "80"), headers=_idem())).json()["data"]
    conf1 = await client.post(f"{DC_ENDPOINT}/{dc1['id']}/confirm", json={"expected_row_version": dc1["row_version"]}, headers=_idem())
    assert conf1.status_code == 200

    # remaining is now 20; attempt 30 must fail at creation time
    response = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "30"), headers=_idem())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DC-004"

    # verify no stock movement / fulfillment change from the rejected attempt
    assert await _available_quantity(client, product["id"]) == "920.000"
    eligibility = await _get_eligibility(client, order["id"])
    assert eligibility["lines"][0]["delivered_quantity"] == "80.000"


# --- §42 Mandatory stock test ---


async def test_mandatory_stock_movement_scenario(client, db_session):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]

    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "20"), headers=_idem())
    challan = created.json()["data"]
    confirmed = await client.post(f"{DC_ENDPOINT}/{challan['id']}/confirm", json={"expected_row_version": challan["row_version"]}, headers=_idem())
    assert confirmed.status_code == 200

    assert await _available_quantity(client, product["id"]) == "80.000"

    so_after = (await client.get(f"{ORDERS_ENDPOINT}/{order['id']}")).json()["data"]
    assert so_after["status"] == "PARTIALLY_FULFILLED"
    eligibility = await _get_eligibility(client, order["id"])
    assert eligibility["lines"][0]["delivered_quantity"] == "20.000"
    assert eligibility["lines"][0]["remaining_quantity"] == "40.000"

    from app.models.stock_ledger_entry import StockLedgerEntry

    result = await db_session.execute(
        select(StockLedgerEntry).where(
            StockLedgerEntry.product_id == uuid.UUID(product["id"]), StockLedgerEntry.movement_type == "STOCK_OUT"
        )
    )
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].quantity == Decimal("20.000")


# --- Insufficient stock ---


async def test_insufficient_stock_prevents_confirmation(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "10")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]

    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "20"), headers=_idem())
    challan = created.json()["data"]

    response = await client.post(f"{DC_ENDPOINT}/{challan['id']}/confirm", json={"expected_row_version": challan["row_version"]}, headers=_idem())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INV-003"

    # confirmation must have fully rolled back: no stock change, DC still DRAFT
    assert await _available_quantity(client, product["id"]) == "10.000"
    detail = await client.get(f"{DC_ENDPOINT}/{challan['id']}")
    assert detail.json()["data"]["status"] == "DRAFT"


# --- Duplicate confirmation / idempotency ---


async def test_duplicate_confirmation_rejected(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]

    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "20"), headers=_idem())
    challan = created.json()["data"]

    first = await client.post(f"{DC_ENDPOINT}/{challan['id']}/confirm", json={"expected_row_version": challan["row_version"]}, headers=_idem())
    assert first.status_code == 200

    detail = await client.get(f"{DC_ENDPOINT}/{challan['id']}")
    current_row_version = detail.json()["data"]["row_version"]

    second = await client.post(
        f"{DC_ENDPOINT}/{challan['id']}/confirm", json={"expected_row_version": current_row_version}, headers=_idem()
    )
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "DC-002"


async def test_idempotent_confirmation_retry(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]

    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "20"), headers=_idem())
    challan = created.json()["data"]
    key = str(uuid.uuid4())

    first = await client.post(f"{DC_ENDPOINT}/{challan['id']}/confirm", json={"expected_row_version": challan["row_version"]}, headers={"Idempotency-Key": key})
    assert first.status_code == 200

    second = await client.post(f"{DC_ENDPOINT}/{challan['id']}/confirm", json={"expected_row_version": challan["row_version"]}, headers={"Idempotency-Key": key})
    assert second.status_code == 200
    assert second.json()["data"] == first.json()["data"]

    assert await _available_quantity(client, product["id"]) == "980.000"  # only ONE stock-out applied


# --- Concurrency (§19/§20) ---


async def test_concurrent_delivery_cannot_exceed_remaining(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "50")
    so_line_id = order["lines"][0]["id"]

    dc_a = (await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "40"), headers=_idem())).json()["data"]
    dc_b = (await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "30"), headers=_idem())).json()["data"]

    async def _confirm(dc):
        return await client.post(f"{DC_ENDPOINT}/{dc['id']}/confirm", json={"expected_row_version": dc["row_version"]}, headers=_idem())

    results = await asyncio.gather(_confirm(dc_a), _confirm(dc_b))
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 422] or statuses == [200, 412]

    eligibility = await _get_eligibility(client, order["id"])
    delivered = Decimal(eligibility["lines"][0]["delivered_quantity"])
    assert delivered <= Decimal("50")


async def test_concurrent_stock_consumption_does_not_go_negative(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "50")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "100")
    so_line_id = order["lines"][0]["id"]

    dc_a = (await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "40"), headers=_idem())).json()["data"]
    dc_b = (await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "30"), headers=_idem())).json()["data"]

    async def _confirm(dc):
        return await client.post(f"{DC_ENDPOINT}/{dc['id']}/confirm", json={"expected_row_version": dc["row_version"]}, headers=_idem())

    results = await asyncio.gather(_confirm(dc_a), _confirm(dc_b))
    statuses = sorted(r.status_code for r in results)
    assert 200 in statuses
    assert statuses[1] in (409, 412, 422)  # insufficient stock, row-version conflict, or exceeds-remaining

    available = Decimal(await _available_quantity(client, product["id"]))
    assert available >= Decimal("0")


# --- Tenant isolation / permissions ---


async def test_tenant_isolation(client):
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]
    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "10"), headers=_idem())
    challan_id = created.json()["data"]["id"]

    await _signup_and_login_owner(client)  # switch to tenant B
    response = await client.get(f"{DC_ENDPOINT}/{challan_id}")
    assert response.status_code == 404


async def test_salesperson_cannot_confirm(client):
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]
    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "10"), headers=_idem())
    challan = created.json()["data"]

    await _create_salesperson_and_login(client)
    response = await client.post(f"{DC_ENDPOINT}/{challan['id']}/confirm", json={"expected_row_version": challan["row_version"]}, headers=_idem())
    assert response.status_code == 403


async def test_salesperson_can_create_and_edit(client):
    # Confirming the Sales Order requires Owner/Manager (PROMPT-013) — set
    # that up first, then switch to Salesperson to exercise DC create/edit.
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]

    await _create_salesperson_and_login(client)
    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "10"), headers=_idem())
    assert created.status_code == 201
    challan = created.json()["data"]

    edited = await client.patch(f"{DC_ENDPOINT}/{challan['id']}", json={"notes": "sp edit", "expected_row_version": challan["row_version"]})
    assert edited.status_code == 200


# --- Edit ---


async def test_edit_draft_challan(client):
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]
    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "10"), headers=_idem())
    challan = created.json()["data"]

    response = await client.patch(
        f"{DC_ENDPOINT}/{challan['id']}", json={"notes": "updated", "expected_row_version": challan["row_version"]}
    )
    assert response.status_code == 200
    assert response.json()["data"]["notes"] == "updated"


async def test_prevent_edit_after_confirmation(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]
    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "10"), headers=_idem())
    challan = created.json()["data"]
    confirmed = await client.post(f"{DC_ENDPOINT}/{challan['id']}/confirm", json={"expected_row_version": challan["row_version"]}, headers=_idem())
    confirmed_data = confirmed.json()["data"]

    response = await client.patch(
        f"{DC_ENDPOINT}/{challan['id']}", json={"notes": "x", "expected_row_version": confirmed_data["row_version"]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DC-002"


# --- Row-version conflict ---


async def test_row_version_conflict(client):
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]
    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "10"), headers=_idem())
    challan = created.json()["data"]

    first = await client.patch(
        f"{DC_ENDPOINT}/{challan['id']}", json={"notes": "first", "expected_row_version": challan["row_version"]}
    )
    assert first.status_code == 200
    stale = await client.patch(
        f"{DC_ENDPOINT}/{challan['id']}", json={"notes": "stale", "expected_row_version": challan["row_version"]}
    )
    assert stale.status_code == 412


# --- Cancellation ---


async def test_cancel_draft_challan(client):
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]
    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "10"), headers=_idem())
    challan = created.json()["data"]

    response = await client.post(f"{DC_ENDPOINT}/{challan['id']}/cancel", json={"expected_row_version": challan["row_version"]})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"


async def test_cannot_cancel_confirmed_challan(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]
    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "10"), headers=_idem())
    challan = created.json()["data"]
    confirmed = await client.post(f"{DC_ENDPOINT}/{challan['id']}/confirm", json={"expected_row_version": challan["row_version"]}, headers=_idem())
    confirmed_data = confirmed.json()["data"]

    response = await client.post(
        f"{DC_ENDPOINT}/{challan['id']}/cancel", json={"expected_row_version": confirmed_data["row_version"]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DC-002"


# --- Audit ---


async def test_audit_creation(client, db_session):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]
    created = await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "10"), headers=_idem())
    challan = created.json()["data"]
    await client.post(f"{DC_ENDPOINT}/{challan['id']}/confirm", json={"expected_row_version": challan["row_version"]}, headers=_idem())

    from app.models.audit_log import AuditLog

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_type == "delivery_challan", AuditLog.entity_id == uuid.UUID(challan["id"]))
    )
    entries = result.scalars().all()
    actions = {e.action for e in entries}
    assert "DELIVERY_CHALLAN_CREATED" in actions
    assert "DELIVERY_CHALLAN_CONFIRMED" in actions

    so_result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_type == "sales_order", AuditLog.action == "SALES_ORDER_FULFILLMENT_UPDATED")
    )
    assert len(so_result.scalars().all()) >= 1


# --- List / search / filter ---


async def test_list_challans_search_and_filter(client):
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]
    await client.post(DC_ENDPOINT, json=_dc_payload(order["id"], so_line_id, "10"), headers=_idem())

    listed = await client.get(DC_ENDPOINT, params={"search": customer["name"]})
    assert listed.status_code == 200
    assert listed.json()["pagination"]["total_items"] == 1

    filtered = await client.get(DC_ENDPOINT, params={"status": "DRAFT"})
    assert filtered.json()["pagination"]["total_items"] == 1

    filtered_none = await client.get(DC_ENDPOINT, params={"status": "CONFIRMED"})
    assert filtered_none.json()["pagination"]["total_items"] == 0

    by_order = await client.get(DC_ENDPOINT, params={"sales_order_id": order["id"]})
    assert by_order.json()["pagination"]["total_items"] == 1
