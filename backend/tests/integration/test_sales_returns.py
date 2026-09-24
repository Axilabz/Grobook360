"""PROMPT-016 test catalogue for /api/v1/sales/returns and the Sales
Invoice return-eligibility endpoint.

Follows test_sales_invoices.py's structure and helper style. Covers
§41's 24 core test cases plus the mandatory §42 stock test, §43 multiple-
return test, and §44 concurrency test.
"""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

RETURNS_ENDPOINT = "/api/v1/sales/returns"
INVOICES_ENDPOINT = "/api/v1/sales/invoices"
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
    return f"sr-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "Sales Return Test Co",
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


async def _create_posted_direct_invoice(client, customer: dict, product: dict, unit: dict, quantity: str = "100") -> dict:
    payload = {
        "customer_id": customer["id"],
        "lines": [{"product_id": product["id"], "quantity": quantity, "uom_id": unit["id"], "unit_price": "100"}],
    }
    created = await client.post(INVOICES_ENDPOINT, json=payload, headers=_idem())
    assert created.status_code == 201
    invoice = created.json()["data"]
    posted = await client.post(
        f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem()
    )
    assert posted.status_code == 200
    return posted.json()["data"]


async def _get_return_eligibility(client, invoice_id: str) -> dict:
    response = await client.get(f"{INVOICES_ENDPOINT}/{invoice_id}/return-eligibility")
    assert response.status_code == 200
    return response.json()["data"]


def _return_payload(invoice_line_id: str, quantity: str, **overrides) -> dict:
    payload = {
        "source_invoice_id": overrides.pop("source_invoice_id", None),
        "return_reason": "DAMAGED",
        "lines": [{"source_invoice_line_id": invoice_line_id, "quantity": quantity}],
    }
    payload.update(overrides)
    return payload


async def _create_return(client, invoice: dict, quantity: str, **overrides) -> dict:
    line_id = invoice["lines"][0]["id"]
    payload = _return_payload(line_id, quantity, source_invoice_id=invoice["id"], **overrides)
    return await client.post(RETURNS_ENDPOINT, json=payload, headers=_idem())


# --- Create: from Sales Invoice ---


async def test_create_valid_draft_return(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    response = await _create_return(client, invoice, "5")
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["return_number"].startswith("SR-")
    assert data["source_invoice_id"] == invoice["id"]
    assert len(data["lines"]) == 1
    assert data["return_reason"] == "DAMAGED"

    # DRAFT: no stock impact yet
    assert await _available_quantity(client, product["id"]) == "80.000"


async def test_create_return_invalid_invoice(client):
    unit, product, customer = await _setup_basic(client)
    payload = _return_payload(str(uuid.uuid4()), "5", source_invoice_id=str(uuid.uuid4()))
    response = await client.post(RETURNS_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SI-001"


async def test_create_return_invoice_from_another_tenant(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    await _signup_and_login_owner(client)  # switch to tenant B
    response = await _create_return(client, invoice, "5")
    assert response.status_code == 404


async def test_create_return_invoice_not_eligible_draft(client):
    unit, product, customer = await _setup_basic(client)
    payload = {
        "customer_id": customer["id"],
        "lines": [{"product_id": product["id"], "quantity": "20", "uom_id": unit["id"], "unit_price": "100"}],
    }
    created = await client.post(INVOICES_ENDPOINT, json=payload, headers=_idem())
    draft_invoice = created.json()["data"]  # never posted

    response = await client.get(f"{INVOICES_ENDPOINT}/{draft_invoice['id']}/return-eligibility")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SR-007"


async def test_create_return_invalid_quantity(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    response = await _create_return(client, invoice, "0")
    assert response.status_code == 422


async def test_create_return_quantity_greater_than_returnable(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    response = await _create_return(client, invoice, "25")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SR-004"


async def test_invalid_return_reason(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    response = await _create_return(client, invoice, "5", return_reason="NOT_A_REAL_REASON")
    assert response.status_code == 422


async def test_other_reason_requires_description(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    response = await _create_return(client, invoice, "5", return_reason="OTHER")
    assert response.status_code == 422

    response_ok = await _create_return(
        client, invoice, "5", return_reason="OTHER", reason_description="Customer changed mind"
    )
    assert response_ok.status_code == 201


# --- Return eligibility ---


async def test_return_eligibility_reflects_invoice(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    eligibility = await _get_return_eligibility(client, invoice["id"])
    line = eligibility["lines"][0]
    assert line["original_quantity"] == "20.000"
    assert line["previously_returned_quantity"] == "0.000"
    assert line["returnable_quantity"] == "20.000"


# --- Partial / full return ---


async def test_partial_return_supported(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    response = await _create_return(client, invoice, "8")
    assert response.status_code == 201

    eligibility = await _get_return_eligibility(client, invoice["id"])
    # DRAFT return does not affect returned_quantity yet — only CONFIRMED does.
    assert eligibility["lines"][0]["returnable_quantity"] == "20.000"


async def test_full_return_supported(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    response = await _create_return(client, invoice, "20")
    assert response.status_code == 201


# --- §42 Mandatory stock test ---


async def test_mandatory_stock_scenario(client, db_session):
    """§42 verbatim: stock 40 after the original invoice's own stock-out
    (seeded at 140, invoiced 100), customer returns 20 -> stock increases
    to exactly 60 with ONE Stock IN movement, no duplicate."""
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "140")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "100")
    assert await _available_quantity(client, product["id"]) == "40.000"

    created = await _create_return(client, invoice, "20")
    assert created.status_code == 201
    sales_return = created.json()["data"]

    confirmed = await client.post(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}/confirm",
        json={"expected_row_version": sales_return["row_version"]},
        headers=_idem(),
    )
    assert confirmed.status_code == 200
    confirmed_data = confirmed.json()["data"]
    assert confirmed_data["status"] == "CONFIRMED"
    assert confirmed_data["accounting_posting_reference"] is not None
    assert confirmed_data["gst_transaction_reference"] is not None

    assert await _available_quantity(client, product["id"]) == "60.000"

    from app.models.stock_ledger_entry import StockLedgerEntry

    result = await db_session.execute(
        select(StockLedgerEntry).where(
            StockLedgerEntry.product_id == uuid.UUID(product["id"]), StockLedgerEntry.movement_type == "STOCK_IN"
        )
    )
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].quantity == Decimal("20.000")


# --- §43 Mandatory multiple-return test ---


async def test_mandatory_multiple_return_scenario(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "100")

    async def _return_and_confirm(quantity: str):
        created = await _create_return(client, invoice, quantity)
        assert created.status_code == 201
        sales_return = created.json()["data"]
        confirmed = await client.post(
            f"{RETURNS_ENDPOINT}/{sales_return['id']}/confirm",
            json={"expected_row_version": sales_return["row_version"]},
            headers=_idem(),
        )
        assert confirmed.status_code == 200
        return confirmed.json()["data"]

    await _return_and_confirm("20")
    eligibility = await _get_return_eligibility(client, invoice["id"])
    assert eligibility["lines"][0]["returnable_quantity"] == "80.000"

    await _return_and_confirm("30")
    eligibility = await _get_return_eligibility(client, invoice["id"])
    assert eligibility["lines"][0]["returnable_quantity"] == "50.000"

    await _return_and_confirm("50")
    eligibility = await _get_return_eligibility(client, invoice["id"])
    assert eligibility["lines"][0]["returnable_quantity"] == "0.000"

    # Further return of even 1 unit must fail.
    response = await _create_return(client, invoice, "1")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SR-004"


# --- Duplicate / idempotent confirmation ---


async def test_duplicate_confirmation_rejected(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_return(client, invoice, "5")
    sales_return = created.json()["data"]

    first = await client.post(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}/confirm", json={"expected_row_version": sales_return["row_version"]}, headers=_idem()
    )
    assert first.status_code == 200
    confirmed = first.json()["data"]

    second = await client.post(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}/confirm", json={"expected_row_version": confirmed["row_version"]}, headers=_idem()
    )
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "SR-002"


async def test_idempotent_confirm_retry(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_return(client, invoice, "5")
    sales_return = created.json()["data"]
    key = str(uuid.uuid4())

    first = await client.post(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}/confirm",
        json={"expected_row_version": sales_return["row_version"]},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200
    second = await client.post(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}/confirm",
        json={"expected_row_version": sales_return["row_version"]},
        headers={"Idempotency-Key": key},
    )
    assert second.status_code == 200
    assert second.json()["data"] == first.json()["data"]
    assert await _available_quantity(client, product["id"]) == "85.000"  # only ONE stock-IN applied (80 + 5)


# --- §44 Mandatory concurrency test ---


async def test_mandatory_concurrent_return_prevention(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "100")

    # Previously returned = 60, remaining = 40.
    first = await _create_return(client, invoice, "60")
    first_return = first.json()["data"]
    await client.post(
        f"{RETURNS_ENDPOINT}/{first_return['id']}/confirm", json={"expected_row_version": first_return["row_version"]}, headers=_idem()
    )

    return_a = (await _create_return(client, invoice, "30")).json()["data"]
    return_b = (await _create_return(client, invoice, "20")).json()["data"]

    async def _confirm(ret):
        return await client.post(
            f"{RETURNS_ENDPOINT}/{ret['id']}/confirm", json={"expected_row_version": ret["row_version"]}, headers=_idem()
        )

    results = await asyncio.gather(_confirm(return_a), _confirm(return_b))
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 422] or statuses == [200, 412]

    final_eligibility = await _get_return_eligibility(client, invoice["id"])
    total_returned = Decimal("100") - Decimal(final_eligibility["lines"][0]["returnable_quantity"])
    assert total_returned <= Decimal("100")
    assert total_returned in (Decimal("90"), Decimal("80"))  # 60 + (30 or 20), never both


# --- Immutability / cancellation ---


async def test_confirmed_return_immutable(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_return(client, invoice, "5")
    sales_return = created.json()["data"]
    confirmed = await client.post(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}/confirm", json={"expected_row_version": sales_return["row_version"]}, headers=_idem()
    )
    confirmed_data = confirmed.json()["data"]

    response = await client.patch(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}", json={"notes": "x", "expected_row_version": confirmed_data["row_version"]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SR-002"


async def test_edit_draft_return(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_return(client, invoice, "5")
    sales_return = created.json()["data"]

    response = await client.patch(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}", json={"notes": "updated", "expected_row_version": sales_return["row_version"]}
    )
    assert response.status_code == 200
    assert response.json()["data"]["notes"] == "updated"


async def test_cancel_draft_return(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_return(client, invoice, "5")
    sales_return = created.json()["data"]

    response = await client.post(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}/cancel", json={"expected_row_version": sales_return["row_version"]}
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"


async def test_cannot_cancel_confirmed_return(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_return(client, invoice, "5")
    sales_return = created.json()["data"]
    confirmed = await client.post(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}/confirm", json={"expected_row_version": sales_return["row_version"]}, headers=_idem()
    )
    confirmed_data = confirmed.json()["data"]

    response = await client.post(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}/cancel", json={"expected_row_version": confirmed_data["row_version"]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SR-002"


# --- Row-version conflict ---


async def test_row_version_conflict(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_return(client, invoice, "5")
    sales_return = created.json()["data"]

    first = await client.patch(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}", json={"notes": "first", "expected_row_version": sales_return["row_version"]}
    )
    assert first.status_code == 200
    stale = await client.patch(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}", json={"notes": "stale", "expected_row_version": sales_return["row_version"]}
    )
    assert stale.status_code == 412


# --- Tenant isolation / permissions ---


async def test_tenant_isolation(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_return(client, invoice, "5")
    return_id = created.json()["data"]["id"]

    await _signup_and_login_owner(client)  # switch to tenant B
    response = await client.get(f"{RETURNS_ENDPOINT}/{return_id}")
    assert response.status_code == 404


async def test_salesperson_cannot_confirm(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_return(client, invoice, "5")
    sales_return = created.json()["data"]

    await _create_salesperson_and_login(client)
    response = await client.post(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}/confirm", json={"expected_row_version": sales_return["row_version"]}, headers=_idem()
    )
    assert response.status_code == 403


async def test_salesperson_can_create_and_edit(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    await _create_salesperson_and_login(client)
    created = await _create_return(client, invoice, "5")
    assert created.status_code == 201
    sales_return = created.json()["data"]
    edited = await client.patch(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}", json={"notes": "sp edit", "expected_row_version": sales_return["row_version"]}
    )
    assert edited.status_code == 200


# --- Audit ---


async def test_audit_generation(client, db_session):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_return(client, invoice, "5")
    sales_return = created.json()["data"]
    await client.post(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}/confirm", json={"expected_row_version": sales_return["row_version"]}, headers=_idem()
    )

    from app.models.audit_log import AuditLog

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_type == "sales_return", AuditLog.entity_id == uuid.UUID(sales_return["id"]))
    )
    actions = {e.action for e in result.scalars().all()}
    assert "SALES_RETURN_CREATED" in actions
    assert "SALES_RETURN_CONFIRMED" in actions
    assert "ACCOUNTING_POSTED" in actions
    assert "GST_TRANSACTION_CREATED" in actions


# --- List / search / filter ---


async def test_list_returns_search_and_filter(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    await _create_return(client, invoice, "5")

    listed = await client.get(RETURNS_ENDPOINT, params={"search": customer["name"]})
    assert listed.status_code == 200
    assert listed.json()["pagination"]["total_items"] == 1

    filtered = await client.get(RETURNS_ENDPOINT, params={"status": "DRAFT"})
    assert filtered.json()["pagination"]["total_items"] == 1

    filtered_reason = await client.get(RETURNS_ENDPOINT, params={"return_reason": "DAMAGED"})
    assert filtered_reason.json()["pagination"]["total_items"] == 1

    filtered_none = await client.get(RETURNS_ENDPOINT, params={"status": "CONFIRMED"})
    assert filtered_none.json()["pagination"]["total_items"] == 0
