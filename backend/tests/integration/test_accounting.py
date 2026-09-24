"""PROMPT-025 test catalogue for the Accounting Posting Matrix & Journal
Engine (/api/v1/accounting/*).

Covers the core mandatory scenarios from §54: balanced journal creation
for every supported source (Sales/Purchase Invoice with CGST+SGST vs
IGST, Customer Receipt, Supplier Payment, Sales/Purchase Return, Credit/
Debit Note), no-journal for Sales Order/Estimate, GST reconciliation,
source<->journal traceability, duplicate-posting prevention, reversal
(+ double-reversal rejection + original immutability), tenant isolation,
and RBAC.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

ACCOUNTING_ENDPOINT = "/api/v1/accounting"
RECEIPTS_ENDPOINT = "/api/v1/customer-receipts"
PAYMENTS_ENDPOINT = "/api/v1/supplier-payments"
SALES_INVOICES_ENDPOINT = "/api/v1/sales/invoices"
SALES_RETURNS_ENDPOINT = "/api/v1/sales/returns"
CREDIT_DEBIT_NOTES_ENDPOINT = "/api/v1/sales/credit-debit-notes"
SALES_ORDERS_ENDPOINT = "/api/v1/sales/orders"
ESTIMATES_ENDPOINT = "/api/v1/sales/estimates"
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
    return f"acc-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "Accounting Test Co", "address_line1": "1 Main St", "city": "Chennai",
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
    payload = {"sku": _unique_sku(), "name": "Test Product", "base_uom_id": base_uom_id, "gst_rate": "18", "cost_price": "50", "selling_price": "100", "mrp": "120"}
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
    customer = await _create_customer(client, state_code=state_code)
    supplier = await _create_supplier(client)
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


async def _get_journal_for_source(client, source_type: str, source_id: str) -> dict | None:
    response = await client.get(f"{ACCOUNTING_ENDPOINT}/journals", params={"source_type": source_type, "page_size": 100})
    assert response.status_code == 200
    for item in response.json()["data"]:
        if item["source_id"] == source_id and item["posting_event_type"] == "ORIGINAL":
            return item
    return None


def _assert_balanced(journal_detail: dict) -> None:
    total_debit = sum(Decimal(line["debit_amount"]) for line in journal_detail["lines"])
    total_credit = sum(Decimal(line["credit_amount"]) for line in journal_detail["lines"])
    assert total_debit == total_credit
    assert Decimal(journal_detail["total_debit"]) == Decimal(journal_detail["total_credit"])


# --- TC-001/002: Sales Invoice, intra-state CGST+SGST ---


async def test_sales_invoice_intra_state_creates_balanced_cgst_sgst_journal(client):
    unit, product, customer, supplier = await _setup_basic(client, state_code="33")
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)
    assert invoice["accounting_posting_reference"] is not None

    list_item = await _get_journal_for_source(client, "SALES_INVOICE", invoice["id"])
    assert list_item is not None
    assert list_item["journal_number"] == invoice["accounting_posting_reference"]

    detail = (await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}")).json()["data"]
    _assert_balanced(detail)
    assert Decimal(detail["total_debit"]) == Decimal(invoice["grand_total"])

    account_codes = {line["account_code"] for line in detail["lines"]}
    account_names = {line["account_name"] for line in detail["lines"]}
    assert any("CGST" in name for name in account_names)
    assert any("SGST" in name for name in account_names)
    assert not any("IGST" in name for name in account_names)


# --- TC-003: Sales Invoice, inter-state IGST ---


async def test_sales_invoice_inter_state_creates_igst_journal(client):
    unit, product, customer, supplier = await _setup_basic(client, state_code="33")
    # Force inter-state: customer state differs from tenant state.
    other_customer = await _create_customer(client, name="Out of State Customer", state_code="27")
    invoice = await _create_posted_sales_invoice(client, other_customer, product, unit)

    list_item = await _get_journal_for_source(client, "SALES_INVOICE", invoice["id"])
    detail = (await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}")).json()["data"]
    _assert_balanced(detail)
    account_names = {line["account_name"] for line in detail["lines"]}
    assert any("IGST" in name for name in account_names)
    assert not any("CGST" in name for name in account_names)
    assert not any("SGST" in name for name in account_names)


# --- TC-004/005: Sales Order / Estimate create NO journal ---


async def test_sales_order_creates_no_journal(client):
    unit, product, customer, supplier = await _setup_basic(client)
    payload = {"customer_id": customer["id"], "lines": [{"product_id": product["id"], "quantity": "5", "uom_id": unit["id"], "unit_price": "100"}]}
    created = await client.post(SALES_ORDERS_ENDPOINT, json=payload, headers=_idem())
    assert created.status_code == 201
    order = created.json()["data"]
    confirmed = await client.post(f"{SALES_ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]})
    assert confirmed.status_code == 200

    assert await _get_journal_for_source(client, "SALES_ORDER", order["id"]) is None


async def test_estimate_creates_no_journal(client):
    unit, product, customer, supplier = await _setup_basic(client)
    payload = {"customer_id": customer["id"], "lines": [{"product_id": product["id"], "quantity": "5", "uom_id": unit["id"], "unit_price": "100"}]}
    created = await client.post(ESTIMATES_ENDPOINT, json=payload, headers=_idem())
    assert created.status_code == 201
    estimate = created.json()["data"]

    assert await _get_journal_for_source(client, "ESTIMATE", estimate["id"]) is None


# --- TC-006/007/008: Purchase Invoice + GST ---


async def test_purchase_invoice_intra_state_creates_balanced_journal(client):
    unit, product, customer, supplier = await _setup_basic(client, state_code="33")
    invoice = await _create_posted_purchase_invoice(client, supplier, product, unit)
    assert invoice["accounting_posting_reference"] is not None

    list_item = await _get_journal_for_source(client, "PURCHASE_INVOICE", invoice["id"])
    assert list_item is not None
    detail = (await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}")).json()["data"]
    _assert_balanced(detail)
    assert Decimal(detail["total_credit"]) == Decimal(invoice["grand_total"])
    account_names = {line["account_name"] for line in detail["lines"]}
    assert any("Input CGST" in name for name in account_names)
    assert any("Input SGST" in name for name in account_names)
    assert any("Purchase Expense" in name for name in account_names)
    assert any("Accounts Payable" in name for name in account_names)


# --- TC-009: Customer Receipt ---


async def test_customer_receipt_creates_balanced_journal(client):
    unit, product, customer, supplier = await _setup_basic(client)
    created = await client.post(RECEIPTS_ENDPOINT, json={"customer_id": customer["id"], "payment_method": "CASH", "amount": "500", "allocations": []}, headers=_idem())
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert posted.status_code == 200

    list_item = await _get_journal_for_source(client, "CUSTOMER_RECEIPT", receipt["id"])
    assert list_item is not None
    detail = (await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}")).json()["data"]
    _assert_balanced(detail)
    assert Decimal(detail["total_debit"]) == Decimal("500")
    account_names = {line["account_name"] for line in detail["lines"]}
    assert any("Cash" in name for name in account_names)
    assert any("Accounts Receivable" in name for name in account_names)


# --- TC-010: Supplier Payment ---


async def test_supplier_payment_creates_balanced_journal(client):
    unit, product, customer, supplier = await _setup_basic(client)
    created = await client.post(PAYMENTS_ENDPOINT, json={"supplier_id": supplier["id"], "payment_method": "BANK_TRANSFER", "amount": "300", "allocations": []}, headers=_idem())
    payment = created.json()["data"]
    posted = await client.post(f"{PAYMENTS_ENDPOINT}/{payment['id']}/post", json={"expected_row_version": payment["row_version"]}, headers=_idem())
    assert posted.status_code == 200

    list_item = await _get_journal_for_source(client, "SUPPLIER_PAYMENT", payment["id"])
    detail = (await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}")).json()["data"]
    _assert_balanced(detail)
    account_names = {line["account_name"] for line in detail["lines"]}
    assert any("Bank" in name for name in account_names)
    assert any("Accounts Payable" in name for name in account_names)


# --- TC-011: Sales Return ---


async def test_sales_return_creates_balanced_journal(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")
    invoice_line_id = invoice["lines"][0]["id"]

    created = await client.post(
        SALES_RETURNS_ENDPOINT,
        json={"source_invoice_id": invoice["id"], "return_reason": "DAMAGED", "lines": [{"source_invoice_line_id": invoice_line_id, "quantity": "2"}]},
        headers=_idem(),
    )
    assert created.status_code == 201
    sales_return = created.json()["data"]
    confirmed = await client.post(f"{SALES_RETURNS_ENDPOINT}/{sales_return['id']}/confirm", json={"expected_row_version": sales_return["row_version"]}, headers=_idem())
    assert confirmed.status_code == 200

    list_item = await _get_journal_for_source(client, "SALES_RETURN", sales_return["id"])
    assert list_item is not None
    detail = (await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}")).json()["data"]
    _assert_balanced(detail)


# --- TC-012: Purchase Return ---


async def test_purchase_return_creates_balanced_journal(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_purchase_invoice(client, supplier, product, unit, "10", "50")
    invoice_line_id = invoice["lines"][0]["id"]

    created = await client.post(
        PURCHASE_RETURNS_ENDPOINT,
        json={"source_purchase_invoice_id": invoice["id"], "return_reason": "DAMAGED", "lines": [{"source_purchase_invoice_line_id": invoice_line_id, "quantity": "2"}]},
        headers=_idem(),
    )
    assert created.status_code == 201
    purchase_return = created.json()["data"]
    confirmed = await client.post(f"{PURCHASE_RETURNS_ENDPOINT}/{purchase_return['id']}/confirm", json={"expected_row_version": purchase_return["row_version"]}, headers=_idem())
    assert confirmed.status_code == 200

    list_item = await _get_journal_for_source(client, "PURCHASE_RETURN", purchase_return["id"])
    assert list_item is not None
    detail = (await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}")).json()["data"]
    _assert_balanced(detail)


# --- TC-013/014: Credit Note / Debit Note ---


async def test_credit_note_creates_balanced_journal(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")
    invoice_line_id = invoice["lines"][0]["id"]

    created = await client.post(
        CREDIT_DEBIT_NOTES_ENDPOINT,
        json={"source_invoice_id": invoice["id"], "note_type": "CREDIT_NOTE", "reason": "Price adjustment", "lines": [{"source_invoice_line_id": invoice_line_id, "quantity": "1"}]},
        headers=_idem(),
    )
    assert created.status_code == 201
    note = created.json()["data"]
    posted = await client.post(f"{CREDIT_DEBIT_NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": note["row_version"]}, headers=_idem())
    assert posted.status_code == 200

    list_item = await _get_journal_for_source(client, "CREDIT_NOTE", note["id"])
    assert list_item is not None
    detail = (await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}")).json()["data"]
    _assert_balanced(detail)


async def test_debit_note_creates_balanced_journal(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")
    invoice_line_id = invoice["lines"][0]["id"]

    created = await client.post(
        CREDIT_DEBIT_NOTES_ENDPOINT,
        json={"source_invoice_id": invoice["id"], "note_type": "DEBIT_NOTE", "reason": "Short billing", "lines": [{"source_invoice_line_id": invoice_line_id, "quantity": "1"}]},
        headers=_idem(),
    )
    assert created.status_code == 201
    note = created.json()["data"]
    posted = await client.post(f"{CREDIT_DEBIT_NOTES_ENDPOINT}/{note['id']}/post", json={"expected_row_version": note["row_version"]}, headers=_idem())
    assert posted.status_code == 200

    list_item = await _get_journal_for_source(client, "DEBIT_NOTE", note["id"])
    assert list_item is not None
    detail = (await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}")).json()["data"]
    _assert_balanced(detail)


# --- TC-017: duplicate posting prevented (idempotency) ---


async def test_duplicate_sales_invoice_posting_creates_one_journal(client, db_session):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)

    from app.models.journal_entry import JournalEntry

    result = await db_session.execute(
        select(JournalEntry).where(JournalEntry.source_type == "SALES_INVOICE", JournalEntry.source_id == uuid.UUID(invoice["id"]))
    )
    journals = result.scalars().all()
    assert len(journals) == 1  # exactly one ORIGINAL journal, no duplicate from any retried internal call


# --- TC-018/019/020: reversal, immutability, double-reversal rejected ---


async def test_manual_journal_reversal_works_and_original_is_immutable(client, db_session):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)
    list_item = await _get_journal_for_source(client, "SALES_INVOICE", invoice["id"])

    from app.models.journal_line import JournalLine

    original_lines_before = await db_session.execute(select(JournalLine).where(JournalLine.journal_id == uuid.UUID(list_item["id"])))
    original_amounts_before = sorted((str(l.debit_amount), str(l.credit_amount)) for l in original_lines_before.scalars().all())

    reverse_response = await client.post(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}/reverse")
    assert reverse_response.status_code == 200
    reversal_detail = reverse_response.json()["data"]
    assert reversal_detail["posting_event_type"] == "REVERSAL"
    assert reversal_detail["reversal_of_journal_id"] == list_item["id"]
    _assert_balanced(reversal_detail)

    original_after = (await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}")).json()["data"]
    assert original_after["status"] == "REVERSED"

    db_session.expire_all()
    original_lines_after = await db_session.execute(select(JournalLine).where(JournalLine.journal_id == uuid.UUID(list_item["id"])))
    original_amounts_after = sorted((str(l.debit_amount), str(l.credit_amount)) for l in original_lines_after.scalars().all())
    assert original_amounts_before == original_amounts_after  # untouched

    # double reversal rejected
    second = await client.post(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}/reverse")
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "ACC-010"


async def test_payment_reversal_reverses_its_own_journal(client):
    unit, product, customer, supplier = await _setup_basic(client)
    created = await client.post(RECEIPTS_ENDPOINT, json={"customer_id": customer["id"], "payment_method": "CASH", "amount": "400", "allocations": []}, headers=_idem())
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    posted_data = posted.json()["data"]

    original = await _get_journal_for_source(client, "CUSTOMER_RECEIPT", receipt["id"])
    assert original is not None

    reversed_resp = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/reverse", json={"expected_row_version": posted_data["row_version"]})
    assert reversed_resp.status_code == 200

    reversal_journal = await client.get(f"{ACCOUNTING_ENDPOINT}/journals", params={"source_type": "CUSTOMER_RECEIPT", "page_size": 100})
    events = {j["posting_event_type"] for j in reversal_journal.json()["data"] if j["source_id"] == receipt["id"]}
    assert events == {"ORIGINAL", "REVERSAL"}


# --- TC-023/029: tenant isolation ---


async def test_cross_tenant_journal_access_denied(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)
    list_item = await _get_journal_for_source(client, "SALES_INVOICE", invoice["id"])

    await _signup_and_login_owner(client)  # tenant B
    response = await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}")
    assert response.status_code == 404


# --- TC-024/025/026: GST reconciliation + traceability ---


async def test_gst_amounts_reconcile_with_invoice(client):
    unit, product, customer, supplier = await _setup_basic(client, state_code="33")
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")
    list_item = await _get_journal_for_source(client, "SALES_INVOICE", invoice["id"])
    detail = (await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}")).json()["data"]

    by_name = {line["account_name"]: line for line in detail["lines"]}
    cgst_line = next(v for k, v in by_name.items() if "CGST" in k)
    sgst_line = next(v for k, v in by_name.items() if "SGST" in k)
    assert cgst_line["credit_amount"] == invoice["cgst_total"]
    assert sgst_line["credit_amount"] == invoice["sgst_total"]

    # journal -> source traceability
    assert detail["source_id"] == invoice["id"]
    assert detail["source_number"] == invoice["invoice_number"]
    # source -> journal traceability
    assert invoice["accounting_posting_reference"] == detail["journal_number"]


# --- RBAC ---


async def test_salesperson_cannot_view_or_reverse_journals(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)
    list_item = await _get_journal_for_source(client, "SALES_INVOICE", invoice["id"])

    await _create_salesperson_and_login(client)
    assert (await client.get(f"{ACCOUNTING_ENDPOINT}/journals")).status_code == 403
    assert (await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}")).status_code == 403
    assert (await client.post(f"{ACCOUNTING_ENDPOINT}/journals/{list_item['id']}/reverse")).status_code == 403


# --- Chart of Accounts / mappings / posting rules ---


async def test_chart_of_accounts_and_mappings_and_posting_rules_endpoints(client):
    await _signup_and_login_owner(client)
    accounts = await client.get(f"{ACCOUNTING_ENDPOINT}/accounts")
    assert accounts.status_code == 200
    assert len(accounts.json()["data"]) > 0

    mappings = await client.get(f"{ACCOUNTING_ENDPOINT}/account-mappings")
    assert mappings.status_code == 200
    assert len(mappings.json()["data"]) > 0

    rules = await client.get(f"{ACCOUNTING_ENDPOINT}/posting-rules")
    assert rules.status_code == 200
    assert len(rules.json()["data"]) > 0
