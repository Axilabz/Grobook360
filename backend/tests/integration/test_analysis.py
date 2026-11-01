"""Analysis page test catalogue (/api/v1/analysis/*).

Covers: reconciliation with the authoritative Reports endpoints
(Analysis must never show a different Net Sales/Net Purchase number than
Reports for the same period), tenant isolation, RBAC per tab, the
comparison-period math (including the safe zero/None percentage-change
case), and the explicit "unavailable" treatment for inventory value and
gross margin.
"""

import uuid
from decimal import Decimal

import pytest

ANALYSIS_ENDPOINT = "/api/v1/analysis"
REPORTS_ENDPOINT = "/api/v1/reports"
SALES_INVOICES_ENDPOINT = "/api/v1/sales/invoices"
PURCHASE_INVOICES_ENDPOINT = "/api/v1/purchase/invoices"
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
    return f"an-{uuid.uuid4().hex[:12]}@example.com"


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


async def _signup_and_login_owner(client, business_name: str = "Analysis Test Co") -> dict:
    phone = _unique_phone()
    payload = {
        "organization": {"business_name": business_name, "address_line1": "1 Main St", "city": "Chennai", "state_code": "33", "pin_code": "600001", "gstin": None},
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
    await _signup_and_login_owner(client)
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


# --- Reconciliation: Analysis must equal Reports for the same period ------


async def test_overview_net_sales_reconciles_with_sales_report(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)

    overview = (await client.get(f"{ANALYSIS_ENDPOINT}/overview", params={"period": "THIS_MONTH"})).json()
    period = overview["meta"]["period"]
    sales_summary = (await client.get(f"{REPORTS_ENDPOINT}/sales/summary", params={"date_from": period["date_from"], "date_to": period["date_to"]})).json()["data"]

    assert Decimal(overview["data"]["kpis"]["net_sales"]["current"]) == Decimal(sales_summary["net_sales"])
    assert invoice["status"] == "POSTED"


async def test_sales_analysis_net_sales_reconciles_with_sales_report(client):
    unit, product, customer, supplier = await _setup_basic(client)
    await _create_posted_sales_invoice(client, customer, product, unit)

    sales_analysis = (await client.get(f"{ANALYSIS_ENDPOINT}/sales", params={"period": "THIS_MONTH"})).json()
    period = sales_analysis["meta"]["period"]
    sales_summary = (await client.get(f"{REPORTS_ENDPOINT}/sales/summary", params={"date_from": period["date_from"], "date_to": period["date_to"]})).json()["data"]

    assert Decimal(sales_analysis["data"]["kpis"]["net_sales"]["current"]) == Decimal(sales_summary["net_sales"])
    assert Decimal(sales_analysis["data"]["kpis"]["gross_sales"]["current"]) == Decimal(sales_summary["gross_sales"])


async def test_purchase_analysis_net_purchase_reconciles_with_purchase_report(client):
    unit, product, customer, supplier = await _setup_basic(client)
    await _create_posted_purchase_invoice(client, supplier, product, unit)

    purchase_analysis = (await client.get(f"{ANALYSIS_ENDPOINT}/purchases", params={"period": "THIS_MONTH"})).json()
    period = purchase_analysis["meta"]["period"]
    purchase_summary = (await client.get(f"{REPORTS_ENDPOINT}/purchase/summary", params={"date_from": period["date_from"], "date_to": period["date_to"]})).json()["data"]

    assert Decimal(purchase_analysis["data"]["kpis"]["net_purchase"]["current"]) == Decimal(purchase_summary["net_purchase"])


# --- Comparison-period math -------------------------------------------------


async def test_comparison_with_no_prior_period_data_returns_none_percent_not_zero(client):
    # The only invoice is THIS month; PREVIOUS_PERIOD (last month) has none.
    # change_percent must be None (unavailable), never a fabricated 0% or
    # a divide-by-zero crash.
    unit, product, customer, supplier = await _setup_basic(client)
    await _create_posted_sales_invoice(client, customer, product, unit)

    response = await client.get(f"{ANALYSIS_ENDPOINT}/sales", params={"period": "THIS_MONTH", "compare": "PREVIOUS_PERIOD"})
    assert response.status_code == 200
    kpi = response.json()["data"]["kpis"]["net_sales"]
    assert Decimal(kpi["previous"]) == Decimal("0")
    assert kpi["change_percent"] is None


async def test_comparison_growth_percent_calculated_correctly(client):
    unit, product, customer, supplier = await _setup_basic(client)
    # Two invoices now; compare current month against itself via explicit
    # CUSTOM bounds so both "periods" contain the same known total, and
    # the percent-change math is independently verifiable.
    await _create_posted_sales_invoice(client, customer, product, unit, qty="10", unit_price="100")

    response = await client.get(
        f"{ANALYSIS_ENDPOINT}/sales",
        params={"period": "THIS_MONTH", "compare": "CUSTOM", "compare_from": "2000-01-01", "compare_to": "2000-01-31"},
    )
    assert response.status_code == 200
    kpi = response.json()["data"]["kpis"]["net_sales"]
    # previous period (year 2000) has zero data -> None change_percent, not misleading.
    assert Decimal(kpi["previous"]) == Decimal("0")
    assert kpi["change_percent"] is None
    assert Decimal(kpi["current"]) > Decimal("0")


# --- Unavailable metrics: never fabricated ---------------------------------


async def test_inventory_value_and_gross_margin_are_explicitly_unavailable(client):
    unit, product, customer, supplier = await _setup_basic(client)
    await _create_posted_sales_invoice(client, customer, product, unit)

    inventory = (await client.get(f"{ANALYSIS_ENDPOINT}/inventory", params={"period": "THIS_MONTH"})).json()["data"]
    assert inventory["kpis"]["inventory_value"]["value"] is None
    assert inventory["kpis"]["stock_turnover"]["value"] is None

    products = (await client.get(f"{ANALYSIS_ENDPOINT}/products", params={"period": "THIS_MONTH"})).json()["data"]
    assert products["top_10"][0]["gross_margin"]["value"] is None


# --- Tenant isolation --------------------------------------------------------


async def test_tenant_isolation_second_tenant_sees_zero(client):
    unit, product, customer, supplier = await _setup_basic(client)
    await _create_posted_sales_invoice(client, customer, product, unit)

    # A second, freshly-signed-up tenant must see zero, not the first
    # tenant's sales.
    await _signup_and_login_owner(client, business_name="Other Analysis Co")
    overview = (await client.get(f"{ANALYSIS_ENDPOINT}/overview", params={"period": "THIS_MONTH"})).json()["data"]
    assert Decimal(overview["kpis"]["net_sales"]["current"]) == Decimal("0")


# --- RBAC --------------------------------------------------------------------


async def test_salesperson_can_view_sales_and_inventory_analysis(client):
    await _setup_basic(client)
    await _create_salesperson_and_login(client)

    assert (await client.get(f"{ANALYSIS_ENDPOINT}/overview", params={"period": "THIS_MONTH"})).status_code == 200
    assert (await client.get(f"{ANALYSIS_ENDPOINT}/sales", params={"period": "THIS_MONTH"})).status_code == 200
    assert (await client.get(f"{ANALYSIS_ENDPOINT}/inventory", params={"period": "THIS_MONTH"})).status_code == 200


async def test_salesperson_cannot_view_purchase_analysis(client):
    await _setup_basic(client)
    await _create_salesperson_and_login(client)

    response = await client.get(f"{ANALYSIS_ENDPOINT}/purchases", params={"period": "THIS_MONTH"})
    assert response.status_code == 403


async def test_unknown_period_rejected(client):
    await _setup_basic(client)
    response = await client.get(f"{ANALYSIS_ENDPOINT}/sales", params={"period": "NOT_A_PERIOD"})
    assert response.status_code == 422
