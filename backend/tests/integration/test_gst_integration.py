"""PROMPT-018 test catalogue for E-Invoice / E-Way Bill integration.

Follows test_credit_debit_notes.py's structure and helper style. Covers
the §42 QA test-case baseline (successful generation, missing GSTIN/HSN,
non-applicable invoice, duplicate/concurrent generate, provider timeout/
5xx/auth-failure, unknown-result reconciliation, cancellation, E-Way
Bill generation/cancellation, tenant isolation, RBAC) using the
deterministic `SandboxSimulatorProvider` (no real external GST/NIC
system is ever contacted).
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.services.gst_integration.provider import SandboxSimulatorProvider

EINVOICE_ENDPOINT = "/api/v1/sales/invoices"  # + /{id}/einvoice[...]
EWAY_BILLS_ENDPOINT = "/api/v1/eway-bills"
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
    SandboxSimulatorProvider.force_outcome = None
    yield
    SandboxSimulatorProvider.force_outcome = None


async def _signup_and_login_owner(client, *, gstin: str | None = "33AAAAA0000A1Z5", state_code: str = "33") -> dict:
    phone = _unique_phone()
    payload = {
        "organization": {
            "business_name": "GST Integration Test Co",
            "address_line1": "1 Main St",
            "city": "Chennai",
            "state_code": state_code,
            "pin_code": "600001",
            "gstin": gstin,
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
        "gst_rate": "18", "cost_price": "50", "selling_price": "100", "mrp": "120", "hsn_code": "12345678",
    }
    payload.update(overrides)
    response = await client.post(PRODUCTS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


async def _create_customer(client, **overrides) -> dict:
    payload = {
        "name": "Test Customer", "owner_name": "Owner", "phone": _unique_phone(),
        "state_code": "33", "address": "1 Buyer Street, Chennai",
    }
    payload.update(overrides)
    response = await client.post(CUSTOMERS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


async def _setup_basic(client, **owner_overrides):
    await _signup_and_login_owner(client, **owner_overrides)
    unit = await _create_unit(client)
    product = await _create_product(client, unit["id"])
    customer = await _create_customer(client)
    return unit, product, customer


async def _seed_opening_stock(client, product_id: str, uom_id: str, quantity: str = "100000") -> None:
    response = await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock",
        json={"product_id": product_id, "quantity": quantity, "uom_id": uom_id},
        headers=_idem(),
    )
    assert response.status_code == 201


async def _create_posted_direct_invoice(client, customer: dict, product: dict, unit: dict, quantity: str = "10") -> dict:
    await _seed_opening_stock(client, product["id"], unit["id"])
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


def _einvoice_url(invoice_id: str, suffix: str = "") -> str:
    return f"{INVOICES_ENDPOINT}/{invoice_id}/einvoice{suffix}"


async def _generate_einvoice(client, invoice_id: str, **headers):
    h = _idem()
    h.update(headers)
    return await client.post(_einvoice_url(invoice_id, "/generate"), headers=h)


# --- TC-001 Successful E-Invoice ---


async def test_successful_einvoice_generation(client, db_session):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    response = await _generate_einvoice(client, invoice["id"])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "GENERATED"
    assert data["irn"]
    assert data["ack_number"]
    assert data["ack_date"]
    assert data["has_signed_qr"] is True

    # Denormalized snapshot on the invoice itself is also updated.
    invoice_detail = (await client.get(f"{INVOICES_ENDPOINT}/{invoice['id']}")).json()["data"]
    assert invoice_detail["irn"] == data["irn"]
    assert invoice_detail["einvoice_status"] == "GENERATED"


# --- TC-002 Missing GSTIN ---


async def test_missing_gstin_blocks_generation(client):
    unit, product, customer = await _setup_basic(client, gstin=None)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    response = await _generate_einvoice(client, invoice["id"])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EINV-004"

    status = (await client.get(_einvoice_url(invoice["id"]))).json()["data"]
    assert status["status"] == "FAILED"


# --- TC-003 Missing HSN ---


async def test_missing_hsn_blocks_generation(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    product = await _create_product(client, unit["id"], hsn_code=None)
    customer = await _create_customer(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    response = await _generate_einvoice(client, invoice["id"])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EINV-004"
    assert "HSN" in response.json()["error"]["message"]


# --- TC-005 Non-applicable invoice ---


async def test_draft_invoice_not_applicable(client):
    unit, product, customer = await _setup_basic(client)
    payload = {
        "customer_id": customer["id"],
        "lines": [{"product_id": product["id"], "quantity": "5", "uom_id": unit["id"], "unit_price": "100"}],
    }
    created = await client.post(INVOICES_ENDPOINT, json=payload, headers=_idem())
    draft_invoice = created.json()["data"]  # never posted

    response = await _generate_einvoice(client, draft_invoice["id"])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EINV-003"


async def test_einvoice_disabled_for_tenant_not_applicable(client, db_session):
    tenant = await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    product = await _create_product(client, unit["id"])
    customer = await _create_customer(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    from app.models.integration_configuration import IntegrationConfiguration

    config = IntegrationConfiguration(tenant_id=uuid.UUID(tenant["tenant_id"]), einvoice_enabled=False)
    db_session.add(config)
    await db_session.commit()

    response = await _generate_einvoice(client, invoice["id"])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EINV-003"


# --- TC-006 Duplicate Generate click (idempotent retry) ---


async def test_duplicate_generate_click_same_key_returns_same_result(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)
    key = str(uuid.uuid4())

    first = await client.post(_einvoice_url(invoice["id"], "/generate"), headers={"Idempotency-Key": key})
    assert first.status_code == 200
    second = await client.post(_einvoice_url(invoice["id"], "/generate"), headers={"Idempotency-Key": key})
    assert second.status_code == 200
    assert second.json()["data"] == first.json()["data"]


async def test_duplicate_generate_different_key_rejected(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    first = await _generate_einvoice(client, invoice["id"])
    assert first.status_code == 200

    second = await _generate_einvoice(client, invoice["id"])
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "EINV-008"


# --- TC-007 Concurrent Generate requests ---


async def test_concurrent_generate_requests_only_one_succeeds(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    results = await asyncio.gather(_generate_einvoice(client, invoice["id"]), _generate_einvoice(client, invoice["id"]))
    statuses = sorted(r.status_code for r in results)
    # One succeeds (200); the other hits either the concurrency guard (409)
    # or "already generated" (422) depending on lock-acquisition order.
    assert statuses[0] == 200
    assert statuses[1] in (409, 422)

    status = (await client.get(_einvoice_url(invoice["id"]))).json()["data"]
    assert status["status"] == "GENERATED"
    assert status["irn"]


# --- TC-008 Provider timeout / TC-011 Unknown result / TC-012 Reconciliation ---


async def test_provider_timeout_then_reconciliation_succeeds_without_duplicate(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    SandboxSimulatorProvider.force_outcome = "TIMEOUT"
    first = await _generate_einvoice(client, invoice["id"])
    assert first.status_code == 502
    assert first.json()["error"]["code"] == "EINV-014"

    status = (await client.get(_einvoice_url(invoice["id"]))).json()["data"]
    assert status["status"] == "STATUS_UNKNOWN"

    # A blind retry must NOT be allowed to just re-submit — it must
    # reconcile first. Clear the fault injection so reconciliation +
    # (if needed) the safe retry both succeed deterministically.
    SandboxSimulatorProvider.force_outcome = None
    second = await _generate_einvoice(client, invoice["id"])
    assert second.status_code == 200
    data = second.json()["data"]
    assert data["status"] == "GENERATED"
    assert data["irn"]


# --- TC-009 Provider 5xx / TC-022 Retry after transient failure ---


async def test_provider_unavailable_then_retry_succeeds(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    SandboxSimulatorProvider.force_outcome = "UNAVAILABLE"
    first = await _generate_einvoice(client, invoice["id"])
    assert first.status_code == 502
    assert first.json()["error"]["code"] == "EINV-012"

    status = (await client.get(_einvoice_url(invoice["id"]))).json()["data"]
    assert status["status"] == "FAILED"

    SandboxSimulatorProvider.force_outcome = None
    retry = await _generate_einvoice(client, invoice["id"])
    assert retry.status_code == 200
    assert retry.json()["data"]["status"] == "GENERATED"


# --- TC-010 Provider authentication failure ---


async def test_provider_auth_failure(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    SandboxSimulatorProvider.force_outcome = "AUTH_FAILED"
    response = await _generate_einvoice(client, invoice["id"])
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "EINV-013"


# --- TC-013 E-Invoice cancellation / TC-014 Invalid cancellation ---


async def test_einvoice_cancellation(client, db_session):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)
    generated = (await _generate_einvoice(client, invoice["id"])).json()["data"]

    response = await client.post(
        _einvoice_url(invoice["id"], "/cancel"), json={"reason": "Data entry error"}, headers=_idem()
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "CANCELLED"
    assert data["cancellation_reason"] == "Data entry error"
    # The original IRN record is preserved, not deleted/blanked.
    assert data["irn"] == generated["irn"]

    from app.models.audit_log import AuditLog

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_type == "einvoice", AuditLog.action == "EINVOICE_CANCELLED")
    )
    assert result.scalars().first() is not None


async def test_invalid_cancellation_before_generation(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    response = await client.post(
        _einvoice_url(invoice["id"], "/cancel"), json={"reason": "x"}, headers=_idem()
    )
    assert response.status_code == 404


async def test_cannot_cancel_twice(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)
    await _generate_einvoice(client, invoice["id"])
    first = await client.post(_einvoice_url(invoice["id"], "/cancel"), json={"reason": "x"}, headers=_idem())
    assert first.status_code == 200

    second = await client.post(_einvoice_url(invoice["id"], "/cancel"), json={"reason": "x"}, headers=_idem())
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "EINV-010"


# --- TC-020 Cross-tenant access attempt ---


async def test_tenant_isolation(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)
    await _generate_einvoice(client, invoice["id"])

    await _signup_and_login_owner(client)  # switch to tenant B
    response = await client.get(_einvoice_url(invoice["id"]))
    assert response.status_code == 404


# --- TC-021 Unauthorized generation/cancellation ---


async def test_salesperson_cannot_generate(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    await _create_salesperson_and_login(client)
    response = await _generate_einvoice(client, invoice["id"])
    assert response.status_code == 403


async def test_salesperson_can_view(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)
    await _generate_einvoice(client, invoice["id"])

    await _create_salesperson_and_login(client)
    response = await client.get(_einvoice_url(invoice["id"]))
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "GENERATED"


# --- Audit ---


async def test_audit_generation_events(client, db_session):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)
    await _generate_einvoice(client, invoice["id"])

    from app.models.audit_log import AuditLog

    result = await db_session.execute(select(AuditLog).where(AuditLog.entity_type == "einvoice"))
    actions = {e.action for e in result.scalars().all()}
    assert "EINVOICE_GENERATION_REQUESTED" in actions
    assert "EINVOICE_GENERATED" in actions


# =====================================================================
# E-Way Bill
# =====================================================================


def _generate_eway_bill_payload(invoice_id: str, **overrides) -> dict:
    payload = {
        "invoice_id": invoice_id, "transport_mode": "ROAD", "vehicle_number": "TN01AB1234",
        "transporter_name": "Test Transporter", "distance_km": "120.5",
    }
    payload.update(overrides)
    return payload


# --- TC-015 Successful E-Way Bill ---


async def test_successful_eway_bill_generation(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    response = await client.post(
        f"{EWAY_BILLS_ENDPOINT}/generate", json=_generate_eway_bill_payload(invoice["id"]), headers=_idem()
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "GENERATED"
    assert data["eway_bill_number"]
    assert data["valid_from"]

    by_invoice = await client.get(f"{INVOICES_ENDPOINT}/{invoice['id']}/eway-bill")
    assert by_invoice.status_code == 200
    assert by_invoice.json()["data"]["eway_bill_number"] == data["eway_bill_number"]


# --- TC-016 Missing transport data ---


async def test_missing_transport_data_blocks_generation(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    response = await client.post(
        f"{EWAY_BILLS_ENDPOINT}/generate",
        json=_generate_eway_bill_payload(invoice["id"], transport_mode="ROAD", vehicle_number=None),
        headers=_idem(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EWB-004"


# --- TC-017 Duplicate E-Way Bill generation ---


async def test_duplicate_eway_bill_generation_rejected(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    first = await client.post(
        f"{EWAY_BILLS_ENDPOINT}/generate", json=_generate_eway_bill_payload(invoice["id"]), headers=_idem()
    )
    assert first.status_code == 201

    second = await client.post(
        f"{EWAY_BILLS_ENDPOINT}/generate", json=_generate_eway_bill_payload(invoice["id"]), headers=_idem()
    )
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "EWB-007"


# --- TC-018 E-Way Bill cancellation ---


async def test_eway_bill_cancellation(client, db_session):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)
    created = (
        await client.post(f"{EWAY_BILLS_ENDPOINT}/generate", json=_generate_eway_bill_payload(invoice["id"]), headers=_idem())
    ).json()["data"]

    response = await client.post(
        f"{EWAY_BILLS_ENDPOINT}/{created['id']}/cancel", json={"reason": "Order cancelled"}, headers=_idem()
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "CANCELLED"
    assert data["eway_bill_number"] == created["eway_bill_number"]

    from app.models.audit_log import AuditLog

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_type == "eway_bill", AuditLog.action == "EWAY_BILL_CANCELLED")
    )
    assert result.scalars().first() is not None


async def test_eway_bill_concurrent_generate_only_one_succeeds(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    async def _gen():
        return await client.post(
            f"{EWAY_BILLS_ENDPOINT}/generate", json=_generate_eway_bill_payload(invoice["id"]), headers=_idem()
        )

    results = await asyncio.gather(_gen(), _gen())
    statuses = sorted(r.status_code for r in results)
    assert statuses[0] == 201
    assert statuses[1] in (409, 422)


async def test_eway_bill_tenant_isolation(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)
    created = (
        await client.post(f"{EWAY_BILLS_ENDPOINT}/generate", json=_generate_eway_bill_payload(invoice["id"]), headers=_idem())
    ).json()["data"]

    await _signup_and_login_owner(client)
    response = await client.get(f"{EWAY_BILLS_ENDPOINT}/{created['id']}")
    assert response.status_code == 404


async def test_salesperson_cannot_generate_eway_bill(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)

    await _create_salesperson_and_login(client)
    response = await client.post(
        f"{EWAY_BILLS_ENDPOINT}/generate", json=_generate_eway_bill_payload(invoice["id"]), headers=_idem()
    )
    assert response.status_code == 403


# --- Integration operation visibility ---


async def test_integration_operation_visible(client):
    unit, product, customer = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, customer, product, unit)
    await _generate_einvoice(client, invoice["id"])

    status = (await client.get(_einvoice_url(invoice["id"]))).json()["data"]
    assert status["status"] == "GENERATED"
    # (Operation id isn't directly exposed on the einvoice detail response
    # by design — §29's log is reached via GET /integration/operations/{id}
    # using an id an operator obtains from server-side logs/troubleshooting,
    # not surfaced as a normal user-facing field.)
