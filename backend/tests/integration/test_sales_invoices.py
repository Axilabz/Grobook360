"""PROMPT-015 test catalogue for /api/v1/sales/invoices and the Delivery
Challan invoice-eligibility/create-invoice endpoints.

Follows test_delivery_challans.py's structure and helper style. Covers
§46's 27 core test cases plus the mandatory §47 double-stock-deduction
test, §48 direct-invoice test, and §49 over-invoicing test.
"""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

INVOICES_ENDPOINT = "/api/v1/sales/invoices"
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
    return f"si-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "Sales Invoice Test Co",
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


async def _create_confirmed_challan(client, order: dict, quantity: str) -> dict:
    so_line_id = order["lines"][0]["id"]
    created = await client.post(
        DC_ENDPOINT,
        json={"sales_order_id": order["id"], "lines": [{"sales_order_line_id": so_line_id, "quantity": quantity}]},
        headers=_idem(),
    )
    assert created.status_code == 201
    challan = created.json()["data"]
    confirmed = await client.post(f"{DC_ENDPOINT}/{challan['id']}/confirm", json={"expected_row_version": challan["row_version"]}, headers=_idem())
    assert confirmed.status_code == 200
    return confirmed.json()["data"]


def _direct_invoice_payload(customer_id: str, product_id: str, uom_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "lines": [{"product_id": product_id, "quantity": "10", "uom_id": uom_id, "unit_price": "100"}],
    }
    payload.update(overrides)
    return payload


async def _get_invoice_eligibility(client, challan_id: str) -> dict:
    response = await client.get(f"{DC_ENDPOINT}/{challan_id}/invoice-eligibility")
    assert response.status_code == 200
    return response.json()["data"]


async def _create_invoice_from_challan(client, challan_id: str, dc_line_id: str, quantity: str, **overrides) -> dict:
    payload = {"lines": [{"source_delivery_challan_line_id": dc_line_id, "quantity": quantity}]}
    payload.update(overrides)
    response = await client.post(f"{DC_ENDPOINT}/{challan_id}/create-invoice", json=payload, headers=_idem())
    return response


# --- Create: Direct Invoice ---


async def test_create_direct_invoice_draft(client):
    unit, product, customer = await _setup_basic(client)
    response = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["invoice_type"] == "DIRECT_SALES_INVOICE"
    assert data["invoice_number"].startswith("INV-")
    assert len(data["lines"]) == 1
    assert data["source_delivery_challan_id"] is None


async def test_create_invalid_customer(client):
    unit, product, _ = await _setup_basic(client)
    response = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(str(uuid.uuid4()), product["id"], unit["id"]), headers=_idem()
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SALES-001"


async def test_create_inactive_customer(client):
    unit, product, customer = await _setup_basic(client)
    await client.post(f"{CUSTOMERS_ENDPOINT}/{customer['id']}/deactivate", json={"expected_row_version": customer["row_version"]})
    response = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SALES-002"


async def test_create_invalid_product(client):
    unit, product, customer = await _setup_basic(client)
    response = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], str(uuid.uuid4()), unit["id"]), headers=_idem()
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SALES-003"


async def test_create_inactive_product(client):
    unit, product, customer = await _setup_basic(client)
    await client.post(f"{PRODUCTS_ENDPOINT}/{product['id']}/deactivate", json={"expected_row_version": product["row_version"]})
    response = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SALES-004"


async def test_create_invalid_quantity(client):
    unit, product, customer = await _setup_basic(client)
    payload = _direct_invoice_payload(customer["id"], product["id"], unit["id"])
    payload["lines"][0]["quantity"] = "0"
    response = await client.post(INVOICES_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 422


async def test_create_invalid_discount_both_types(client):
    unit, product, customer = await _setup_basic(client)
    payload = _direct_invoice_payload(customer["id"], product["id"], unit["id"])
    payload["lines"][0]["discount_percent"] = "10"
    payload["lines"][0]["discount_amount"] = "50"
    response = await client.post(INVOICES_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 422


# --- GST / totals ---


async def test_gst_calculation_direct_invoice(client):
    unit, product, customer = await _setup_basic(client)
    response = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    data = response.json()["data"]
    line = data["lines"][0]
    assert Decimal(line["cgst_amount"]) == Decimal("90.00")  # 10*100=1000 taxable * 18% / 2
    assert Decimal(line["sgst_amount"]) == Decimal("90.00")
    assert Decimal(data["grand_total"]) == Decimal("1180.00")


async def test_client_total_tampering_ignored(client):
    unit, product, customer = await _setup_basic(client)
    payload = _direct_invoice_payload(customer["id"], product["id"], unit["id"])
    payload["grand_total"] = "1"
    response = await client.post(INVOICES_ENDPOINT, json=payload, headers=_idem())
    data = response.json()["data"]
    assert Decimal(data["grand_total"]) == Decimal("1180.00")


# --- §48 Mandatory direct-invoice test ---


async def test_mandatory_direct_invoice_scenario(client, db_session):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")

    payload = _direct_invoice_payload(customer["id"], product["id"], unit["id"])
    payload["lines"][0]["quantity"] = "20"
    created = await client.post(INVOICES_ENDPOINT, json=payload, headers=_idem())
    invoice = created.json()["data"]

    assert await _available_quantity(client, product["id"]) == "100.000"  # DRAFT: no stock impact yet

    posted = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    posted_data = posted.json()["data"]
    assert posted_data["status"] == "POSTED"
    assert posted_data["accounting_posting_reference"] is not None
    assert posted_data["gst_transaction_reference"] is not None

    assert await _available_quantity(client, product["id"]) == "80.000"

    from app.models.stock_ledger_entry import StockLedgerEntry

    result = await db_session.execute(
        select(StockLedgerEntry).where(
            StockLedgerEntry.product_id == uuid.UUID(product["id"]), StockLedgerEntry.movement_type == "STOCK_OUT"
        )
    )
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].quantity == Decimal("20.000")


async def test_posting_requires_status_draft(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    created = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    invoice = created.json()["data"]
    first = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert first.status_code == 200
    posted = first.json()["data"]

    second = await client.post(
        f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": posted["row_version"]}, headers=_idem()
    )
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "SI-002"


async def test_idempotent_post_retry(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    created = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    invoice = created.json()["data"]
    key = str(uuid.uuid4())

    first = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers={"Idempotency-Key": key})
    assert first.status_code == 200
    second = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers={"Idempotency-Key": key})
    assert second.status_code == 200
    assert second.json()["data"] == first.json()["data"]
    assert await _available_quantity(client, product["id"]) == "90.000"  # only ONE stock-out applied


async def test_concurrent_posting_only_one_succeeds(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    created = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    invoice = created.json()["data"]

    async def _post():
        return await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())

    results = await asyncio.gather(_post(), _post())
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 412] or statuses == [200, 422]
    assert await _available_quantity(client, product["id"]) == "90.000"


# --- Create / Post: from Delivery Challan ---


async def test_create_invoice_from_confirmed_dc(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    challan = await _create_confirmed_challan(client, order, "20")

    eligibility = await _get_invoice_eligibility(client, challan["id"])
    dc_line_id = eligibility["lines"][0]["source_delivery_challan_line_id"]
    assert eligibility["lines"][0]["invoiceable_quantity"] == "20.000"

    response = await _create_invoice_from_challan(client, challan["id"], dc_line_id, "20")
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["invoice_type"] == "DELIVERY_CHALLAN_SALES_INVOICE"
    assert data["source_delivery_challan_id"] == challan["id"]
    assert data["status"] == "DRAFT"
    assert Decimal(data["lines"][0]["unit_price"]) == Decimal("100")


async def test_invoice_from_unconfirmed_dc_rejected(client):
    unit, product, customer = await _setup_basic(client)
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    so_line_id = order["lines"][0]["id"]
    created = await client.post(
        DC_ENDPOINT, json={"sales_order_id": order["id"], "lines": [{"sales_order_line_id": so_line_id, "quantity": "10"}]}, headers=_idem()
    )
    draft_challan = created.json()["data"]  # never confirmed

    response = await client.get(f"{DC_ENDPOINT}/{draft_challan['id']}/invoice-eligibility")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SI-007"


# --- §47 Mandatory double-stock-deduction test ---


async def test_mandatory_no_double_stock_deduction(client, db_session):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "20")
    challan = await _create_confirmed_challan(client, order, "20")

    assert await _available_quantity(client, product["id"]) == "80.000"

    eligibility = await _get_invoice_eligibility(client, challan["id"])
    dc_line_id = eligibility["lines"][0]["source_delivery_challan_line_id"]
    created = await _create_invoice_from_challan(client, challan["id"], dc_line_id, "20")
    assert created.status_code == 201
    invoice = created.json()["data"]

    posted = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert posted.status_code == 200

    # CRITICAL: stock must remain 80, NOT drop to 60.
    assert await _available_quantity(client, product["id"]) == "80.000"

    from app.models.stock_ledger_entry import StockLedgerEntry

    result = await db_session.execute(
        select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"]))
    )
    entries = result.scalars().all()
    stock_out_entries = [e for e in entries if e.movement_type == "STOCK_OUT"]
    assert len(stock_out_entries) == 1  # from the Delivery Challan confirm — NOT a second one from the invoice


async def test_dc_based_invoice_creates_no_stock_ledger_entry_of_its_own(client, db_session):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "60")
    challan = await _create_confirmed_challan(client, order, "20")

    from app.models.stock_ledger_entry import StockLedgerEntry

    before = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"])))
    before_count = len(before.scalars().all())

    eligibility = await _get_invoice_eligibility(client, challan["id"])
    dc_line_id = eligibility["lines"][0]["source_delivery_challan_line_id"]
    created = await _create_invoice_from_challan(client, challan["id"], dc_line_id, "20")
    invoice = created.json()["data"]
    await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())

    after = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"])))
    after_count = len(after.scalars().all())
    assert after_count == before_count


# --- §49 Over-invoicing test ---


async def test_over_invoicing_rejected(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "100")
    challan = await _create_confirmed_challan(client, order, "100")

    eligibility = await _get_invoice_eligibility(client, challan["id"])
    dc_line_id = eligibility["lines"][0]["source_delivery_challan_line_id"]

    first = await _create_invoice_from_challan(client, challan["id"], dc_line_id, "70")
    assert first.status_code == 201
    invoice1 = first.json()["data"]
    posted1 = await client.post(f"{INVOICES_ENDPOINT}/{invoice1['id']}/post", json={"expected_row_version": invoice1["row_version"]}, headers=_idem())
    assert posted1.status_code == 200

    # remaining invoiceable is 30; attempt 40 must fail
    second = await _create_invoice_from_challan(client, challan["id"], dc_line_id, "40")
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "SI-004"


async def test_concurrent_invoicing_against_same_dc(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    order = await _create_confirmed_sales_order(client, unit, product, customer, "50")
    challan = await _create_confirmed_challan(client, order, "50")

    eligibility = await _get_invoice_eligibility(client, challan["id"])
    dc_line_id = eligibility["lines"][0]["source_delivery_challan_line_id"]

    inv_a = (await _create_invoice_from_challan(client, challan["id"], dc_line_id, "40")).json()["data"]
    inv_b = (await _create_invoice_from_challan(client, challan["id"], dc_line_id, "30")).json()["data"]

    async def _post(inv):
        return await client.post(f"{INVOICES_ENDPOINT}/{inv['id']}/post", json={"expected_row_version": inv["row_version"]}, headers=_idem())

    results = await asyncio.gather(_post(inv_a), _post(inv_b))
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 422] or statuses == [200, 412]

    final_eligibility = await _get_invoice_eligibility(client, challan["id"])
    assert Decimal(final_eligibility["lines"][0]["invoiced_quantity"]) <= Decimal("50")


# --- Immutability / cancellation ---


async def test_posted_invoice_immutable(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    created = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    invoice = created.json()["data"]
    posted = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    posted_data = posted.json()["data"]

    response = await client.patch(
        f"{INVOICES_ENDPOINT}/{invoice['id']}", json={"notes": "x", "expected_row_version": posted_data["row_version"]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SI-002"


async def test_edit_draft_invoice(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    invoice = created.json()["data"]
    response = await client.patch(
        f"{INVOICES_ENDPOINT}/{invoice['id']}", json={"notes": "updated", "expected_row_version": invoice["row_version"]}
    )
    assert response.status_code == 200
    assert response.json()["data"]["notes"] == "updated"


async def test_cancel_draft_invoice(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    invoice = created.json()["data"]
    response = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/cancel", json={"expected_row_version": invoice["row_version"]})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"


async def test_cannot_cancel_posted_invoice(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    created = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    invoice = created.json()["data"]
    posted = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    posted_data = posted.json()["data"]

    response = await client.post(
        f"{INVOICES_ENDPOINT}/{invoice['id']}/cancel", json={"expected_row_version": posted_data["row_version"]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SI-002"


# --- Row-version conflict ---


async def test_row_version_conflict(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    invoice = created.json()["data"]
    first = await client.patch(
        f"{INVOICES_ENDPOINT}/{invoice['id']}", json={"notes": "first", "expected_row_version": invoice["row_version"]}
    )
    assert first.status_code == 200
    stale = await client.patch(
        f"{INVOICES_ENDPOINT}/{invoice['id']}", json={"notes": "stale", "expected_row_version": invoice["row_version"]}
    )
    assert stale.status_code == 412


# --- Tenant isolation / permissions ---


async def test_tenant_isolation(client):
    unit, product, customer = await _setup_basic(client)
    created = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    invoice_id = created.json()["data"]["id"]

    await _signup_and_login_owner(client)  # switch to tenant B
    response = await client.get(f"{INVOICES_ENDPOINT}/{invoice_id}")
    assert response.status_code == 404


async def test_salesperson_cannot_post(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    created = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    invoice = created.json()["data"]

    await _create_salesperson_and_login(client)
    response = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert response.status_code == 403


async def test_salesperson_can_create_and_edit(client):
    unit, product, customer = await _setup_basic(client)
    await _create_salesperson_and_login(client)
    created = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    assert created.status_code == 201
    invoice = created.json()["data"]
    edited = await client.patch(
        f"{INVOICES_ENDPOINT}/{invoice['id']}", json={"notes": "sp edit", "expected_row_version": invoice["row_version"]}
    )
    assert edited.status_code == 200


# --- Audit / accounting / GST ---


async def test_audit_and_integration_boundaries(client, db_session):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    created = await client.post(
        INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem()
    )
    invoice = created.json()["data"]
    await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())

    from app.models.audit_log import AuditLog

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_type == "sales_invoice", AuditLog.entity_id == uuid.UUID(invoice["id"]))
    )
    actions = {e.action for e in result.scalars().all()}
    assert "SALES_INVOICE_CREATED" in actions
    assert "SALES_INVOICE_POSTED" in actions
    assert "ACCOUNTING_POSTED" in actions
    assert "GST_TRANSACTION_CREATED" in actions


# --- List / search / filter ---


async def test_list_invoices_search_and_filter(client):
    unit, product, customer = await _setup_basic(client)
    await client.post(INVOICES_ENDPOINT, json=_direct_invoice_payload(customer["id"], product["id"], unit["id"]), headers=_idem())

    listed = await client.get(INVOICES_ENDPOINT, params={"search": customer["name"]})
    assert listed.status_code == 200
    assert listed.json()["pagination"]["total_items"] == 1

    filtered = await client.get(INVOICES_ENDPOINT, params={"status": "DRAFT"})
    assert filtered.json()["pagination"]["total_items"] == 1

    filtered_type = await client.get(INVOICES_ENDPOINT, params={"invoice_type": "DIRECT_SALES_INVOICE"})
    assert filtered_type.json()["pagination"]["total_items"] == 1

    filtered_none = await client.get(INVOICES_ENDPOINT, params={"status": "POSTED"})
    assert filtered_none.json()["pagination"]["total_items"] == 0
