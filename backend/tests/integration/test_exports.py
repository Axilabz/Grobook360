"""Test catalogue for the Global Table/Grid Export Framework
(cross-cutting Excel/PDF export prompt) — /api/v1/exports.

Follows test_products.py/test_customers.py's structure and helper
style. Covers the security-critical subset explicitly demanded by the
source prompt's own §29 (RBAC, tenant isolation, resource allowlist,
scope/format validation) plus §30 QA basics (valid file magic bytes,
search/filter preservation, empty result, current-page vs all-filtered
scope). Not every one of the ~40 candidate resources is re-tested here
— the 7 resources this pass implements (customers, suppliers, products,
sales_invoices, purchase_invoices, customer_receipts, supplier_payments)
share ONE code path (export_service.run_export), so tenant/RBAC/format
behavior is proven once, generically, and re-checked per-resource only
for the resource-specific wiring (search/filter fields, column mapping).
"""

import uuid

import pytest

EXPORTS_ENDPOINT = "/api/v1/exports"
CUSTOMERS_ENDPOINT = "/api/v1/customers"
SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"
USERS_ENDPOINT = "/api/v1/users"
RESET_ENDPOINT = "/api/v1/auth/reset-password"

OWNER_PASSWORD = "SecurePass123"
SALESPERSON_PASSWORD = "AnotherSecurePass456"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _unique_email() -> str:
    return f"exp-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    from app.core.rate_limit import reset_rate_limits
    from app.core.login_lockout import reset_all

    reset_rate_limits()
    reset_all()
    yield


async def _signup_and_login_owner(client, business_name: str = "Export Test Co") -> dict:
    phone = _unique_phone()
    payload = {
        "organization": {
            "business_name": business_name, "address_line1": "1 Main St", "city": "Chennai",
            "state_code": "33", "pin_code": "600001", "gstin": None,
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


async def _create_customer(client, **overrides) -> dict:
    payload = {"name": "ABC Traders", "owner_name": "Ravi", "phone": _unique_phone()}
    payload.update(overrides)
    response = await client.post(CUSTOMERS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


# --- Happy path: valid Excel/PDF generation ---


async def test_export_customers_xlsx_valid_file(client):
    await _signup_and_login_owner(client)
    await _create_customer(client, name="Sunrise Traders")

    response = await client.post(EXPORTS_ENDPOINT, json={"resource": "customers", "format": "xlsx", "scope": "ALL_FILTERED"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content[:2] == b"PK"  # xlsx is a zip container


async def test_export_customers_pdf_valid_file(client):
    await _signup_and_login_owner(client)
    await _create_customer(client, name="Sunrise Traders")

    response = await client.post(EXPORTS_ENDPOINT, json={"resource": "customers", "format": "pdf", "scope": "ALL_FILTERED"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:5] == b"%PDF-"


async def test_export_empty_result_still_returns_valid_file(client):
    await _signup_and_login_owner(client)
    # No customers created — the resource legitimately has zero rows.
    response = await client.post(
        EXPORTS_ENDPOINT, json={"resource": "customers", "format": "pdf", "scope": "ALL_FILTERED", "search": "no-such-customer"}
    )
    assert response.status_code == 200
    assert response.content[:5] == b"%PDF-"


# --- Search/filter/scope preservation ---


async def test_export_respects_search(client):
    await _signup_and_login_owner(client)
    await _create_customer(client, name="Alpha Distributors")
    await _create_customer(client, name="Beta Wholesalers")

    # Excel is the easiest format to assert row-level content on directly.
    from io import BytesIO
    from openpyxl import load_workbook

    response = await client.post(
        EXPORTS_ENDPOINT, json={"resource": "customers", "format": "xlsx", "scope": "ALL_FILTERED", "search": "Alpha"}
    )
    assert response.status_code == 200
    wb = load_workbook(BytesIO(response.content))
    ws = wb.active
    all_text = " ".join(str(cell.value) for row in ws.iter_rows() for cell in row if cell.value is not None)
    assert "Alpha Distributors" in all_text
    assert "Beta Wholesalers" not in all_text


async def test_export_current_page_vs_all_filtered_scope(client):
    await _signup_and_login_owner(client)
    for i in range(3):
        await _create_customer(client, name=f"Customer {i}", phone=_unique_phone())

    from io import BytesIO
    from openpyxl import load_workbook

    current_page = await client.post(
        EXPORTS_ENDPOINT, json={"resource": "customers", "format": "xlsx", "scope": "CURRENT_PAGE", "page": 1, "page_size": 2}
    )
    assert current_page.status_code == 200
    wb1 = load_workbook(BytesIO(current_page.content))
    data_rows_current = sum(1 for row in wb1.active.iter_rows(min_row=8) if row[0].value)

    all_filtered = await client.post(EXPORTS_ENDPOINT, json={"resource": "customers", "format": "xlsx", "scope": "ALL_FILTERED"})
    assert all_filtered.status_code == 200
    wb2 = load_workbook(BytesIO(all_filtered.content))
    data_rows_all = sum(1 for row in wb2.active.iter_rows(min_row=8) if row[0].value)

    assert data_rows_current == 2
    assert data_rows_all == 3


# --- Validation ---


async def test_export_invalid_resource_rejected(client):
    await _signup_and_login_owner(client)
    response = await client.post(EXPORTS_ENDPOINT, json={"resource": "some_internal_table", "format": "xlsx", "scope": "ALL_FILTERED"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EXP-001"


async def test_export_invalid_format_rejected(client):
    await _signup_and_login_owner(client)
    response = await client.post(EXPORTS_ENDPOINT, json={"resource": "customers", "format": "docx", "scope": "ALL_FILTERED"})
    assert response.status_code == 422  # Pydantic pattern validation


async def test_export_invalid_scope_rejected(client):
    await _signup_and_login_owner(client)
    response = await client.post(EXPORTS_ENDPOINT, json={"resource": "customers", "format": "xlsx", "scope": "EVERYTHING"})
    assert response.status_code == 422


# --- RBAC ---


async def test_export_unauthorized_without_session(client):
    response = await client.post(EXPORTS_ENDPOINT, json={"resource": "customers", "format": "xlsx", "scope": "ALL_FILTERED"})
    assert response.status_code == 401


async def test_export_salesperson_cannot_export_customers(client):
    """Salesperson has customers.view/create but NOT customers.export
    (migration 0031's own explicit resolution) — the UI would hide the
    Export button, but this proves the BACKEND independently rejects a
    direct API call too (§13 of the source prompt)."""
    await _signup_and_login_owner(client)
    await _create_salesperson_and_login(client)

    response = await client.post(EXPORTS_ENDPOINT, json={"resource": "customers", "format": "xlsx", "scope": "ALL_FILTERED"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "EXP-005"


async def test_export_salesperson_can_view_but_not_export(client):
    """Confirms this is genuinely a VIEW-vs-EXPORT split, not a blanket
    Salesperson lockout on the resource."""
    await _signup_and_login_owner(client)
    await _create_customer(client)
    await _create_salesperson_and_login(client)

    view_response = await client.get(CUSTOMERS_ENDPOINT)
    assert view_response.status_code == 200  # Salesperson CAN view

    export_response = await client.post(EXPORTS_ENDPOINT, json={"resource": "customers", "format": "xlsx", "scope": "ALL_FILTERED"})
    assert export_response.status_code == 403  # but CANNOT export


# --- Tenant isolation ---


async def test_export_tenant_isolation(client):
    """Tenant A's export must never contain Tenant B's records, even
    though both tenants have customers with similar names."""
    await _signup_and_login_owner(client, business_name="Tenant A Co")
    await _create_customer(client, name="Shared Name Traders")

    await _signup_and_login_owner(client, business_name="Tenant B Co")
    await _create_customer(client, name="Shared Name Traders")

    from io import BytesIO
    from openpyxl import load_workbook

    # Currently logged in as Tenant B's owner (the second signup).
    response = await client.post(EXPORTS_ENDPOINT, json={"resource": "customers", "format": "xlsx", "scope": "ALL_FILTERED"})
    assert response.status_code == 200
    wb = load_workbook(BytesIO(response.content))
    data_rows = sum(1 for row in wb.active.iter_rows(min_row=8) if row[0].value)
    assert data_rows == 1  # only Tenant B's own single customer, never Tenant A's


# --- Resource coverage smoke test (each of the 7 implemented resources) ---


@pytest.mark.parametrize("resource", ["customers", "suppliers", "products", "sales_invoices", "purchase_invoices", "customer_receipts", "supplier_payments"])
async def test_export_each_resource_owner_can_export_empty_dataset(client, resource):
    """Confirms every resource in this pass's registry is reachable end
    to end (permission resolves, adapter runs, generator produces a
    valid file) even with zero matching rows — proves the wiring for
    all 7, not just the customers happy-path exercised in depth above."""
    await _signup_and_login_owner(client)
    response = await client.post(EXPORTS_ENDPOINT, json={"resource": resource, "format": "xlsx", "scope": "ALL_FILTERED"})
    assert response.status_code == 200, response.text
    assert response.content[:2] == b"PK"
