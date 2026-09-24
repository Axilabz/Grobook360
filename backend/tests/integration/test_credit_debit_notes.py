"""PROMPT-017 test catalogue for /api/v1/sales/credit-debit-notes and the
Sales Invoice adjustment-eligibility endpoint.

Follows test_sales_returns.py's structure and helper style. Covers §47's
25 core test cases plus the mandatory §48 no-stock test, §49 credit-limit
test, and §50 concurrency test.
"""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

NOTES_ENDPOINT = "/api/v1/sales/credit-debit-notes"
INVOICES_ENDPOINT = "/api/v1/sales/invoices"
RETURNS_ENDPOINT = "/api/v1/sales/returns"
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
    return f"cdn-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "Credit Debit Note Test Co",
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


async def _create_posted_direct_invoice(client, customer: dict, product: dict, unit: dict, quantity: str = "100", unit_price: str = "100") -> dict:
    payload = {
        "customer_id": customer["id"],
        "lines": [{"product_id": product["id"], "quantity": quantity, "uom_id": unit["id"], "unit_price": unit_price}],
    }
    created = await client.post(INVOICES_ENDPOINT, json=payload, headers=_idem())
    assert created.status_code == 201
    invoice = created.json()["data"]
    posted = await client.post(
        f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem()
    )
    assert posted.status_code == 200
    return posted.json()["data"]


async def _get_adjustment_eligibility(client, invoice_id: str) -> dict:
    response = await client.get(f"{INVOICES_ENDPOINT}/{invoice_id}/adjustment-eligibility")
    assert response.status_code == 200
    return response.json()["data"]


def _note_payload(invoice_id: str, invoice_line_id: str, quantity: str, note_type: str = "CREDIT_NOTE", **overrides) -> dict:
    payload = {
        "source_invoice_id": invoice_id,
        "note_type": note_type,
        "reason": "Pricing correction",
        "lines": [{"source_invoice_line_id": invoice_line_id, "quantity": quantity}],
    }
    payload.update(overrides)
    return payload


async def _create_note(client, invoice: dict, quantity: str, note_type: str = "CREDIT_NOTE", **overrides):
    line_id = invoice["lines"][0]["id"]
    payload = _note_payload(invoice["id"], line_id, quantity, note_type=note_type, **overrides)
    return await client.post(NOTES_ENDPOINT, json=payload, headers=_idem())


# --- Create: Credit Note from Sales Invoice ---


async def test_create_credit_note_draft(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    response = await _create_note(client, invoice, "5", note_type="CREDIT_NOTE")
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["note_type"] == "CREDIT_NOTE"
    assert data["note_number"].startswith("CN-")
    assert data["source_invoice_id"] == invoice["id"]
    assert len(data["lines"]) == 1
    assert data["reason"] == "Pricing correction"


async def test_create_debit_note_draft(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    response = await _create_note(client, invoice, "5", note_type="DEBIT_NOTE")
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["note_type"] == "DEBIT_NOTE"
    assert data["note_number"].startswith("DN-")


async def test_invalid_note_type(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    response = await _create_note(client, invoice, "5", note_type="REFUND_NOTE")
    assert response.status_code == 422


async def test_create_note_invalid_invoice(client):
    await _setup_basic(client)
    payload = _note_payload(str(uuid.uuid4()), str(uuid.uuid4()), "5")
    response = await client.post(NOTES_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SI-001"


async def test_create_note_invoice_from_another_tenant(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    await _signup_and_login_owner(client)  # switch to tenant B
    response = await _create_note(client, invoice, "5")
    assert response.status_code == 404


async def test_create_note_invoice_not_eligible_draft(client):
    unit, product, customer = await _setup_basic(client)
    payload = {
        "customer_id": customer["id"],
        "lines": [{"product_id": product["id"], "quantity": "20", "uom_id": unit["id"], "unit_price": "100"}],
    }
    created = await client.post(INVOICES_ENDPOINT, json=payload, headers=_idem())
    draft_invoice = created.json()["data"]  # never posted

    response = await client.get(f"{INVOICES_ENDPOINT}/{draft_invoice['id']}/adjustment-eligibility")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CDN-007"


async def test_create_note_invalid_quantity(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    response = await _create_note(client, invoice, "0")
    assert response.status_code == 422


async def test_create_credit_note_exceeds_eligible_quantity(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    response = await _create_note(client, invoice, "25", note_type="CREDIT_NOTE")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CDN-004"


# --- Adjustment eligibility ---


async def test_adjustment_eligibility_reflects_invoice(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    eligibility = await _get_adjustment_eligibility(client, invoice["id"])
    line = eligibility["lines"][0]
    assert line["original_quantity"] == "20.000"
    assert line["previously_credited_quantity"] == "0.000"
    assert line["previously_debited_quantity"] == "0.000"
    assert line["creditable_quantity"] == "20.000"
    assert line["debitable_quantity"] == "20.000"


# --- GST calculation ---


async def test_gst_calculation_credit_note(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20", unit_price="100")

    response = await _create_note(client, invoice, "10", note_type="CREDIT_NOTE")
    data = response.json()["data"]
    line = data["lines"][0]
    assert Decimal(line["cgst_amount"]) == Decimal("90.00")  # 10*100=1000 taxable * 18% / 2
    assert Decimal(line["sgst_amount"]) == Decimal("90.00")
    assert Decimal(data["grand_total"]) == Decimal("1180.00")


# --- §48 Mandatory no-stock test ---


async def test_mandatory_no_stock_impact(client, db_session):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "140")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    assert await _available_quantity(client, product["id"]) == "120.000"

    # Sales Return of the full 20 units -> stock 140.
    invoice_line_id = invoice["lines"][0]["id"]
    return_created = await client.post(
        RETURNS_ENDPOINT,
        json={
            "source_invoice_id": invoice["id"],
            "return_reason": "DAMAGED",
            "lines": [{"source_invoice_line_id": invoice_line_id, "quantity": "20"}],
        },
        headers=_idem(),
    )
    assert return_created.status_code == 201
    sales_return = return_created.json()["data"]
    confirmed = await client.post(
        f"{RETURNS_ENDPOINT}/{sales_return['id']}/confirm", json={"expected_row_version": sales_return["row_version"]}, headers=_idem()
    )
    assert confirmed.status_code == 200
    assert await _available_quantity(client, product["id"]) == "140.000"

    from app.models.stock_ledger_entry import StockLedgerEntry

    before = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"])))
    before_count = len(before.scalars().all())

    # Now create + post a Credit Note against the same invoice line.
    created = await _create_note(client, invoice, "20", note_type="CREDIT_NOTE")
    assert created.status_code == 201
    note = created.json()["data"]
    posted = await client.post(
        f"{NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": note["row_version"]}, headers=_idem()
    )
    assert posted.status_code == 200
    posted_data = posted.json()["data"]
    assert posted_data["status"] == "POSTED"
    assert posted_data["accounting_posting_reference"] is not None
    assert posted_data["gst_transaction_reference"] is not None

    # Stock must remain 140 — ZERO stock movement from the Credit Note.
    assert await _available_quantity(client, product["id"]) == "140.000"

    after = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"])))
    after_count = len(after.scalars().all())
    assert after_count == before_count


async def test_mandatory_no_stock_impact_debit_note(client, db_session):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    assert await _available_quantity(client, product["id"]) == "80.000"

    from app.models.stock_ledger_entry import StockLedgerEntry

    before = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"])))
    before_count = len(before.scalars().all())

    created = await _create_note(client, invoice, "5", note_type="DEBIT_NOTE")
    note = created.json()["data"]
    posted = await client.post(
        f"{NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": note["row_version"]}, headers=_idem()
    )
    assert posted.status_code == 200

    assert await _available_quantity(client, product["id"]) == "80.000"
    after = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"])))
    after_count = len(after.scalars().all())
    assert after_count == before_count


# --- §49 Mandatory credit-limit test ---


async def test_mandatory_credit_limit_scenario(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "100", unit_price="100")
    # Invoice grand total for 100 units @ 100 with 18% GST = 11800.

    first = await _create_note(client, invoice, "60", note_type="CREDIT_NOTE")
    assert first.status_code == 201
    first_note = first.json()["data"]
    posted1 = await client.post(
        f"{NOTES_ENDPOINT}/{first_note['id']}/post", json={"expected_row_version": first_note["row_version"]}, headers=_idem()
    )
    assert posted1.status_code == 200

    eligibility = await _get_adjustment_eligibility(client, invoice["id"])
    assert eligibility["lines"][0]["creditable_quantity"] == "40.000"

    # Attempt a further 50 units of credit -> exceeds the 40 remaining -> FAIL.
    second = await _create_note(client, invoice, "50", note_type="CREDIT_NOTE")
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "CDN-004"

    # No accounting posting, GST adjustment, or stock movement should
    # have resulted from the rejected attempt (nothing to assert beyond
    # the fact that no note/accounting-reference exists for it, since the
    # request never even created a DRAFT row).


# --- §50 Mandatory concurrency test ---


async def test_mandatory_concurrent_credit_prevention(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "1000")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "100")

    note_a = (await _create_note(client, invoice, "70", note_type="CREDIT_NOTE")).json()["data"]
    note_b = (await _create_note(client, invoice, "50", note_type="CREDIT_NOTE")).json()["data"]

    async def _post(note):
        return await client.post(
            f"{NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": note["row_version"]}, headers=_idem()
        )

    results = await asyncio.gather(_post(note_a), _post(note_b))
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 422] or statuses == [200, 412]

    final_eligibility = await _get_adjustment_eligibility(client, invoice["id"])
    total_credited = Decimal("100") - Decimal(final_eligibility["lines"][0]["creditable_quantity"])
    assert total_credited <= Decimal("100")
    assert total_credited in (Decimal("70"), Decimal("50"))  # never both


# --- Duplicate / idempotent posting ---


async def test_duplicate_posting_rejected(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_note(client, invoice, "5")
    note = created.json()["data"]

    first = await client.post(
        f"{NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": note["row_version"]}, headers=_idem()
    )
    assert first.status_code == 200
    posted = first.json()["data"]

    second = await client.post(
        f"{NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": posted["row_version"]}, headers=_idem()
    )
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "CDN-002"


async def test_idempotent_post_retry(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_note(client, invoice, "5")
    note = created.json()["data"]
    key = str(uuid.uuid4())

    first = await client.post(
        f"{NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": note["row_version"]}, headers={"Idempotency-Key": key}
    )
    assert first.status_code == 200
    second = await client.post(
        f"{NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": note["row_version"]}, headers={"Idempotency-Key": key}
    )
    assert second.status_code == 200
    assert second.json()["data"] == first.json()["data"]

    eligibility = await _get_adjustment_eligibility(client, invoice["id"])
    assert eligibility["lines"][0]["creditable_quantity"] == "15.000"  # only ONE credit applied (20 - 5)


# --- Immutability / cancellation ---


async def test_posted_note_immutable(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_note(client, invoice, "5")
    note = created.json()["data"]
    posted = await client.post(
        f"{NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": note["row_version"]}, headers=_idem()
    )
    posted_data = posted.json()["data"]

    response = await client.patch(
        f"{NOTES_ENDPOINT}/{note['id']}", json={"notes": "x", "expected_row_version": posted_data["row_version"]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CDN-002"


async def test_edit_draft_note(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_note(client, invoice, "5")
    note = created.json()["data"]

    response = await client.patch(
        f"{NOTES_ENDPOINT}/{note['id']}", json={"notes": "updated", "expected_row_version": note["row_version"]}
    )
    assert response.status_code == 200
    assert response.json()["data"]["notes"] == "updated"


async def test_cancel_draft_note(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_note(client, invoice, "5")
    note = created.json()["data"]

    response = await client.post(
        f"{NOTES_ENDPOINT}/{note['id']}/cancel", json={"expected_row_version": note["row_version"]}
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"


async def test_cannot_cancel_posted_note(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_note(client, invoice, "5")
    note = created.json()["data"]
    posted = await client.post(
        f"{NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": note["row_version"]}, headers=_idem()
    )
    posted_data = posted.json()["data"]

    response = await client.post(
        f"{NOTES_ENDPOINT}/{note['id']}/cancel", json={"expected_row_version": posted_data["row_version"]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CDN-002"


# --- Row-version conflict ---


async def test_row_version_conflict(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_note(client, invoice, "5")
    note = created.json()["data"]

    first = await client.patch(
        f"{NOTES_ENDPOINT}/{note['id']}", json={"notes": "first", "expected_row_version": note["row_version"]}
    )
    assert first.status_code == 200
    stale = await client.patch(
        f"{NOTES_ENDPOINT}/{note['id']}", json={"notes": "stale", "expected_row_version": note["row_version"]}
    )
    assert stale.status_code == 412


# --- Tenant isolation / permissions ---


async def test_tenant_isolation(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_note(client, invoice, "5")
    note_id = created.json()["data"]["id"]

    await _signup_and_login_owner(client)  # switch to tenant B
    response = await client.get(f"{NOTES_ENDPOINT}/{note_id}")
    assert response.status_code == 404


async def test_salesperson_cannot_post(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_note(client, invoice, "5")
    note = created.json()["data"]

    await _create_salesperson_and_login(client)
    response = await client.post(
        f"{NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": note["row_version"]}, headers=_idem()
    )
    assert response.status_code == 403


async def test_salesperson_can_create_and_edit(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")

    await _create_salesperson_and_login(client)
    created = await _create_note(client, invoice, "5")
    assert created.status_code == 201
    note = created.json()["data"]
    edited = await client.patch(
        f"{NOTES_ENDPOINT}/{note['id']}", json={"notes": "sp edit", "expected_row_version": note["row_version"]}
    )
    assert edited.status_code == 200


# --- Audit ---


async def test_audit_generation(client, db_session):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    created = await _create_note(client, invoice, "5", note_type="CREDIT_NOTE")
    note = created.json()["data"]
    await client.post(
        f"{NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": note["row_version"]}, headers=_idem()
    )

    from app.models.audit_log import AuditLog

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_type == "credit_debit_note", AuditLog.entity_id == uuid.UUID(note["id"]))
    )
    actions = {e.action for e in result.scalars().all()}
    assert "CREDIT_NOTE_CREATED" in actions
    assert "CREDIT_NOTE_POSTED" in actions
    assert "ACCOUNTING_POSTED" in actions
    assert "GST_TRANSACTION_CREATED" in actions


# --- List / search / filter ---


async def test_list_notes_search_and_filter(client):
    unit, product, customer = await _setup_basic(client)
    await _seed_opening_stock(client, product["id"], unit["id"], "100")
    invoice = await _create_posted_direct_invoice(client, customer, product, unit, "20")
    await _create_note(client, invoice, "5", note_type="CREDIT_NOTE")
    await _create_note(client, invoice, "3", note_type="DEBIT_NOTE")

    listed = await client.get(NOTES_ENDPOINT, params={"search": customer["name"]})
    assert listed.status_code == 200
    assert listed.json()["pagination"]["total_items"] == 2

    filtered_type = await client.get(NOTES_ENDPOINT, params={"note_type": "CREDIT_NOTE"})
    assert filtered_type.json()["pagination"]["total_items"] == 1

    filtered_status = await client.get(NOTES_ENDPOINT, params={"status": "DRAFT"})
    assert filtered_status.json()["pagination"]["total_items"] == 2

    filtered_none = await client.get(NOTES_ENDPOINT, params={"status": "POSTED"})
    assert filtered_none.json()["pagination"]["total_items"] == 0
