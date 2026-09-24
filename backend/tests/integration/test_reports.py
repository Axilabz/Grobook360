"""PROMPT-027 test catalogue for Reports, Dashboards & Financial
Statements (/api/v1/reports/*).

Covers the core mandatory scenarios from §60: dashboard load and
reconciliation with detailed reports, Sales/Purchase summary+register+
customer/supplier-wise+product-wise+returns, current stock and stock
movement traceability, Receivables/Payables with partial/full payment,
Payment register+method summary+cheque report, General Ledger+Trial
Balance+P&L+Balance Sheet (all balancing), GST reporting delegation,
draft-document exclusion, tenant isolation, and RBAC.
"""

import uuid
from decimal import Decimal

import pytest

REPORTS_ENDPOINT = "/api/v1/reports"
SALES_INVOICES_ENDPOINT = "/api/v1/sales/invoices"
SALES_RETURNS_ENDPOINT = "/api/v1/sales/returns"
PURCHASE_INVOICES_ENDPOINT = "/api/v1/purchase/invoices"
PURCHASE_RETURNS_ENDPOINT = "/api/v1/purchase/returns"
RECEIPTS_ENDPOINT = "/api/v1/customer-receipts"
PAYMENTS_ENDPOINT = "/api/v1/supplier-payments"
ACCOUNTING_ENDPOINT = "/api/v1/accounting"
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
    return f"rep-{uuid.uuid4().hex[:12]}@example.com"


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
        "organization": {"business_name": "Reports Test Co", "address_line1": "1 Main St", "city": "Chennai", "state_code": state_code, "pin_code": "600001", "gstin": None},
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


async def _create_unit(client) -> dict:
    response = await client.post(UNITS_ENDPOINT, json={"code": "PCS", "name": "Pieces"})
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
    response = await client.post(f"{INVENTORY_ENDPOINT}/opening-stock", json={"product_id": product_id, "quantity": quantity, "uom_id": uom_id}, headers=_idem())
    assert response.status_code == 201


async def _setup_basic(client, state_code: str = "33"):
    await _signup_and_login_owner(client, state_code=state_code)
    unit = await _create_unit(client)
    product = await _create_product(client, unit["id"])
    customer = await _create_customer(client, state_code=state_code)
    supplier = await _create_supplier(client, state_code=state_code)
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


# --- TC-001/TC-047: Dashboard loads and reconciles with detailed reports --


async def test_dashboard_loads_and_reconciles_with_sales_report(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)

    dashboard = (await client.get(f"{REPORTS_ENDPOINT}/dashboard", params={"period": "THIS_MONTH"})).json()["data"]
    sales_summary = (await client.get(f"{REPORTS_ENDPOINT}/sales/summary", params={"date_from": dashboard["period"]["date_from"], "date_to": dashboard["period"]["date_to"]})).json()["data"]

    assert Decimal(dashboard["sales"]["net_sales"]) == Decimal(sales_summary["net_sales"])
    assert Decimal(dashboard["sales"]["invoice_total"]) == Decimal(invoice["grand_total"])


async def test_dashboard_receivables_equals_receivables_report(client):
    unit, product, customer, supplier = await _setup_basic(client)
    await _create_posted_sales_invoice(client, customer, product, unit)

    dashboard = (await client.get(f"{REPORTS_ENDPOINT}/dashboard", params={"period": "THIS_MONTH"})).json()["data"]
    receivables = (await client.get(f"{REPORTS_ENDPOINT}/receivables")).json()

    assert Decimal(dashboard["receivables"]["total_outstanding"]) == Decimal(receivables["summary"]["total_receivables"])


# --- TC-004/005: Sales Summary / Invoice Register -------------------------


async def test_sales_summary_calculates_correctly(client):
    unit, product, customer, supplier = await _setup_basic(client, state_code="33")
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, qty="10", unit_price="100")

    summary = (await client.get(f"{REPORTS_ENDPOINT}/sales/summary")).json()["data"]
    assert Decimal(summary["taxable_sales"]) == Decimal(invoice["taxable_total"])
    assert Decimal(summary["total_gst"]) == Decimal(invoice["tax_total"])
    assert Decimal(summary["net_sales"]) == Decimal(invoice["taxable_total"])


async def test_sales_invoice_register_shows_posted_invoices_only(client):
    unit, product, customer, supplier = await _setup_basic(client)
    posted = await _create_posted_sales_invoice(client, customer, product, unit)

    draft_payload = {"customer_id": customer["id"], "lines": [{"product_id": product["id"], "quantity": "1", "uom_id": unit["id"], "unit_price": "100"}]}
    draft_response = await client.post(SALES_INVOICES_ENDPOINT, json=draft_payload, headers=_idem())
    assert draft_response.status_code == 201

    register = (await client.get(f"{REPORTS_ENDPOINT}/sales/invoices")).json()
    invoice_ids = {item["invoice_id"] for item in register["data"]}
    assert posted["id"] in invoice_ids
    assert draft_response.json()["data"]["id"] not in invoice_ids


# --- TC-007/008: Customer-wise / Product-wise Sales ------------------------


async def test_customer_wise_sales_aggregates_correctly(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, qty="10", unit_price="100")

    result = (await client.get(f"{REPORTS_ENDPOINT}/sales/customers")).json()["data"]
    row = next(r for r in result if r["customer_id"] == customer["id"])
    assert row["invoice_count"] == 1
    assert Decimal(row["taxable_sales"]) == Decimal(invoice["taxable_total"])
    assert Decimal(row["outstanding"]) == Decimal(invoice["grand_total"])


async def test_product_wise_sales_aggregates_correctly(client):
    unit, product, customer, supplier = await _setup_basic(client)
    await _create_posted_sales_invoice(client, customer, product, unit, qty="10", unit_price="100")

    result = (await client.get(f"{REPORTS_ENDPOINT}/sales/products")).json()["data"]
    row = next(r for r in result if r["product_id"] == product["id"])
    assert Decimal(row["quantity_sold"]) == Decimal("10.000")


# --- TC-009: Sales Return Report ------------------------------------------


async def test_sales_return_report_calculates_correctly(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, qty="10")
    return_payload = {"source_invoice_id": invoice["id"], "return_reason": "DAMAGED", "lines": [{"source_invoice_line_id": invoice["lines"][0]["id"], "quantity": "3"}]}
    created = await client.post(SALES_RETURNS_ENDPOINT, json=return_payload, headers=_idem())
    sales_return = created.json()["data"]
    confirmed = await client.post(f"{SALES_RETURNS_ENDPOINT}/{sales_return['id']}/confirm", json={"expected_row_version": sales_return["row_version"]}, headers=_idem())
    assert confirmed.status_code == 200
    sales_return = confirmed.json()["data"]

    result = (await client.get(f"{REPORTS_ENDPOINT}/sales/returns")).json()["data"]
    row = next(r for r in result if r["return_id"] == sales_return["id"])
    assert Decimal(row["total_return_value"]) == Decimal(sales_return["grand_total"])
    assert row["source_invoice_number"] == invoice["invoice_number"]


# --- TC-010/011: Purchase Summary / Register --------------------------------


async def test_purchase_summary_calculates_correctly(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_purchase_invoice(client, supplier, product, unit, qty="10", unit_price="50")

    summary = (await client.get(f"{REPORTS_ENDPOINT}/purchase/summary")).json()["data"]
    assert Decimal(summary["taxable_purchase"]) == Decimal(invoice["taxable_total"])
    assert Decimal(summary["net_purchase"]) == Decimal(invoice["taxable_total"])


async def test_purchase_invoice_register_includes_supplier_name(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_purchase_invoice(client, supplier, product, unit)

    register = (await client.get(f"{REPORTS_ENDPOINT}/purchase/invoices")).json()["data"]
    row = next(r for r in register if r["invoice_id"] == invoice["id"])
    assert row["supplier_name"] == supplier["name"]


# --- TC-012/013: Supplier-wise / Product-wise Purchase ----------------------


async def test_supplier_wise_purchase_aggregates_correctly(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_purchase_invoice(client, supplier, product, unit, qty="10", unit_price="50")

    result = (await client.get(f"{REPORTS_ENDPOINT}/purchase/suppliers")).json()["data"]
    row = next(r for r in result if r["supplier_id"] == supplier["id"])
    assert Decimal(row["taxable_purchase"]) == Decimal(invoice["taxable_total"])


async def test_product_wise_purchase_aggregates_correctly(client):
    unit, product, customer, supplier = await _setup_basic(client)
    await _create_posted_purchase_invoice(client, supplier, product, unit, qty="10", unit_price="50")

    result = (await client.get(f"{REPORTS_ENDPOINT}/purchase/products")).json()["data"]
    row = next(r for r in result if r["product_id"] == product["id"])
    assert Decimal(row["quantity_purchased"]) == Decimal("10.000")


# --- TC-014: Purchase Return Report -----------------------------------------


async def test_purchase_return_report_calculates_correctly(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_purchase_invoice(client, supplier, product, unit, qty="10")
    return_payload = {"source_purchase_invoice_id": invoice["id"], "return_reason": "DAMAGED", "lines": [{"source_purchase_invoice_line_id": invoice["lines"][0]["id"], "quantity": "2"}]}
    created = await client.post(PURCHASE_RETURNS_ENDPOINT, json=return_payload, headers=_idem())
    purchase_return = created.json()["data"]
    confirmed = await client.post(f"{PURCHASE_RETURNS_ENDPOINT}/{purchase_return['id']}/confirm", json={"expected_row_version": purchase_return["row_version"]}, headers=_idem())
    assert confirmed.status_code == 200
    purchase_return = confirmed.json()["data"]

    result = (await client.get(f"{REPORTS_ENDPOINT}/purchase/returns")).json()["data"]
    row = next(r for r in result if r["return_id"] == purchase_return["id"])
    assert Decimal(row["total_return_value"]) == Decimal(purchase_return["grand_total"])


# --- TC-015/016: Current Stock / Stock Movement traceability ----------------


async def test_current_stock_equals_stock_ledger_balance(client):
    unit, product, customer, supplier = await _setup_basic(client)
    await _create_posted_sales_invoice(client, customer, product, unit, qty="15")

    result = (await client.get(f"{REPORTS_ENDPOINT}/inventory/current-stock")).json()["data"]
    row = next(r for r in result if r["product_id"] == product["id"])
    assert Decimal(row["current_quantity"]) == Decimal("985.000")


async def test_stock_movement_report_traces_source_document(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, qty="5")

    result = (await client.get(f"{REPORTS_ENDPOINT}/inventory/movements", params={"product_id": product["id"], "movement_type": "STOCK_OUT"})).json()["data"]
    assert any(m["source_type"] == "SALES_INVOICE" for m in result)


# --- TC-017/018/019: Receivables + partial/full payment ---------------------


async def test_receivables_equals_invoice_outstanding(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, qty="10", unit_price="100")

    result = (await client.get(f"{REPORTS_ENDPOINT}/receivables")).json()["data"]
    row = next(r for r in result if r["invoice_id"] == invoice["id"])
    assert Decimal(row["outstanding"]) == Decimal(invoice["grand_total"])


async def test_partial_payment_reflected_in_receivables(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, qty="10", unit_price="100")

    receipt_payload = {"customer_id": customer["id"], "payment_method": "CASH", "amount": "500", "allocations": [{"invoice_id": invoice["id"], "allocated_amount": "500"}]}
    created = await client.post(RECEIPTS_ENDPOINT, json=receipt_payload, headers=_idem())
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert posted.status_code == 200

    result = (await client.get(f"{REPORTS_ENDPOINT}/receivables")).json()["data"]
    row = next(r for r in result if r["invoice_id"] == invoice["id"])
    assert row["payment_status"] == "PARTIALLY_PAID"
    assert Decimal(row["outstanding"]) == Decimal(invoice["grand_total"]) - Decimal("500")


async def test_fully_paid_invoice_excluded_from_receivables_list(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, qty="1", unit_price="100")

    receipt_payload = {"customer_id": customer["id"], "payment_method": "CASH", "amount": invoice["grand_total"], "allocations": [{"invoice_id": invoice["id"], "allocated_amount": invoice["grand_total"]}]}
    created = await client.post(RECEIPTS_ENDPOINT, json=receipt_payload, headers=_idem())
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert posted.status_code == 200

    result = (await client.get(f"{REPORTS_ENDPOINT}/receivables")).json()["data"]
    assert all(r["invoice_id"] != invoice["id"] for r in result)


# --- TC-020: Payables ---------------------------------------------------------


async def test_payables_equals_purchase_invoice_outstanding(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_purchase_invoice(client, supplier, product, unit, qty="10", unit_price="50")

    result = (await client.get(f"{REPORTS_ENDPOINT}/payables")).json()["data"]
    row = next(r for r in result if r["invoice_id"] == invoice["id"])
    assert Decimal(row["outstanding"]) == Decimal(invoice["grand_total"])


# --- TC-021/022/023: Payment reports ------------------------------------------


async def test_payment_register_shows_customer_receipt(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, qty="1", unit_price="100")
    receipt_payload = {"customer_id": customer["id"], "payment_method": "UPI", "amount": invoice["grand_total"], "allocations": [{"invoice_id": invoice["id"], "allocated_amount": invoice["grand_total"]}]}
    created = await client.post(RECEIPTS_ENDPOINT, json=receipt_payload, headers=_idem())
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert posted.status_code == 200

    result = (await client.get(f"{REPORTS_ENDPOINT}/payments", params={"party_type": "CUSTOMER"})).json()["data"]
    row = next(r for r in result if r["payment_id"] == receipt["id"])
    assert row["party_name"] == customer["name"]
    assert row["payment_method"] == "UPI"


async def test_payment_method_summary_aggregates_by_method(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, qty="1", unit_price="100")
    receipt_payload = {"customer_id": customer["id"], "payment_method": "CASH", "amount": invoice["grand_total"], "allocations": [{"invoice_id": invoice["id"], "allocated_amount": invoice["grand_total"]}]}
    created = await client.post(RECEIPTS_ENDPOINT, json=receipt_payload, headers=_idem())
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert posted.status_code == 200

    result = (await client.get(f"{REPORTS_ENDPOINT}/payments/method-summary")).json()["data"]
    row = next(r for r in result if r["payment_method"] == "CASH")
    assert Decimal(row["amount"]) == Decimal(invoice["grand_total"])


async def test_cheque_report_shows_pending_cheque(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, qty="1", unit_price="100")
    receipt_payload = {
        "customer_id": customer["id"], "payment_method": "CHEQUE", "amount": invoice["grand_total"],
        "cheque_number": "CHQ001", "cheque_date": "2026-04-01", "cheque_bank_name": "Test Bank",
        "allocations": [{"invoice_id": invoice["id"], "allocated_amount": invoice["grand_total"]}],
    }
    created = await client.post(RECEIPTS_ENDPOINT, json=receipt_payload, headers=_idem())
    assert created.status_code == 201, created.text
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert posted.status_code == 200

    result = (await client.get(f"{REPORTS_ENDPOINT}/payments/cheques", params={"cheque_status": "PENDING"})).json()["data"]
    assert any(c["cheque_number"] == "CHQ001" for c in result)


# --- TC-024/025/026: General Ledger / Trial Balance --------------------------


async def test_general_ledger_equals_posted_journal_lines(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)

    accounts = (await client.get(f"{ACCOUNTING_ENDPOINT}/accounts")).json()["data"]
    ar_account = next(a for a in accounts if "Receivable" in a["name"] and "Input" not in a["name"])

    gl = (await client.get(f"{REPORTS_ENDPOINT}/accounting/general-ledger", params={"account_id": ar_account["id"]})).json()["data"]
    assert any(e["source_number"] == invoice["invoice_number"] for e in gl["entries"])
    matching = next(e for e in gl["entries"] if e["source_number"] == invoice["invoice_number"])
    assert Decimal(matching["debit"]) == Decimal(invoice["grand_total"])


async def test_trial_balance_balances(client):
    unit, product, customer, supplier = await _setup_basic(client)
    await _create_posted_sales_invoice(client, customer, product, unit)
    await _create_posted_purchase_invoice(client, supplier, product, unit)

    tb = (await client.get(f"{REPORTS_ENDPOINT}/accounting/trial-balance")).json()["data"]
    assert tb["is_balanced"] is True
    assert Decimal(tb["total_debit"]) == Decimal(tb["total_credit"])


# --- TC-027/028: P&L / Balance Sheet ------------------------------------------


async def test_profit_and_loss_uses_posted_accounting_data(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, qty="10", unit_price="100")

    pl = (await client.get(f"{REPORTS_ENDPOINT}/accounting/profit-loss")).json()["data"]
    assert Decimal(pl["total_revenue"]) == Decimal(invoice["taxable_total"])


async def test_balance_sheet_balances(client):
    unit, product, customer, supplier = await _setup_basic(client)
    await _create_posted_sales_invoice(client, customer, product, unit)
    await _create_posted_purchase_invoice(client, supplier, product, unit)

    bs = (await client.get(f"{REPORTS_ENDPOINT}/accounting/balance-sheet")).json()["data"]
    assert bs["is_balanced"] is True
    assert Decimal(bs["difference"]) == Decimal("0")
    assert Decimal(bs["total_assets"]) == Decimal(bs["total_liabilities"]) + Decimal(bs["total_equity"])


# --- TC-030: GST report equals GST reporting dataset -------------------------


async def test_gst_summary_reconciles_with_gst_module(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)
    return_period = invoice["invoice_date"][:7]

    report_summary = (await client.get(f"{REPORTS_ENDPOINT}/gst/summary", params={"return_period": return_period})).json()["data"]
    gst_summary = (await client.get("/api/v1/gst/dashboard", params={"return_period": return_period})).json()["data"]
    assert Decimal(report_summary["output_gst"]) == Decimal(gst_summary["output_gst"])


# --- TC-034/035: Date range / Financial year filtering ------------------------


async def test_invalid_date_range_rejected(client):
    await _setup_basic(client)
    response = await client.get(f"{REPORTS_ENDPOINT}/sales/summary", params={"date_from": "2026-12-31", "date_to": "2026-01-01"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REP-001"


async def test_date_range_filtering_excludes_out_of_range_invoice(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)

    from datetime import date, timedelta

    future_from = (date.today() + timedelta(days=5)).isoformat()
    future_to = (date.today() + timedelta(days=10)).isoformat()
    summary = (await client.get(f"{REPORTS_ENDPOINT}/sales/summary", params={"date_from": future_from, "date_to": future_to})).json()["data"]
    assert Decimal(summary["net_sales"]) == Decimal("0")


# --- TC-036: Tenant isolation --------------------------------------------------


async def test_tenant_isolation_on_sales_report(client):
    unit, product, customer, supplier = await _setup_basic(client)
    await _create_posted_sales_invoice(client, customer, product, unit)

    other_phone = _unique_phone()
    signup = await client.post(
        SIGNUP_ENDPOINT,
        json={
            "organization": {"business_name": "Other Tenant", "address_line1": "2 Side St", "city": "Mumbai", "state_code": "27", "pin_code": "400001", "gstin": None},
            "owner": {"phone": other_phone, "email": _unique_email(), "password": OWNER_PASSWORD, "confirm_password": OWNER_PASSWORD},
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert signup.status_code == 201
    login = await client.post(LOGIN_ENDPOINT, json={"login_identifier": other_phone, "password": OWNER_PASSWORD})
    assert login.status_code == 200

    result = (await client.get(f"{REPORTS_ENDPOINT}/sales/summary")).json()["data"]
    assert Decimal(result["net_sales"]) == Decimal("0")


# --- TC-037: RBAC --------------------------------------------------------------


async def test_salesperson_denied_receivables_and_trial_balance(client):
    await _setup_basic(client)
    await _create_salesperson_and_login(client)

    assert (await client.get(f"{REPORTS_ENDPOINT}/receivables")).status_code == 403
    assert (await client.get(f"{REPORTS_ENDPOINT}/accounting/trial-balance")).status_code == 403
    assert (await client.get(f"{REPORTS_ENDPOINT}/purchase/summary")).status_code == 403


async def test_salesperson_allowed_dashboard_and_sales_report(client):
    await _setup_basic(client)
    await _create_salesperson_and_login(client)

    assert (await client.get(f"{REPORTS_ENDPOINT}/dashboard")).status_code == 200
    assert (await client.get(f"{REPORTS_ENDPOINT}/sales/summary")).status_code == 200
    assert (await client.get(f"{REPORTS_ENDPOINT}/inventory/current-stock")).status_code == 200


# --- TC-040: Pagination --------------------------------------------------------


async def test_sales_invoice_register_pagination(client):
    unit, product, customer, supplier = await _setup_basic(client)
    for _ in range(3):
        await _create_posted_sales_invoice(client, customer, product, unit, qty="1")

    page1 = (await client.get(f"{REPORTS_ENDPOINT}/sales/invoices", params={"page": 1, "page_size": 2})).json()
    assert len(page1["data"]) == 2
    assert page1["pagination"]["total_items"] == 3
    assert page1["pagination"]["total_pages"] == 2
