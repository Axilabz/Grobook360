"""PROMPT-028 test catalogue for the offline-sync idempotency additions
(Customer/Supplier/Sales Invoice creation via `Idempotency-Key` replay).

The offline sync engine (`pwa/syncEngine.ts`) does not call a new
generic `/sync` endpoint — it replays these SAME `POST /customers`,
`POST /suppliers`, `POST /sales/invoices` endpoints, sending the
client-generated `client_transaction_id` as the `Idempotency-Key`
header. `POST /sales/invoices` already required this header
(PROMPT-015); this prompt made it OPTIONAL on Customer/Supplier
creation (previously unsupported) so all three offline-writable
entities share the same duplicate-prevention guarantee (§11/§48/AC-011).
"""

import uuid

import pytest

CUSTOMERS_ENDPOINT = "/api/v1/customers"
SUPPLIERS_ENDPOINT = "/api/v1/suppliers"
SALES_INVOICES_ENDPOINT = "/api/v1/sales/invoices"
PRODUCTS_ENDPOINT = "/api/v1/products"
UNITS_ENDPOINT = "/api/v1/units"
INVENTORY_ENDPOINT = "/api/v1/inventory"
SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"

OWNER_PASSWORD = "SecurePass123"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _unique_email() -> str:
    return f"off-{uuid.uuid4().hex[:12]}@example.com"


def _unique_sku() -> str:
    return f"SKU-{uuid.uuid4().hex[:10].upper()}"


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    from app.core.rate_limit import reset_rate_limits
    from app.core.login_lockout import reset_all

    reset_rate_limits()
    reset_all()
    yield


async def _signup_and_login_owner(client) -> dict:
    phone = _unique_phone()
    payload = {
        "organization": {"business_name": "Offline Sync Test Co", "address_line1": "1 Main St", "city": "Chennai", "state_code": "33", "pin_code": "600001", "gstin": None},
        "owner": {"phone": phone, "email": _unique_email(), "password": OWNER_PASSWORD, "confirm_password": OWNER_PASSWORD},
    }
    signup_response = await client.post(SIGNUP_ENDPOINT, json=payload, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert signup_response.status_code == 201
    login_response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": OWNER_PASSWORD})
    assert login_response.status_code == 200
    return signup_response.json()["data"]


# --- TC-022/TC-017 style: Customer quick-add idempotency ------------------


async def test_customer_creation_without_idempotency_key_still_works(client):
    """Backward compatibility: the existing online CustomerManagement UI
    never sends this header — confirms it still isn't required."""
    await _signup_and_login_owner(client)
    payload = {"name": "Online Customer", "owner_name": "Owner", "phone": _unique_phone()}
    response = await client.post(CUSTOMERS_ENDPOINT, json=payload)
    assert response.status_code == 201


async def test_duplicate_customer_sync_with_same_idempotency_key_does_not_duplicate(client):
    await _signup_and_login_owner(client)
    key = str(uuid.uuid4())
    payload = {"name": "Offline Customer", "owner_name": "Offline Customer", "phone": _unique_phone()}

    first = await client.post(CUSTOMERS_ENDPOINT, json=payload, headers={"Idempotency-Key": key})
    assert first.status_code == 201
    first_id = first.json()["data"]["id"]

    # Simulates a retried offline sync attempt (e.g. the client never
    # received the first response) with the IDENTICAL client_transaction_id.
    second = await client.post(CUSTOMERS_ENDPOINT, json=payload, headers={"Idempotency-Key": key})
    assert second.status_code == 201
    assert second.json()["data"]["id"] == first_id

    listing = await client.get(CUSTOMERS_ENDPOINT, params={"search": "Offline Customer"})
    matches = [c for c in listing.json()["data"] if c["name"] == "Offline Customer"]
    assert len(matches) == 1


async def test_same_idempotency_key_different_payload_is_rejected(client):
    await _signup_and_login_owner(client)
    key = str(uuid.uuid4())
    first = await client.post(CUSTOMERS_ENDPOINT, json={"name": "Customer A", "owner_name": "A", "phone": _unique_phone()}, headers={"Idempotency-Key": key})
    assert first.status_code == 201

    second = await client.post(CUSTOMERS_ENDPOINT, json={"name": "Customer B", "owner_name": "B", "phone": _unique_phone()}, headers={"Idempotency-Key": key})
    assert second.status_code == 409


# --- TC-024 style: Supplier quick-add idempotency --------------------------


async def test_duplicate_supplier_sync_with_same_idempotency_key_does_not_duplicate(client):
    await _signup_and_login_owner(client)
    key = str(uuid.uuid4())
    payload = {"name": "Offline Supplier", "contact_person": "Offline Supplier", "phone": _unique_phone(), "email": _unique_email()}

    first = await client.post(SUPPLIERS_ENDPOINT, json=payload, headers={"Idempotency-Key": key})
    assert first.status_code == 201
    first_id = first.json()["data"]["id"]

    second = await client.post(SUPPLIERS_ENDPOINT, json=payload, headers={"Idempotency-Key": key})
    assert second.status_code == 201
    assert second.json()["data"]["id"] == first_id


async def test_supplier_creation_without_idempotency_key_still_works(client):
    await _signup_and_login_owner(client)
    payload = {"name": "Online Supplier", "contact_person": "Contact", "phone": _unique_phone(), "email": _unique_email()}
    response = await client.post(SUPPLIERS_ENDPOINT, json=payload)
    assert response.status_code == 201


# --- TC-017/TC-012/TC-013: offline Sales Invoice sync idempotency + numbering


async def test_duplicate_offline_invoice_sync_assigns_one_final_invoice_number(client):
    """Simulates the offline workflow end to end: the client generates a
    client_transaction_id once, retries the SAME sync request (as if the
    first response was lost), and must get back the SAME
    server-authoritative invoice number both times — never two invoices,
    never two numbers consumed (§11/§12/§28/AC-006/AC-011)."""
    await _signup_and_login_owner(client)
    unit = (await client.post(UNITS_ENDPOINT, json={"code": "PCS", "name": "Pieces"})).json()["data"]
    product = (
        await client.post(
            PRODUCTS_ENDPOINT,
            json={"sku": _unique_sku(), "name": "Offline Test Product", "base_uom_id": unit["id"], "gst_rate": "18", "cost_price": "50", "selling_price": "100", "mrp": "120"},
        )
    ).json()["data"]
    customer = (await client.post(CUSTOMERS_ENDPOINT, json={"name": "Sync Test Customer", "owner_name": "Owner", "phone": _unique_phone()})).json()["data"]
    await client.post(f"{INVENTORY_ENDPOINT}/opening-stock", json={"product_id": product["id"], "quantity": "100", "uom_id": unit["id"]}, headers={"Idempotency-Key": str(uuid.uuid4())})

    client_transaction_id = str(uuid.uuid4())
    payload = {"customer_id": customer["id"], "lines": [{"product_id": product["id"], "quantity": "5", "uom_id": unit["id"], "unit_price": "100"}]}

    first = await client.post(SALES_INVOICES_ENDPOINT, json=payload, headers={"Idempotency-Key": client_transaction_id})
    assert first.status_code == 201
    first_data = first.json()["data"]
    assert first_data["invoice_number"] is not None
    assert not first_data["invoice_number"].startswith("OFF-")  # server-authoritative, never a temp reference

    # Retry — same client_transaction_id, same payload (an offline device
    # retrying because it never received the first ack).
    second = await client.post(SALES_INVOICES_ENDPOINT, json=payload, headers={"Idempotency-Key": client_transaction_id})
    assert second.status_code == 201
    second_data = second.json()["data"]
    assert second_data["id"] == first_data["id"]
    assert second_data["invoice_number"] == first_data["invoice_number"]


async def test_offline_invoice_sync_creates_draft_not_posted(client):
    """§32: accounting/GST processing must only happen after the server
    POSTS the invoice — sync (create) alone must leave it in DRAFT with
    no accounting/GST reference populated yet."""
    await _signup_and_login_owner(client)
    unit = (await client.post(UNITS_ENDPOINT, json={"code": "PCS", "name": "Pieces"})).json()["data"]
    product = (
        await client.post(
            PRODUCTS_ENDPOINT,
            json={"sku": _unique_sku(), "name": "Offline Draft Product", "base_uom_id": unit["id"], "gst_rate": "18", "cost_price": "50", "selling_price": "100", "mrp": "120"},
        )
    ).json()["data"]
    customer = (await client.post(CUSTOMERS_ENDPOINT, json={"name": "Draft Test Customer", "owner_name": "Owner", "phone": _unique_phone()})).json()["data"]
    await client.post(f"{INVENTORY_ENDPOINT}/opening-stock", json={"product_id": product["id"], "quantity": "100", "uom_id": unit["id"]}, headers={"Idempotency-Key": str(uuid.uuid4())})

    payload = {"customer_id": customer["id"], "lines": [{"product_id": product["id"], "quantity": "1", "uom_id": unit["id"], "unit_price": "100"}]}
    created = await client.post(SALES_INVOICES_ENDPOINT, json=payload, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert created.status_code == 201
    data = created.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["accounting_posting_reference"] is None
    assert data["gst_transaction_reference"] is None
