"""PROMPT-020 test catalogue for Purchase Order Management
(/api/v1/purchase/orders).

Most of the core PO workflow (create/confirm/cancel, ordered/received/
remaining tracking, partial receiving, over-receipt prevention,
concurrency, stock-impact, cross-tenant isolation, RBAC) was already
built and tested in PROMPT-019's `test_purchase_foundation.py`. This
file covers ONLY the genuinely new PROMPT-020 surface area: the new
header fields (supplier_reference/expected_delivery_date/payment_terms/
delivery_terms), the new `/related-documents`, `/receiving-summary`,
and `/audit-history` endpoints, and idempotent duplicate confirm/cancel
behavior (TC-027/028).
"""

import uuid

import pytest

ORDERS_ENDPOINT = "/api/v1/purchase/orders"
RECEIPTS_ENDPOINT = "/api/v1/purchase/goods-receipts"
UNITS_ENDPOINT = "/api/v1/units"
PRODUCTS_ENDPOINT = "/api/v1/products"
SUPPLIERS_ENDPOINT = "/api/v1/suppliers"
SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"
USERS_ENDPOINT = "/api/v1/users"
RESET_ENDPOINT = "/api/v1/auth/reset-password"

OWNER_PASSWORD = "SecurePass123"
SALESPERSON_PASSWORD = "AnotherSecurePass456"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _unique_email() -> str:
    return f"pom-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "PO Management Test Co", "address_line1": "1 Main St", "city": "Chennai",
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


async def _create_supplier(client, **overrides) -> dict:
    payload = {"name": "Test Supplier", "contact_person": "Contact", "phone": _unique_phone(), "email": _unique_email()}
    payload.update(overrides)
    response = await client.post(SUPPLIERS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


async def _setup_basic(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    product = await _create_product(client, unit["id"])
    supplier = await _create_supplier(client)
    return unit, product, supplier


def _po_payload(supplier_id: str, product_id: str, uom_id: str, quantity: str = "100", **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "lines": [{"product_id": product_id, "quantity": quantity, "uom_id": uom_id, "unit_price": "50"}],
    }
    payload.update(overrides)
    return payload


async def _create_confirmed_po(client, supplier, product, unit, quantity: str = "100", **overrides) -> dict:
    created = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"], quantity, **overrides), headers=_idem())
    assert created.status_code == 201
    order = created.json()["data"]
    confirmed = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]})
    assert confirmed.status_code == 200
    return confirmed.json()["data"]


async def _create_confirmed_receipt(client, order: dict, quantity: str) -> dict:
    po_line_id = order["lines"][0]["id"]
    created = await client.post(
        RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": quantity}]}, headers=_idem()
    )
    assert created.status_code == 201
    receipt = created.json()["data"]
    confirmed = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/confirm", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert confirmed.status_code == 200
    return confirmed.json()["data"]


# --- §4 header fields ---


async def test_create_po_with_new_header_fields(client):
    unit, product, supplier = await _setup_basic(client)
    payload = _po_payload(
        supplier["id"], product["id"], unit["id"], "20",
        supplier_reference="SUP-REF-001", expected_delivery_date="2026-10-01",
        payment_terms="Net 30", delivery_terms="FOB Destination",
    )
    response = await client.post(ORDERS_ENDPOINT, json=payload, headers=_idem())
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["supplier_reference"] == "SUP-REF-001"
    assert data["expected_delivery_date"] == "2026-10-01"
    assert data["payment_terms"] == "Net 30"
    assert data["delivery_terms"] == "FOB Destination"


async def test_header_fields_are_optional(client):
    unit, product, supplier = await _setup_basic(client)
    response = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"], "10"), headers=_idem())
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["supplier_reference"] is None
    assert data["expected_delivery_date"] is None
    assert data["payment_terms"] is None
    assert data["delivery_terms"] is None


async def test_update_draft_po_header_fields(client):
    unit, product, supplier = await _setup_basic(client)
    created = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"], "10"), headers=_idem())
    order = created.json()["data"]

    response = await client.patch(
        f"{ORDERS_ENDPOINT}/{order['id']}",
        json={"supplier_reference": "UPDATED-REF", "payment_terms": "Net 15", "expected_row_version": order["row_version"]},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["supplier_reference"] == "UPDATED-REF"
    assert data["payment_terms"] == "Net 15"


# --- §19/§21/§45: ordered/received/remaining exposed on list + detail ---


async def test_list_and_detail_expose_quantity_totals(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "100")
    await _create_confirmed_receipt(client, order, "40")

    detail = await client.get(f"{ORDERS_ENDPOINT}/{order['id']}")
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["total_ordered_quantity"] == "100.000"
    assert data["total_received_quantity"] == "40.000"
    assert data["total_remaining_quantity"] == "60.000"
    assert data["lines"][0]["remaining_quantity"] == "60.000"

    listed = await client.get(ORDERS_ENDPOINT, params={"search": order["po_number"]})
    assert listed.status_code == 200
    list_row = listed.json()["data"][0]
    assert list_row["total_ordered_quantity"] == "100.000"
    assert list_row["total_received_quantity"] == "40.000"
    assert list_row["total_remaining_quantity"] == "60.000"


# --- §17/§24/§34: related documents ---


async def test_related_documents_lists_goods_receipts(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "100")
    receipt1 = await _create_confirmed_receipt(client, order, "40")
    receipt2 = await _create_confirmed_receipt(client, order, "30")

    response = await client.get(f"{ORDERS_ENDPOINT}/{order['id']}/related-documents")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["purchase_order_id"] == order["id"]
    grn_numbers = {gr["grn_number"] for gr in data["goods_receipts"]}
    assert grn_numbers == {receipt1["grn_number"], receipt2["grn_number"]}
    assert data["purchase_invoices"] == []


async def test_related_documents_includes_purchase_invoice_from_gr(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "20")
    receipt = await _create_confirmed_receipt(client, order, "20")

    gr_line_id = receipt["lines"][0]["id"]
    created = await client.post(
        f"{RECEIPTS_ENDPOINT}/{receipt['id']}/create-invoice", json={"lines": [{"source_goods_receipt_line_id": gr_line_id, "quantity": "20"}]}, headers=_idem()
    )
    assert created.status_code == 201
    invoice = created.json()["data"]

    response = await client.get(f"{ORDERS_ENDPOINT}/{order['id']}/related-documents")
    data = response.json()["data"]
    assert len(data["purchase_invoices"]) == 1
    assert data["purchase_invoices"][0]["id"] == invoice["id"]
    assert data["purchase_invoices"][0]["source_goods_receipt_id"] == receipt["id"]


async def test_related_documents_empty_for_new_po(client):
    unit, product, supplier = await _setup_basic(client)
    created = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"], "10"), headers=_idem())
    order = created.json()["data"]

    response = await client.get(f"{ORDERS_ENDPOINT}/{order['id']}/related-documents")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["goods_receipts"] == []
    assert data["purchase_invoices"] == []


# --- §30 receiving summary ---


async def test_receiving_summary(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "50")
    await _create_confirmed_receipt(client, order, "20")

    response = await client.get(f"{ORDERS_ENDPOINT}/{order['id']}/receiving-summary")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["po_number"] == order["po_number"]
    assert data["status"] == "PARTIALLY_RECEIVED"
    assert data["total_ordered_quantity"] == "50.000"
    assert data["total_received_quantity"] == "20.000"
    assert data["total_remaining_quantity"] == "30.000"
    assert len(data["lines"]) == 1
    line = data["lines"][0]
    assert line["ordered_quantity"] == "50.000"
    assert line["received_quantity"] == "20.000"
    assert line["remaining_quantity"] == "30.000"


# --- §34/§38 audit history ---


async def test_audit_history_records_lifecycle_events(client):
    unit, product, supplier = await _setup_basic(client)
    created = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"], "10"), headers=_idem())
    order = created.json()["data"]

    confirmed = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]})
    confirmed_order = confirmed.json()["data"]

    response = await client.get(f"{ORDERS_ENDPOINT}/{order['id']}/audit-history")
    assert response.status_code == 200
    events = response.json()["data"]["events"]
    actions = [e["action"] for e in events]
    assert "PURCHASE_ORDER_CREATED" in actions
    assert "PURCHASE_ORDER_CONFIRMED" in actions
    # chronological order
    assert actions.index("PURCHASE_ORDER_CREATED") < actions.index("PURCHASE_ORDER_CONFIRMED")

    cancel_target = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"], "5"), headers=_idem())
    draft_order = cancel_target.json()["data"]
    await client.post(f"{ORDERS_ENDPOINT}/{draft_order['id']}/cancel", json={"expected_row_version": draft_order["row_version"]})
    cancel_history = await client.get(f"{ORDERS_ENDPOINT}/{draft_order['id']}/audit-history")
    cancel_actions = [e["action"] for e in cancel_history.json()["data"]["events"]]
    assert "PURCHASE_ORDER_CANCELLED" in cancel_actions


async def test_audit_history_cross_tenant_returns_404(client):
    unit, product, supplier = await _setup_basic(client)
    created = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"], "10"), headers=_idem())
    order_id = created.json()["data"]["id"]

    await _signup_and_login_owner(client)  # tenant B
    response = await client.get(f"{ORDERS_ENDPOINT}/{order_id}/audit-history")
    assert response.status_code == 404


# --- §29/TC-027/028: idempotent confirm/cancel (no duplicate state) ---


async def test_duplicate_confirmation_request_rejected_no_duplicate_state(client):
    unit, product, supplier = await _setup_basic(client)
    created = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"], "10"), headers=_idem())
    order = created.json()["data"]

    first = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]})
    assert first.status_code == 200
    confirmed = first.json()["data"]
    assert confirmed["status"] == "CONFIRMED"

    # A second confirmation attempt with the same (now-stale) row_version
    # is safely rejected — no duplicate PO number, no duplicate CONFIRMED
    # transition, no duplicate audit event.
    second = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]})
    assert second.status_code in (409, 412, 422)

    final = await client.get(f"{ORDERS_ENDPOINT}/{order['id']}")
    assert final.json()["data"]["status"] == "CONFIRMED"
    assert final.json()["data"]["po_number"] == confirmed["po_number"]

    history = await client.get(f"{ORDERS_ENDPOINT}/{order['id']}/audit-history")
    confirm_events = [e for e in history.json()["data"]["events"] if e["action"] == "PURCHASE_ORDER_CONFIRMED"]
    assert len(confirm_events) == 1


async def test_duplicate_cancellation_request_rejected_no_duplicate_state(client):
    unit, product, supplier = await _setup_basic(client)
    created = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"], "10"), headers=_idem())
    order = created.json()["data"]

    first = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/cancel", json={"expected_row_version": order["row_version"]})
    assert first.status_code == 200
    assert first.json()["data"]["status"] == "CANCELLED"

    second = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/cancel", json={"expected_row_version": order["row_version"]})
    assert second.status_code in (409, 412, 422)

    history = await client.get(f"{ORDERS_ENDPOINT}/{order['id']}/audit-history")
    cancel_events = [e for e in history.json()["data"]["events"] if e["action"] == "PURCHASE_ORDER_CANCELLED"]
    assert len(cancel_events) == 1


# --- §37/§7 RBAC on the new endpoints ---


async def test_salesperson_cannot_view_related_documents_or_summary_or_audit(client):
    unit, product, supplier = await _setup_basic(client)
    created = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"], "10"), headers=_idem())
    order_id = created.json()["data"]["id"]

    await _create_salesperson_and_login(client)
    assert (await client.get(f"{ORDERS_ENDPOINT}/{order_id}/related-documents")).status_code == 403
    assert (await client.get(f"{ORDERS_ENDPOINT}/{order_id}/receiving-summary")).status_code == 403
    assert (await client.get(f"{ORDERS_ENDPOINT}/{order_id}/audit-history")).status_code == 403


# --- §22: fully received PO cannot be over-received further (regression guard) ---


async def test_fully_received_po_rejects_further_receipt(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "20")
    receipt = await _create_confirmed_receipt(client, order, "20")

    po_line_id = order["lines"][0]["id"]
    response = await client.post(
        RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "1"}]}, headers=_idem()
    )
    assert response.status_code == 422

    summary = await client.get(f"{ORDERS_ENDPOINT}/{order['id']}/receiving-summary")
    assert summary.json()["data"]["status"] == "FULLY_RECEIVED"
    assert summary.json()["data"]["total_remaining_quantity"] == "0.000"
