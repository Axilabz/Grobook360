"""PROMPT-021 test catalogue for Goods Receipt Management
(/api/v1/purchase/goods-receipts).

Most of the core GR workflow (create/confirm/cancel-draft, ordered/
received/remaining tracking, partial receiving, over-receipt prevention,
concurrency, stock-IN-on-confirm, idempotency, cross-tenant isolation,
RBAC) was already built and tested in PROMPT-019's own
`test_purchase_foundation.py`. This file covers ONLY the genuinely new
PROMPT-021 surface area: the new `supplier_delivery_note` header field,
stock-movement visibility on line items, the new `/related-documents`
and `/audit-history` endpoints, and — the main new feature — confirmed-
GR cancellation with a compensating Stock OUT reversal (§23-25).
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

ORDERS_ENDPOINT = "/api/v1/purchase/orders"
RECEIPTS_ENDPOINT = "/api/v1/purchase/goods-receipts"
UNITS_ENDPOINT = "/api/v1/units"
PRODUCTS_ENDPOINT = "/api/v1/products"
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
    return f"grm-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "GR Management Test Co", "address_line1": "1 Main St", "city": "Chennai",
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


async def _available_quantity(client, product_id: str) -> str:
    response = await client.get(f"{INVENTORY_ENDPOINT}/availability/{product_id}")
    return response.json()["data"]["available_quantity"]


def _po_payload(supplier_id: str, product_id: str, uom_id: str, quantity: str = "100", **overrides) -> dict:
    payload = {"supplier_id": supplier_id, "lines": [{"product_id": product_id, "quantity": quantity, "uom_id": uom_id, "unit_price": "50"}]}
    payload.update(overrides)
    return payload


async def _create_confirmed_po(client, supplier, product, unit, quantity: str = "100") -> dict:
    created = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"], quantity), headers=_idem())
    assert created.status_code == 201
    order = created.json()["data"]
    confirmed = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]})
    assert confirmed.status_code == 200
    return confirmed.json()["data"]


async def _create_confirmed_receipt(client, order: dict, quantity: str, **overrides) -> dict:
    po_line_id = order["lines"][0]["id"]
    payload = {"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": quantity}]}
    payload.update(overrides)
    created = await client.post(RECEIPTS_ENDPOINT, json=payload, headers=_idem())
    assert created.status_code == 201
    receipt = created.json()["data"]
    confirmed = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/confirm", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert confirmed.status_code == 200
    return confirmed.json()["data"]


# --- §5/§28: supplier_delivery_note header field ---


async def test_create_gr_with_supplier_delivery_note(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "20")
    po_line_id = order["lines"][0]["id"]

    response = await client.post(
        RECEIPTS_ENDPOINT,
        json={"purchase_order_id": order["id"], "supplier_delivery_note": "DN-2026-001", "lines": [{"purchase_order_line_id": po_line_id, "quantity": "10"}]},
        headers=_idem(),
    )
    assert response.status_code == 201
    assert response.json()["data"]["supplier_delivery_note"] == "DN-2026-001"


async def test_supplier_delivery_note_optional(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "10")
    po_line_id = order["lines"][0]["id"]

    response = await client.post(
        RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "5"}]}, headers=_idem(),
    )
    assert response.status_code == 201
    assert response.json()["data"]["supplier_delivery_note"] is None


async def test_update_draft_gr_supplier_delivery_note(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "10")
    po_line_id = order["lines"][0]["id"]
    created = await client.post(
        RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "5"}]}, headers=_idem(),
    )
    receipt = created.json()["data"]

    response = await client.patch(
        f"{RECEIPTS_ENDPOINT}/{receipt['id']}",
        json={"supplier_delivery_note": "DN-UPDATED", "expected_row_version": receipt["row_version"]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["supplier_delivery_note"] == "DN-UPDATED"


# --- §42 Stock Impact Visibility ---


async def test_confirmed_gr_exposes_stock_movement_id(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "20")
    receipt = await _create_confirmed_receipt(client, order, "20")

    line = receipt["lines"][0]
    assert line["stock_movement_id"] is not None
    assert line["stock_movement_reversed"] is False


async def test_draft_gr_has_no_stock_movement_id(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "10")
    po_line_id = order["lines"][0]["id"]
    created = await client.post(
        RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "5"}]}, headers=_idem(),
    )
    draft = created.json()["data"]
    assert draft["lines"][0]["stock_movement_id"] is None


# --- §18/§34/§41 related documents ---


async def test_related_documents_shows_source_po(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "20")
    receipt = await _create_confirmed_receipt(client, order, "20")

    response = await client.get(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/related-documents")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source_purchase_order_id"] == order["id"]
    assert data["source_purchase_order_number"] == order["po_number"]
    assert data["purchase_invoices"] == []


async def test_related_documents_shows_linked_invoice(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "20")
    receipt = await _create_confirmed_receipt(client, order, "20")

    gr_line_id = receipt["lines"][0]["id"]
    created = await client.post(
        f"{RECEIPTS_ENDPOINT}/{receipt['id']}/create-invoice", json={"lines": [{"source_goods_receipt_line_id": gr_line_id, "quantity": "20"}]}, headers=_idem(),
    )
    assert created.status_code == 201
    invoice = created.json()["data"]

    response = await client.get(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/related-documents")
    data = response.json()["data"]
    assert len(data["purchase_invoices"]) == 1
    assert data["purchase_invoices"][0]["id"] == invoice["id"]


async def test_related_documents_cross_tenant_returns_404(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "10")
    po_line_id = order["lines"][0]["id"]
    created = await client.post(
        RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "5"}]}, headers=_idem(),
    )
    receipt_id = created.json()["data"]["id"]

    await _signup_and_login_owner(client)  # tenant B
    response = await client.get(f"{RECEIPTS_ENDPOINT}/{receipt_id}/related-documents")
    assert response.status_code == 404


# --- §46 audit history ---


async def test_audit_history_records_lifecycle(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "10")
    po_line_id = order["lines"][0]["id"]
    created = await client.post(
        RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "5"}]}, headers=_idem(),
    )
    receipt = created.json()["data"]
    confirmed = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/confirm", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert confirmed.status_code == 200

    response = await client.get(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/audit-history")
    assert response.status_code == 200
    actions = [e["action"] for e in response.json()["data"]["events"]]
    assert "GOODS_RECEIPT_CREATED" in actions
    assert "GOODS_RECEIPT_CONFIRMED" in actions
    assert actions.index("GOODS_RECEIPT_CREATED") < actions.index("GOODS_RECEIPT_CONFIRMED")


async def test_salesperson_cannot_view_related_documents_or_audit(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "10")
    po_line_id = order["lines"][0]["id"]
    created = await client.post(
        RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "5"}]}, headers=_idem(),
    )
    receipt_id = created.json()["data"]["id"]

    await _create_salesperson_and_login(client)
    assert (await client.get(f"{RECEIPTS_ENDPOINT}/{receipt_id}/related-documents")).status_code == 403
    assert (await client.get(f"{RECEIPTS_ENDPOINT}/{receipt_id}/audit-history")).status_code == 403


# --- §23-25/INVARIANT 7/8: confirmed-GR cancellation with reversal ---


async def test_cancel_confirmed_gr_creates_compensating_stock_out(client, db_session):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "50")
    receipt = await _create_confirmed_receipt(client, order, "30")

    assert await _available_quantity(client, product["id"]) == "30.000"

    response = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/cancel", json={"expected_row_version": receipt["row_version"]})
    assert response.status_code == 200
    cancelled = response.json()["data"]
    assert cancelled["status"] == "CANCELLED"

    # Stock is reversed back to 0.
    assert await _available_quantity(client, product["id"]) == "0.000"

    # The original STOCK_IN ledger entry is NEVER edited/deleted — a NEW
    # compensating STOCK_OUT entry exists alongside it (INVARIANT 7/8).
    from app.models.stock_ledger_entry import StockLedgerEntry

    result = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"])))
    entries = result.scalars().all()
    movement_types = sorted(e.movement_type for e in entries)
    assert movement_types == ["STOCK_IN", "STOCK_OUT"]
    assert len(entries) == 2

    # The line's stock_movement_reversed flag now reflects this.
    detail = await client.get(f"{RECEIPTS_ENDPOINT}/{receipt['id']}")
    assert detail.json()["data"]["lines"][0]["stock_movement_reversed"] is True


async def test_cancel_confirmed_gr_reverses_po_received_quantity(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "50")
    receipt = await _create_confirmed_receipt(client, order, "30")

    order_after_receipt = (await client.get(f"{ORDERS_ENDPOINT}/{order['id']}")).json()["data"]
    assert order_after_receipt["status"] == "PARTIALLY_RECEIVED"
    assert order_after_receipt["lines"][0]["received_quantity"] == "30.000"

    cancelled = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/cancel", json={"expected_row_version": receipt["row_version"]})
    assert cancelled.status_code == 200

    order_after_reversal = (await client.get(f"{ORDERS_ENDPOINT}/{order['id']}")).json()["data"]
    assert order_after_reversal["status"] == "CONFIRMED"
    assert order_after_reversal["lines"][0]["received_quantity"] == "0.000"
    assert order_after_reversal["total_remaining_quantity"] == "50.000"


async def test_cancel_confirmed_gr_blocked_by_downstream_invoice(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "20")
    receipt = await _create_confirmed_receipt(client, order, "20")

    gr_line_id = receipt["lines"][0]["id"]
    created = await client.post(
        f"{RECEIPTS_ENDPOINT}/{receipt['id']}/create-invoice", json={"lines": [{"source_goods_receipt_line_id": gr_line_id, "quantity": "20"}]}, headers=_idem(),
    )
    assert created.status_code == 201
    invoice = created.json()["data"]
    # invoiced_quantity is only incremented when the invoice is POSTED, not
    # at DRAFT creation — post it so the downstream dependency actually exists.
    posted = await client.post(
        f"/api/v1/purchase/invoices/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem(),
    )
    assert posted.status_code == 200

    response = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/cancel", json={"expected_row_version": receipt["row_version"]})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "GR-007"

    # Stock untouched — the rejected cancellation must not partially apply.
    assert await _available_quantity(client, product["id"]) == "20.000"


async def test_cancel_confirmed_gr_blocked_when_stock_already_consumed(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "20")
    receipt = await _create_confirmed_receipt(client, order, "20")
    assert await _available_quantity(client, product["id"]) == "20.000"

    # Simulate downstream consumption via a manual stock-out adjustment
    # (the existing PROMPT-010 adjustments endpoint) so the reversal can
    # no longer be satisfied without going negative.
    adjust_response = await client.post(
        f"{INVENTORY_ENDPOINT}/adjustments",
        json={"product_id": product["id"], "direction": "OUT", "quantity": "15", "uom_id": unit["id"], "reason": "Test consumption"},
        headers=_idem(),
    )
    assert adjust_response.status_code == 201
    assert await _available_quantity(client, product["id"]) == "5.000"

    response = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/cancel", json={"expected_row_version": receipt["row_version"]})
    assert response.status_code == 409

    # Stock and GR status remain unchanged — the failed reversal rolled back cleanly.
    assert await _available_quantity(client, product["id"]) == "5.000"
    detail = await client.get(f"{RECEIPTS_ENDPOINT}/{receipt['id']}")
    assert detail.json()["data"]["status"] == "CONFIRMED"


async def test_cancel_draft_gr_still_has_no_stock_impact(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "10")
    po_line_id = order["lines"][0]["id"]
    created = await client.post(
        RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "5"}]}, headers=_idem(),
    )
    draft = created.json()["data"]

    response = await client.post(f"{RECEIPTS_ENDPOINT}/{draft['id']}/cancel", json={"expected_row_version": draft["row_version"]})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"
    assert await _available_quantity(client, product["id"]) == "0.000"


async def test_double_cancel_confirmed_gr_rejected(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "20")
    receipt = await _create_confirmed_receipt(client, order, "20")

    first = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/cancel", json={"expected_row_version": receipt["row_version"]})
    assert first.status_code == 200

    second = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/cancel", json={"expected_row_version": receipt["row_version"]})
    assert second.status_code in (409, 412, 422)

    # Only one reversal happened.
    assert await _available_quantity(client, product["id"]) == "0.000"


async def test_unauthorized_cancellation_rejected(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "10")
    po_line_id = order["lines"][0]["id"]
    created = await client.post(
        RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "5"}]}, headers=_idem(),
    )
    receipt = created.json()["data"]

    await _create_salesperson_and_login(client)
    response = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/cancel", json={"expected_row_version": receipt["row_version"]})
    assert response.status_code == 403
