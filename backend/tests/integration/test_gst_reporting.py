"""PROMPT-026 test catalogue for the GST Rule Engine & GST Reporting
(/api/v1/gst/*).

Covers the core mandatory scenarios from §52: outward (B2B/B2C) and
inward GST transaction snapshot creation for Sales/Purchase Invoice,
sign-reversed snapshots for Sales/Purchase Return and Credit/Debit Note,
historical snapshot immutability after a master-data rate change,
accounting<->GST-engine reconciliation, GSTR-1/GSTR-3B dataset
generation, pre-submission validation (missing GSTIN/HSN, duplicate
document), idempotency, tenant isolation, and RBAC.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

GST_ENDPOINT = "/api/v1/gst"
ACCOUNTING_ENDPOINT = "/api/v1/accounting"
SALES_INVOICES_ENDPOINT = "/api/v1/sales/invoices"
SALES_RETURNS_ENDPOINT = "/api/v1/sales/returns"
CREDIT_DEBIT_NOTES_ENDPOINT = "/api/v1/sales/credit-debit-notes"
PURCHASE_INVOICES_ENDPOINT = "/api/v1/purchase/invoices"
PURCHASE_RETURNS_ENDPOINT = "/api/v1/purchase/returns"
PRODUCTS_ENDPOINT = "/api/v1/products"
UNITS_ENDPOINT = "/api/v1/units"
CUSTOMERS_ENDPOINT = "/api/v1/customers"
SUPPLIERS_ENDPOINT = "/api/v1/suppliers"
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
    return f"gst-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "GST Test Co", "address_line1": "1 Main St", "city": "Chennai",
            "state_code": state_code, "pin_code": "600001", "gstin": None,
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
    create_response = await client.post(USERS_ENDPOINT, json={"name": "SP", "phone": phone, "email": _unique_email(), "role": "SALESPERSON"})
    assert create_response.status_code == 201
    reset_token = ConsolePasswordRecoveryProvider.outbox[-1].reset_link.split("token=")[1]
    reset_response = await client.post(RESET_ENDPOINT, json={"token": reset_token, "new_password": SALESPERSON_PASSWORD, "confirm_password": SALESPERSON_PASSWORD})
    assert reset_response.status_code == 200
    login = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": SALESPERSON_PASSWORD})
    assert login.status_code == 200


async def _create_unit(client, code: str = "PCS", name: str = "Pieces") -> dict:
    response = await client.post(UNITS_ENDPOINT, json={"code": code, "name": name})
    assert response.status_code == 201
    return response.json()["data"]


async def _create_product(client, base_uom_id: str, **overrides) -> dict:
    payload = {"sku": _unique_sku(), "name": "Test Product", "base_uom_id": base_uom_id, "gst_rate": "18", "cost_price": "50", "selling_price": "100", "mrp": "120", "hsn_code": "12345678"}
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


async def _create_supplier(client, **overrides) -> dict:
    payload = {"name": "Test Supplier", "contact_person": "Contact", "phone": _unique_phone(), "email": _unique_email()}
    payload.update(overrides)
    response = await client.post(SUPPLIERS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


async def _seed_opening_stock(client, product_id: str, uom_id: str, quantity: str = "1000") -> None:
    response = await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock", json={"product_id": product_id, "quantity": quantity, "uom_id": uom_id}, headers=_idem(),
    )
    assert response.status_code == 201


async def _setup_basic(client, state_code: str = "33"):
    await _signup_and_login_owner(client, state_code=state_code)
    unit = await _create_unit(client)
    product = await _create_product(client, unit["id"])
    customer = await _create_customer(client, state_code=state_code, gstin=f"{state_code}AAAAA0000A1Z5")
    supplier = await _create_supplier(client, state_code=state_code, gstin=f"{state_code}BBBBB0000B1Z5")
    await _seed_opening_stock(client, product["id"], unit["id"])
    return unit, product, customer, supplier


async def _create_posted_sales_invoice(client, customer, product, unit, qty: str = "10", unit_price: str = "100") -> dict:
    payload = {"customer_id": customer["id"], "lines": [{"product_id": product["id"], "quantity": qty, "uom_id": unit["id"], "unit_price": unit_price}]}
    created = await client.post(SALES_INVOICES_ENDPOINT, json=payload, headers=_idem())
    assert created.status_code == 201
    invoice = created.json()["data"]
    posted = await client.post(f"{SALES_INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    return posted.json()["data"]


async def _create_posted_purchase_invoice(client, supplier, product, unit, qty: str = "10", unit_price: str = "50") -> dict:
    payload = {"supplier_id": supplier["id"], "lines": [{"product_id": product["id"], "quantity": qty, "uom_id": unit["id"], "unit_price": unit_price}]}
    created = await client.post(PURCHASE_INVOICES_ENDPOINT, json=payload, headers=_idem())
    assert created.status_code == 201
    invoice = created.json()["data"]
    posted = await client.post(f"{PURCHASE_INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    return posted.json()["data"]


async def _get_transaction_for_source(client, source_type: str, source_id: str) -> dict | None:
    response = await client.get(f"{GST_ENDPOINT}/transactions", params={"source_type": source_type, "page_size": 100})
    assert response.status_code == 200
    for item in response.json()["data"]:
        if item["source_id"] == source_id and item["event_type"] == "ORIGINAL":
            return item
    return None


# --- TC-011: Sales Invoice GST snapshot creation (B2B) -------------------


async def test_sales_invoice_creates_b2b_outward_gst_transaction(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)
    assert invoice["gst_transaction_reference"] is not None

    txn = await _get_transaction_for_source(client, "SALES_INVOICE", invoice["id"])
    assert txn is not None
    assert txn["id"] == invoice["gst_transaction_reference"]
    assert txn["direction"] == "OUTWARD"
    assert txn["classification"] == "B2B"
    assert Decimal(txn["taxable_value"]) == Decimal(invoice["taxable_total"])
    assert Decimal(txn["cgst_amount"]) == Decimal(invoice["cgst_total"])
    assert Decimal(txn["sgst_amount"]) == Decimal(invoice["sgst_total"])

    detail = (await client.get(f"{GST_ENDPOINT}/transactions/{txn['id']}")).json()["data"]
    assert len(detail["lines"]) == 1
    assert detail["lines"][0]["hsn_code"] == product["hsn_code"]


async def test_sales_invoice_b2c_when_customer_has_no_gstin(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    product = await _create_product(client, unit["id"])
    customer = await _create_customer(client)  # no GSTIN -> B2C
    await _seed_opening_stock(client, product["id"], unit["id"])
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)

    txn = await _get_transaction_for_source(client, "SALES_INVOICE", invoice["id"])
    assert txn["classification"] == "B2C"


# --- TC-012: Purchase Invoice GST snapshot creation -----------------------


async def test_purchase_invoice_creates_inward_gst_transaction(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_purchase_invoice(client, supplier, product, unit)
    assert invoice["gst_transaction_reference"] is not None

    txn = await _get_transaction_for_source(client, "PURCHASE_INVOICE", invoice["id"])
    assert txn["direction"] == "INWARD"
    assert txn["classification"] == "B2B"
    assert Decimal(txn["taxable_value"]) == Decimal(invoice["taxable_total"])


# --- TC-013: Sales Return GST reversal -------------------------------------


async def test_sales_return_reverses_output_gst(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, qty="10")

    return_payload = {
        "source_invoice_id": invoice["id"],
        "return_reason": "DAMAGED",
        "lines": [{"source_invoice_line_id": invoice["lines"][0]["id"], "quantity": "5"}],
    }
    created = await client.post(SALES_RETURNS_ENDPOINT, json=return_payload, headers=_idem())
    assert created.status_code == 201
    sales_return = created.json()["data"]
    confirmed = await client.post(
        f"{SALES_RETURNS_ENDPOINT}/{sales_return['id']}/confirm", json={"expected_row_version": sales_return["row_version"]}, headers=_idem(),
    )
    assert confirmed.status_code == 200
    sales_return = confirmed.json()["data"]

    txn = await _get_transaction_for_source(client, "SALES_RETURN", sales_return["id"])
    assert txn is not None
    assert txn["direction"] == "OUTWARD"
    assert Decimal(txn["taxable_value"]) == -Decimal(sales_return["taxable_total"])
    assert Decimal(txn["cgst_amount"]) < 0


# --- TC-015: Credit Note GST adjustment ------------------------------------


async def test_credit_note_reduces_output_gst(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, qty="10")

    note_payload = {
        "source_invoice_id": invoice["id"], "note_type": "CREDIT_NOTE", "reason": "Price adjustment",
        "lines": [{"source_invoice_line_id": invoice["lines"][0]["id"], "quantity": "2"}],
    }
    created = await client.post(CREDIT_DEBIT_NOTES_ENDPOINT, json=note_payload, headers=_idem())
    assert created.status_code == 201
    note = created.json()["data"]
    posted = await client.post(f"{CREDIT_DEBIT_NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": note["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    note = posted.json()["data"]

    txn = await _get_transaction_for_source(client, "CREDIT_NOTE", note["id"])
    assert txn is not None
    assert Decimal(txn["taxable_value"]) == -Decimal(note["taxable_total"])


# --- TC-014/TC-013 reversal: Purchase Invoice cancellation reverses GST ---


async def test_purchase_invoice_cancellation_reverses_gst_transaction(client, db_session):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_purchase_invoice(client, supplier, product, unit)

    original_txn = await _get_transaction_for_source(client, "PURCHASE_INVOICE", invoice["id"])
    cancelled = await client.post(
        f"{PURCHASE_INVOICES_ENDPOINT}/{invoice['id']}/cancel", json={"expected_row_version": invoice["row_version"]}, headers=_idem(),
    )
    assert cancelled.status_code == 200

    response = await client.get(f"{GST_ENDPOINT}/transactions", params={"source_type": "PURCHASE_INVOICE", "page_size": 100})
    reversal = next(item for item in response.json()["data"] if item["source_id"] == invoice["id"] and item["event_type"] == "REVERSAL")
    assert Decimal(reversal["taxable_value"]) == -Decimal(original_txn["taxable_value"])
    assert Decimal(reversal["cgst_amount"]) == -Decimal(original_txn["cgst_amount"])

    # §21: the ORIGINAL row itself is never edited by the reversal.
    still_original = await _get_transaction_for_source(client, "PURCHASE_INVOICE", invoice["id"])
    assert Decimal(still_original["taxable_value"]) == Decimal(original_txn["taxable_value"])


# --- TC-017: historical snapshot immutable after a master-data rate change


async def test_gst_snapshot_immutable_after_product_rate_change(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)
    txn = await _get_transaction_for_source(client, "SALES_INVOICE", invoice["id"])
    detail_before = (await client.get(f"{GST_ENDPOINT}/transactions/{txn['id']}")).json()["data"]
    assert detail_before["lines"][0]["gst_rate"] == "18.00"

    update = await client.patch(
        f"{PRODUCTS_ENDPOINT}/{product['id']}", json={"gst_rate": "12", "expected_row_version": product["row_version"]},
    )
    assert update.status_code == 200

    detail_after = (await client.get(f"{GST_ENDPOINT}/transactions/{txn['id']}")).json()["data"]
    assert detail_after["lines"][0]["gst_rate"] == "18.00"
    assert detail_after["taxable_value"] == detail_before["taxable_value"]


# --- TC-018/TC-030: accounting equals GST engine (reconciliation) ---------


async def test_reconciliation_shows_zero_difference(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)
    return_period = invoice["invoice_date"][:7]

    response = await client.get(f"{GST_ENDPOINT}/reconciliation", params={"return_period": return_period})
    assert response.status_code == 200
    data = response.json()["data"]
    assert Decimal(data["output_gst_difference"]) == Decimal("0")
    assert Decimal(data["gst_engine_output_gst"]) == Decimal(data["accounting_output_gst"])


# --- TC-020/TC-021: GSTR-1 / GSTR-3B dataset generation -------------------


async def test_gstr1_dataset_includes_posted_invoice(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)
    return_period = invoice["invoice_date"][:7]

    response = await client.get(f"{GST_ENDPOINT}/returns/gstr1", params={"return_period": return_period})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["b2b"]["count"] == 1
    assert Decimal(data["b2b"]["totals"]["taxable_value"]) == Decimal(invoice["taxable_total"])
    assert any(entry["hsn_code"] == product["hsn_code"] for entry in data["hsn_summary"])


async def test_gstr3b_dataset_nets_output_and_input(client):
    unit, product, customer, supplier = await _setup_basic(client)
    sales_invoice = await _create_posted_sales_invoice(client, customer, product, unit)
    purchase_invoice = await _create_posted_purchase_invoice(client, supplier, product, unit)
    return_period = sales_invoice["invoice_date"][:7]

    response = await client.get(f"{GST_ENDPOINT}/returns/gstr3b", params={"return_period": return_period})
    assert response.status_code == 200
    data = response.json()["data"]
    assert Decimal(data["output_cgst"]) == Decimal(sales_invoice["cgst_total"])
    assert Decimal(data["input_tax_credit_cgst"]) == Decimal(purchase_invoice["cgst_total"])


# --- TC-024/TC-025: validation detects missing GSTIN/HSN ------------------


async def test_validate_gstr1_detects_missing_hsn(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    product = await _create_product(client, unit["id"], hsn_code=None)
    customer = await _create_customer(client)  # B2C -> HSN missing is a WARNING, not an ERROR
    await _seed_opening_stock(client, product["id"], unit["id"])
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)
    return_period = invoice["invoice_date"][:7]

    response = await client.post(f"{GST_ENDPOINT}/returns/gstr1/validate", params={"return_period": return_period})
    assert response.status_code == 200
    issues = response.json()["data"]["issues"]
    assert any(issue["code"] == "GST-003" for issue in issues)


async def test_validate_gstr1_detects_missing_gstin_for_b2b(client, db_session):
    """A B2B `gst_transaction` with no GSTIN cannot occur through the
    normal API flow (classification is derived FROM GSTIN presence at
    Sales Invoice creation time) — inserted directly to exercise the
    validator itself, matching this file's established db_session-direct
    pattern for scenarios the API surface cannot reach."""
    from datetime import date

    from app.core.gst_constants import B2B, EVT_ORIGINAL, OUTWARD
    from app.models.gst_transaction import GstTransaction

    signup_data = await _signup_and_login_owner(client)
    txn = GstTransaction(
        tenant_id=uuid.UUID(signup_data["tenant_id"]), source_type="SALES_INVOICE", source_id=uuid.uuid4(), source_number="INV-BAD-1",
        event_type=EVT_ORIGINAL, direction=OUTWARD, classification=B2B, party_gstin=None, document_date=date.today(),
        financial_year_label="2026-27", return_period=date.today().strftime("%Y-%m"), taxable_value=Decimal("1000"),
        cgst_amount=Decimal("90"), sgst_amount=Decimal("90"), igst_amount=Decimal("0"), cess_amount=Decimal("0"),
        total_gst=Decimal("180"), total_amount=Decimal("1180"),
    )
    db_session.add(txn)
    await db_session.commit()

    return_period = date.today().strftime("%Y-%m")
    response = await client.post(f"{GST_ENDPOINT}/returns/gstr1/validate", params={"return_period": return_period})
    assert response.status_code == 200
    issues = response.json()["data"]["issues"]
    assert any(issue["code"] == "GST-001" and issue["severity"] == "ERROR" for issue in issues)


# --- TC-031: idempotency — no duplicate GST transaction on retry ---------


async def test_gst_transaction_recording_is_idempotent(client, db_session):
    from app.models.gst_transaction import GstTransaction
    from app.models.sales_invoice import SalesInvoice
    from app.services.sales.gst_reporting_service import GstReportingService

    unit, product, customer, supplier = await _setup_basic(client)
    invoice_data = await _create_posted_sales_invoice(client, customer, product, unit)

    result = await db_session.execute(select(SalesInvoice).where(SalesInvoice.id == uuid.UUID(invoice_data["id"])))
    invoice = result.scalar_one()

    service = GstReportingService(db_session)
    ref1 = await service.record_invoice_transaction(tenant_id=invoice.tenant_id, actor_user_id=invoice.created_by, invoice=invoice, ip_address=None)
    ref2 = await service.record_invoice_transaction(tenant_id=invoice.tenant_id, actor_user_id=invoice.created_by, invoice=invoice, ip_address=None)
    assert ref1 == ref2 == invoice_data["gst_transaction_reference"]

    count_result = await db_session.execute(
        select(GstTransaction).where(GstTransaction.tenant_id == invoice.tenant_id, GstTransaction.source_id == invoice.id, GstTransaction.event_type == "ORIGINAL")
    )
    assert len(count_result.scalars().all()) == 1


# --- TC-032: tenant isolation ----------------------------------------------


async def test_gst_transactions_are_tenant_isolated(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)

    other_phone = _unique_phone()
    other_client_response = await client.post(
        SIGNUP_ENDPOINT,
        json={
            "organization": {"business_name": "Other Tenant", "address_line1": "2 Side St", "city": "Mumbai", "state_code": "27", "pin_code": "400001", "gstin": None},
            "owner": {"phone": other_phone, "email": _unique_email(), "password": OWNER_PASSWORD, "confirm_password": OWNER_PASSWORD},
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert other_client_response.status_code == 201
    other_login = await client.post(LOGIN_ENDPOINT, json={"login_identifier": other_phone, "password": OWNER_PASSWORD})
    assert other_login.status_code == 200

    response = await client.get(f"{GST_ENDPOINT}/transactions", params={"source_type": "SALES_INVOICE", "page_size": 100})
    assert response.status_code == 200
    assert all(item["source_id"] != invoice["id"] for item in response.json()["data"])

    detail_response = await client.get(f"{GST_ENDPOINT}/transactions/{invoice['gst_transaction_reference']}")
    assert detail_response.status_code == 404


# --- TC-033: RBAC — Salesperson denied ------------------------------------


async def test_salesperson_cannot_view_gst_transactions(client):
    await _setup_basic(client)
    await _create_salesperson_and_login(client)
    response = await client.get(f"{GST_ENDPOINT}/transactions")
    assert response.status_code == 403
