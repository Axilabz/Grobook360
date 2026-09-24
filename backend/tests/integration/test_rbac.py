"""PROMPT-006 S47 test catalogue for /api/v1/roles and /api/v1/permissions,
plus permission-based authorization on /api/v1/users (migrated from
require_role in PROMPT-005 to require_permission in PROMPT-006).
"""

import uuid

import pytest
from sqlalchemy import select

from app.models.role import Role
from app.services.password_recovery.provider import ConsolePasswordRecoveryProvider

SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"
RESET_ENDPOINT = "/api/v1/auth/reset-password"
USERS_ENDPOINT = "/api/v1/users"
ROLES_ENDPOINT = "/api/v1/roles"
PERMISSIONS_ENDPOINT = "/api/v1/permissions"

OWNER_PASSWORD = "SecurePass123"
NEW_USER_PASSWORD = "AnotherSecurePass456"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    from app.core.rate_limit import reset_rate_limits
    from app.core.login_lockout import reset_all

    reset_rate_limits()
    reset_all()
    ConsolePasswordRecoveryProvider.outbox.clear()
    yield


async def _signup_and_login_owner(client) -> dict:
    phone = _unique_phone()
    payload = {
        "organization": {
            "business_name": "RBAC Test Co",
            "address_line1": "1 Main St",
            "city": "Chennai",
            "state_code": "33",
            "pin_code": "600001",
            "gstin": None,
        },
        "owner": {"phone": phone, "email": _unique_email(), "password": OWNER_PASSWORD, "confirm_password": OWNER_PASSWORD},
    }
    signup_response = await client.post(SIGNUP_ENDPOINT, json=payload, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert signup_response.status_code == 201
    data = signup_response.json()["data"]
    data["phone"] = phone

    login_response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": OWNER_PASSWORD})
    assert login_response.status_code == 200
    return data


async def _create_user_and_login(client, *, role: str, password: str = NEW_USER_PASSWORD) -> dict:
    phone = _unique_phone()
    email = _unique_email()
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "Test User", "phone": phone, "email": email, "role": role}
    )
    assert create_response.status_code == 201
    user_data = create_response.json()["data"]
    user_data["phone"] = phone

    reset_token = ConsolePasswordRecoveryProvider.outbox[-1].reset_link.split("token=")[1]
    reset_response = await client.post(RESET_ENDPOINT, json={"token": reset_token, "new_password": password, "confirm_password": password})
    assert reset_response.status_code == 200

    login_response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": password})
    assert login_response.status_code == 200
    return user_data


# --- ROLE ---


async def test_rbac_api_001_list_roles(client):
    await _signup_and_login_owner(client)
    response = await client.get(ROLES_ENDPOINT)
    assert response.status_code == 200
    names = {r["name"] for r in response.json()["data"]}
    assert "OWNER" in names


async def test_rbac_api_002_get_role(client):
    await _signup_and_login_owner(client)
    roles = (await client.get(ROLES_ENDPOINT)).json()["data"]
    owner_role = next(r for r in roles if r["name"] == "OWNER")

    response = await client.get(f"{ROLES_ENDPOINT}/{owner_role['id']}")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["name"] == "OWNER"
    assert "users.create" in body["permissions"]
    assert body["user_count"] >= 1


async def test_rbac_api_003_unauthorized_role_access(client):
    await _signup_and_login_owner(client)
    salesperson = await _create_user_and_login(client, role="SALESPERSON")
    # log back in as salesperson (already logged in by helper)
    response = await client.get(ROLES_ENDPOINT)
    assert response.status_code == 403


async def test_rbac_api_004_role_scope_via_tenant_isolation(client):
    tenant_a = await _signup_and_login_owner(client)
    roles_a = (await client.get(ROLES_ENDPOINT)).json()["data"]
    owner_role_a = next(r for r in roles_a if r["name"] == "OWNER")

    await _signup_and_login_owner(client)  # switch to tenant B
    response = await client.get(f"{ROLES_ENDPOINT}/{owner_role_a['id']}")
    assert response.status_code == 404  # tenant A's role must not resolve under tenant B


# --- PERMISSION ---


async def test_rbac_api_005_list_permissions(client):
    await _signup_and_login_owner(client)
    response = await client.get(PERMISSIONS_ENDPOINT)
    assert response.status_code == 200
    codes = {p["code"] for p in response.json()["data"]}
    assert {"users.view", "users.create", "users.update", "users.activate", "users.deactivate"}.issubset(codes)


async def test_rbac_api_006_get_role_permissions(client):
    await _signup_and_login_owner(client)
    roles = (await client.get(ROLES_ENDPOINT)).json()["data"]
    owner_role = next(r for r in roles if r["name"] == "OWNER")

    response = await client.get(f"{ROLES_ENDPOINT}/{owner_role['id']}/permissions")
    assert response.status_code == 200
    assert "users.deactivate" in response.json()["data"]


async def test_rbac_api_007_unauthorized_permission_access(client):
    await _signup_and_login_owner(client)
    await _create_user_and_login(client, role="SALESPERSON")
    response = await client.get(PERMISSIONS_ENDPOINT)
    assert response.status_code == 403


# --- EFFECTIVE PERMISSIONS PER ROLE ---


async def test_owner_gets_full_users_permission_set(client):
    await _signup_and_login_owner(client)
    me = await client.get("/api/v1/auth/me")
    permissions = set(me.json()["data"]["permissions"])
    assert {"users.view", "users.create", "users.update", "users.activate", "users.deactivate", "roles.view", "permissions.view"} <= permissions


async def test_manager_gets_view_only_permission_set(client):
    await _signup_and_login_owner(client)
    await _create_user_and_login(client, role="MANAGER")
    me = await client.get("/api/v1/auth/me")
    permissions = set(me.json()["data"]["permissions"])
    assert permissions == {
        "users.view", "roles.view", "permissions.view",
        "customers.view", "customers.create", "customers.update", "customers.activate", "customers.deactivate", "customers.export",
        "suppliers.view", "suppliers.create", "suppliers.update", "suppliers.activate", "suppliers.deactivate", "suppliers.export",
        "products.view", "products.create", "products.update", "products.activate", "products.deactivate", "products.export",
        "inventory.view", "inventory.opening_stock", "inventory.adjust", "inventory.stock_in", "inventory.stock_out",
        "sales_estimate.view", "sales_estimate.create", "sales_estimate.edit", "sales_estimate.send",
        "sales_estimate.accept", "sales_estimate.reject", "sales_estimate.cancel", "sales_estimate.convert",
        "sales_order.view", "sales_order.create", "sales_order.edit", "sales_order.confirm", "sales_order.cancel",
        "delivery_challan.view", "delivery_challan.create", "delivery_challan.edit",
        "delivery_challan.confirm", "delivery_challan.cancel",
        "sales_invoice.view", "sales_invoice.create", "sales_invoice.edit",
        "sales_invoice.post", "sales_invoice.cancel", "sales_invoice.export",
        "sales_return.view", "sales_return.create", "sales_return.edit",
        "sales_return.confirm", "sales_return.cancel",
        "credit_note.view", "credit_note.create", "credit_note.edit", "credit_note.post", "credit_note.cancel",
        "debit_note.view", "debit_note.create", "debit_note.edit", "debit_note.post", "debit_note.cancel",
        "einvoice.view", "einvoice.generate", "einvoice.cancel",
        "eway_bill.view", "eway_bill.generate", "eway_bill.cancel",
        "purchase_order.view", "purchase_order.create", "purchase_order.edit", "purchase_order.confirm", "purchase_order.cancel",
        "goods_receipt.view", "goods_receipt.create", "goods_receipt.edit", "goods_receipt.confirm", "goods_receipt.cancel",
        "purchase_invoice.view", "purchase_invoice.create", "purchase_invoice.edit", "purchase_invoice.post", "purchase_invoice.cancel", "purchase_invoice.export",
        "purchase_return.view", "purchase_return.create", "purchase_return.edit", "purchase_return.confirm", "purchase_return.cancel",
        "customer_receipt.view", "customer_receipt.create", "customer_receipt.edit", "customer_receipt.post", "customer_receipt.reverse", "customer_receipt.export",
        "supplier_payment.view", "supplier_payment.create", "supplier_payment.edit", "supplier_payment.post", "supplier_payment.reverse", "supplier_payment.export",
        "accounting.view_journals", "accounting.view_chart_of_accounts", "accounting.manage_account_mappings", "accounting.reverse_journal",
        "gst.view", "gst.prepare_returns", "gst.export",
        "reports.view_dashboard", "reports.view_sales", "reports.view_purchase", "reports.view_inventory",
        "reports.view_receivables", "reports.view_payables", "reports.view_payments", "reports.view_general_ledger",
        "reports.view_trial_balance", "reports.view_profit_loss", "reports.view_balance_sheet", "reports.view_gst",
        "reports.export",
        "employees.view", "employees.create", "employees.edit", "employees.deactivate",
        "salary.view", "salary.manage", "attendance.view", "attendance.manage",
        "leave.view", "leave.manage", "leave.approve",
        "payroll.run", "payroll.finalize", "payroll.view", "payroll.view_payslip", "payroll.export",
    }


async def test_salesperson_gets_no_permissions(client):
    # Name predates PROMPT-007/008/009/010/012/013/014/015/016: Salesperson
    # has the Customers and Suppliers "Limited" slice of access (create/
    # edit, no deactivate) per FR-CUST-07/FR-SUPP-05, only view for
    # Products (FR-PROD-04) and Inventory (FR-STK-04), the full Estimate
    # lifecycle except convert-to-Sales-Order (PROMPT-012), the full Sales
    # Order lifecycle except confirm (PROMPT-013), the full Delivery
    # Challan lifecycle except confirm (PROMPT-014), the full Sales
    # Invoice lifecycle except post (PROMPT-015), and the full Sales
    # Return lifecycle except confirm (PROMPT-016 — no approved source
    # resolves any of these exclusions; all mirror the Customer/Supplier
    # "full minus one higher-commitment action" shape) — it is no longer
    # literally permission-less, just still has none of the Users surface.
    await _signup_and_login_owner(client)
    await _create_user_and_login(client, role="SALESPERSON")
    me = await client.get("/api/v1/auth/me")
    assert set(me.json()["data"]["permissions"]) == {
        "customers.view", "customers.create", "customers.update",
        "suppliers.view", "suppliers.create", "suppliers.update",
        "products.view",
        "inventory.view",
        "sales_estimate.view", "sales_estimate.create", "sales_estimate.edit", "sales_estimate.send",
        "sales_estimate.accept", "sales_estimate.reject", "sales_estimate.cancel",
        "sales_order.view", "sales_order.create", "sales_order.edit", "sales_order.cancel",
        "delivery_challan.view", "delivery_challan.create", "delivery_challan.edit", "delivery_challan.cancel",
        "sales_invoice.view", "sales_invoice.create", "sales_invoice.edit", "sales_invoice.cancel",
        "sales_return.view", "sales_return.create", "sales_return.edit", "sales_return.cancel",
        "credit_note.view", "credit_note.create", "credit_note.edit", "credit_note.cancel",
        "debit_note.view", "debit_note.create", "debit_note.edit", "debit_note.cancel",
        "einvoice.view", "eway_bill.view",
        "customer_receipt.view", "customer_receipt.create", "customer_receipt.edit",
        "reports.view_dashboard", "reports.view_sales", "reports.view_inventory",
    }


# --- AUTHORIZATION (permission-based, migrated from require_role) ---


async def test_rbac_api_015_authorized_endpoint(client):
    await _signup_and_login_owner(client)
    response = await client.post(
        USERS_ENDPOINT, json={"name": "X", "phone": _unique_phone(), "email": _unique_email(), "role": "MANAGER"}
    )
    assert response.status_code == 201


async def test_rbac_api_016_missing_permission(client):
    await _signup_and_login_owner(client)
    await _create_user_and_login(client, role="MANAGER")  # users.view only, no users.create
    response = await client.post(
        USERS_ENDPOINT, json={"name": "X", "phone": _unique_phone(), "email": _unique_email(), "role": "SALESPERSON"}
    )
    assert response.status_code == 403


async def test_rbac_api_018_tenant_isolation_on_roles(client):
    tenant_a = await _signup_and_login_owner(client)
    roles_a = (await client.get(ROLES_ENDPOINT)).json()["data"]

    await _signup_and_login_owner(client)  # tenant B
    roles_b = (await client.get(ROLES_ENDPOINT)).json()["data"]

    ids_a = {r["id"] for r in roles_a}
    ids_b = {r["id"] for r in roles_b}
    assert ids_a.isdisjoint(ids_b)


async def test_rbac_api_020_direct_api_bypass_denied(client):
    # No auth at all — must be rejected before any permission check runs.
    response = await client.get(ROLES_ENDPOINT)
    assert response.status_code == 401


# --- PRIVILEGE ESCALATION (structural, via ASSIGNABLE_ROLES + permission gating) ---


async def test_rbac_api_012_platform_role_escalation_blocked(client):
    await _signup_and_login_owner(client)
    response = await client.post(
        USERS_ENDPOINT,
        json={"name": "X", "phone": _unique_phone(), "email": _unique_email(), "role": "PLATFORM_ADMINISTRATOR"},
    )
    assert response.status_code == 422  # rejected by schema — not even a valid enum value


async def test_new_role_row_is_auto_seeded_with_default_permissions(client, db_session):
    tenant = await _signup_and_login_owner(client)
    await _create_user_and_login(client, role="MANAGER")

    result = await db_session.execute(
        select(Role).where(Role.tenant_id == uuid.UUID(tenant["tenant_id"]), Role.name == "MANAGER")
    )
    manager_role = result.scalar_one()

    from app.models.permission import Permission
    from app.models.role_permission import RolePermission

    perm_result = await db_session.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == manager_role.id)
    )
    codes = {row[0] for row in perm_result.all()}
    assert codes == {
        "users.view", "roles.view", "permissions.view",
        "customers.view", "customers.create", "customers.update", "customers.activate", "customers.deactivate", "customers.export",
        "suppliers.view", "suppliers.create", "suppliers.update", "suppliers.activate", "suppliers.deactivate", "suppliers.export",
        "products.view", "products.create", "products.update", "products.activate", "products.deactivate", "products.export",
        "inventory.view", "inventory.opening_stock", "inventory.adjust", "inventory.stock_in", "inventory.stock_out",
        "sales_estimate.view", "sales_estimate.create", "sales_estimate.edit", "sales_estimate.send",
        "sales_estimate.accept", "sales_estimate.reject", "sales_estimate.cancel", "sales_estimate.convert",
        "sales_order.view", "sales_order.create", "sales_order.edit", "sales_order.confirm", "sales_order.cancel",
        "delivery_challan.view", "delivery_challan.create", "delivery_challan.edit",
        "delivery_challan.confirm", "delivery_challan.cancel",
        "sales_invoice.view", "sales_invoice.create", "sales_invoice.edit",
        "sales_invoice.post", "sales_invoice.cancel", "sales_invoice.export",
        "sales_return.view", "sales_return.create", "sales_return.edit",
        "sales_return.confirm", "sales_return.cancel",
        "credit_note.view", "credit_note.create", "credit_note.edit", "credit_note.post", "credit_note.cancel",
        "debit_note.view", "debit_note.create", "debit_note.edit", "debit_note.post", "debit_note.cancel",
        "einvoice.view", "einvoice.generate", "einvoice.cancel",
        "eway_bill.view", "eway_bill.generate", "eway_bill.cancel",
        "purchase_order.view", "purchase_order.create", "purchase_order.edit", "purchase_order.confirm", "purchase_order.cancel",
        "goods_receipt.view", "goods_receipt.create", "goods_receipt.edit", "goods_receipt.confirm", "goods_receipt.cancel",
        "purchase_invoice.view", "purchase_invoice.create", "purchase_invoice.edit", "purchase_invoice.post", "purchase_invoice.cancel", "purchase_invoice.export",
        "purchase_return.view", "purchase_return.create", "purchase_return.edit", "purchase_return.confirm", "purchase_return.cancel",
        "customer_receipt.view", "customer_receipt.create", "customer_receipt.edit", "customer_receipt.post", "customer_receipt.reverse", "customer_receipt.export",
        "supplier_payment.view", "supplier_payment.create", "supplier_payment.edit", "supplier_payment.post", "supplier_payment.reverse", "supplier_payment.export",
        "accounting.view_journals", "accounting.view_chart_of_accounts", "accounting.manage_account_mappings", "accounting.reverse_journal",
        "gst.view", "gst.prepare_returns", "gst.export",
        "reports.view_dashboard", "reports.view_sales", "reports.view_purchase", "reports.view_inventory",
        "reports.view_receivables", "reports.view_payables", "reports.view_payments", "reports.view_general_ledger",
        "reports.view_trial_balance", "reports.view_profit_loss", "reports.view_balance_sheet", "reports.view_gst",
        "reports.export",
        "employees.view", "employees.create", "employees.edit", "employees.deactivate",
        "salary.view", "salary.manage", "attendance.view", "attendance.manage",
        "leave.view", "leave.manage", "leave.approve",
        "payroll.run", "payroll.finalize", "payroll.view", "payroll.view_payslip", "payroll.export",
    }
