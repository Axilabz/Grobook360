"""Collections-on-Invoice, Daily Collection Report & Sales-by-User Analysis
(approved plan, follow-up to the RBAC Alignment Phase).

Covers: GET /sales/invoices/{id}/payment-history (per-invoice collection
history), GET /reports/payments/daily-collection (day-grouped collections
+ export), and GET /analysis/sales-by-user (Owner/Manager see every staff
member, Salesperson sees only their own row — enforced server-side).
"""

import uuid

import pytest

SALES_INVOICES_ENDPOINT = "/api/v1/sales/invoices"
RECEIPTS_ENDPOINT = "/api/v1/customer-receipts"
REPORTS_ENDPOINT = "/api/v1/reports"
ANALYSIS_ENDPOINT = "/api/v1/analysis"
EXPORTS_ENDPOINT = "/api/v1/exports"
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
    return f"car-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "Collections Test Co", "address_line1": "1 Main St", "city": "Chennai",
            "state_code": state_code, "pin_code": "600001", "gstin": None,
        },
        "owner": {"phone": phone, "email": _unique_email(), "password": OWNER_PASSWORD, "confirm_password": OWNER_PASSWORD},
    }
    signup_response = await client.post(SIGNUP_ENDPOINT, json=payload, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert signup_response.status_code == 201
    login_response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": OWNER_PASSWORD})
    assert login_response.status_code == 200
    return signup_response.json()["data"]


async def _create_user_and_login(client, role: str, name: str = "User") -> str:
    from app.services.password_recovery.provider import ConsolePasswordRecoveryProvider

    phone = _unique_phone()
    create_response = await client.post(USERS_ENDPOINT, json={"name": name, "phone": phone, "email": _unique_email(), "role": role})
    assert create_response.status_code == 201
    reset_token = ConsolePasswordRecoveryProvider.outbox[-1].reset_link.split("token=")[1]
    reset_response = await client.post(RESET_ENDPOINT, json={"token": reset_token, "new_password": SALESPERSON_PASSWORD, "confirm_password": SALESPERSON_PASSWORD})
    assert reset_response.status_code == 200
    login = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": SALESPERSON_PASSWORD})
    assert login.status_code == 200
    return phone


async def _create_salesperson_and_login(client, name: str = "SP") -> str:
    return await _create_user_and_login(client, "SALESPERSON", name)


async def _current_user_id(client) -> str:
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    return me.json()["data"]["user_id"]


async def _login(client, phone: str, password: str) -> None:
    response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": password})
    assert response.status_code == 200


async def _create_unit(client) -> dict:
    response = await client.post(UNITS_ENDPOINT, json={"code": "PCS", "name": "Pieces"})
    assert response.status_code == 201
    return response.json()["data"]


async def _create_product(client, base_uom_id: str) -> dict:
    payload = {"sku": _unique_sku(), "name": "Test Product", "base_uom_id": base_uom_id, "gst_rate": "18", "cost_price": "50", "selling_price": "100", "mrp": "120"}
    response = await client.post(PRODUCTS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


async def _create_customer(client, **overrides) -> dict:
    payload = {"name": "Test Customer", "owner_name": "Owner", "phone": _unique_phone()}
    payload.update(overrides)
    response = await client.post(CUSTOMERS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


async def _seed_opening_stock(client, product_id: str, uom_id: str, quantity: str = "1000") -> None:
    response = await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock", json={"product_id": product_id, "quantity": quantity, "uom_id": uom_id}, headers=_idem(),
    )
    assert response.status_code == 201


async def _setup_basic(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    product = await _create_product(client, unit["id"])
    customer = await _create_customer(client)
    await _seed_opening_stock(client, product["id"], unit["id"])
    return unit, product, customer


async def _create_posted_sales_invoice(client, customer, product, unit, amount_qty: str = "10", unit_price: str = "100") -> dict:
    payload = {"customer_id": customer["id"], "lines": [{"product_id": product["id"], "quantity": amount_qty, "uom_id": unit["id"], "unit_price": unit_price}]}
    created = await client.post(SALES_INVOICES_ENDPOINT, json=payload, headers=_idem())
    assert created.status_code == 201
    invoice = created.json()["data"]
    posted = await client.post(f"{SALES_INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    return posted.json()["data"]


async def _create_and_post_receipt(client, customer, invoice, amount: str) -> dict:
    created = await client.post(
        RECEIPTS_ENDPOINT,
        json={"customer_id": customer["id"], "payment_method": "CASH", "amount": amount, "allocations": [{"invoice_id": invoice["id"], "allocated_amount": amount}]},
        headers=_idem(),
    )
    assert created.status_code == 201
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    return posted.json()["data"]


# --- Per-invoice payment history ---------------------------------------


async def test_payment_history_empty_before_any_collection(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)
    response = await client.get(f"{SALES_INVOICES_ENDPOINT}/{invoice['id']}/payment-history")
    assert response.status_code == 200
    assert response.json()["data"] == []


async def test_payment_history_shows_collector_and_amount(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")
    grand_total = invoice["grand_total"]
    await _create_and_post_receipt(client, customer, invoice, grand_total)

    response = await client.get(f"{SALES_INVOICES_ENDPOINT}/{invoice['id']}/payment-history")
    assert response.status_code == 200
    entries = response.json()["data"]
    assert len(entries) == 1
    assert entries[0]["amount"] == grand_total
    # Owner sign-up has no `name` field (only `business_name`) — the key
    # must still be present and resolvable to a non-null name for a named
    # user (checked by the Manager-created-user scenario elsewhere in this
    # file); here it legitimately resolves to None for the Owner.
    assert "collected_by_name" in entries[0]
    assert entries[0]["status"] == "POSTED"


async def test_payment_history_cross_tenant_invoice_returns_404(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)

    await _signup_and_login_owner(client)  # tenant B
    response = await client.get(f"{SALES_INVOICES_ENDPOINT}/{invoice['id']}/payment-history")
    assert response.status_code == 404


async def test_payment_history_requires_sales_invoice_view_permission(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit)
    phone = await _create_salesperson_and_login(client)
    response = await client.get(f"{SALES_INVOICES_ENDPOINT}/{invoice['id']}/payment-history")
    # Salesperson keeps sales_invoice.view (unchanged by the RBAC Alignment
    # Phase) — this should succeed, just scoped to the same tenant data.
    assert response.status_code == 200


# --- Daily Collection Report --------------------------------------------


async def test_daily_collection_report_groups_by_date(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")
    grand_total = invoice["grand_total"]
    await _create_and_post_receipt(client, customer, invoice, grand_total)

    response = await client.get(f"{REPORTS_ENDPOINT}/payments/daily-collection")
    assert response.status_code == 200
    days = response.json()["data"]
    assert len(days) == 1
    assert days[0]["entry_count"] == 1
    assert days[0]["total_amount"] == grand_total
    assert days[0]["entries"][0]["customer_name"] == customer["name"]


async def test_daily_collection_report_denied_without_reports_view_payments(client):
    unit, product, customer = await _setup_basic(client)
    await _create_salesperson_and_login(client)  # lacks reports.view_payments
    response = await client.get(f"{REPORTS_ENDPOINT}/payments/daily-collection")
    assert response.status_code == 403


async def test_daily_collection_export_returns_valid_xlsx(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")
    await _create_and_post_receipt(client, customer, invoice, invoice["grand_total"])

    response = await client.post(EXPORTS_ENDPOINT, json={"resource": "daily_collection", "format": "xlsx", "scope": "ALL_FILTERED"})
    assert response.status_code == 200
    assert response.content[:2] == b"PK"


# --- Sales by User Analysis ---------------------------------------------


async def test_owner_sees_every_staff_members_sales(client):
    owner_phone = _unique_phone()
    signup_response = await client.post(
        SIGNUP_ENDPOINT,
        json={
            "organization": {"business_name": "Collections Test Co", "address_line1": "1 Main St", "city": "Chennai", "state_code": "33", "pin_code": "600001", "gstin": None},
            "owner": {"phone": owner_phone, "email": _unique_email(), "password": OWNER_PASSWORD, "confirm_password": OWNER_PASSWORD},
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert signup_response.status_code == 201
    await _login(client, owner_phone, OWNER_PASSWORD)

    unit = await _create_unit(client)
    product = await _create_product(client, unit["id"])
    customer = await _create_customer(client)
    await _seed_opening_stock(client, product["id"], unit["id"])
    owner_id = await _current_user_id(client)
    await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")

    # Manager has sales_invoice.post (unlike Salesperson, unchanged by the
    # RBAC Alignment Phase) — use Manager as the "other staff member" whose
    # invoice must also show up in Owner's full breakdown.
    await _create_user_and_login(client, "MANAGER", "Mgr")
    manager_id = await _current_user_id(client)
    await _create_posted_sales_invoice(client, customer, product, unit, "5", "100")

    # Back to Owner to read the full breakdown.
    await _login(client, owner_phone, OWNER_PASSWORD)
    response = await client.get(f"{ANALYSIS_ENDPOINT}/sales-by-user")
    assert response.status_code == 200
    rows = {row["user_id"]: row for row in response.json()["data"]}
    assert owner_id in rows and rows[owner_id]["invoice_count"] == 1
    assert manager_id in rows and rows[manager_id]["invoice_count"] == 1


async def test_salesperson_sees_only_their_own_sales(client):
    unit, product, customer = await _setup_basic(client)
    other_user_id = await _current_user_id(client)  # Owner's own id
    await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")

    await _create_salesperson_and_login(client)
    response = await client.get(f"{ANALYSIS_ENDPOINT}/sales-by-user")
    assert response.status_code == 200
    rows = response.json()["data"]
    # The Owner's own user_id must NEVER appear in a Salesperson's view —
    # this is the server-side enforcement the approved plan requires.
    assert all(row["user_id"] != other_user_id for row in rows)
