"""PROMPT-022 test catalogue for Purchase Invoice Management
(/api/v1/purchase/invoices, plus the new PO-linked endpoints on
/api/v1/purchase/orders).

Most of the core PI workflow (create direct/from-GR, draft/edit/post,
GST calc, GR-eligibility tracking, DIRECT-vs-GR stock branching,
idempotency, concurrency, RBAC, tenant isolation) was already built and
tested in PROMPT-019's own `test_purchase_foundation.py`. This file
covers ONLY the genuinely new PROMPT-022 surface area: PO-linked
invoicing ("Supported Flow 2", including multi-GR consolidation),
supplier_invoice_date/due_date fields, the system-determined
`stock_impact` field, per-line stock-movement visibility, the
duplicate-supplier-invoice-number warning, `/related-documents` and
`/audit-history`, and — the main new feature — POSTED-invoice
cancellation with a compensating Stock OUT reversal (DIRECT invoices)
or bookkeeping-only release (GR/PO-sourced invoices).
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

ORDERS_ENDPOINT = "/api/v1/purchase/orders"
RECEIPTS_ENDPOINT = "/api/v1/purchase/goods-receipts"
INVOICES_ENDPOINT = "/api/v1/purchase/invoices"
RETURNS_ENDPOINT = "/api/v1/purchase/returns"
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
    return f"pim-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "PI Management Test Co", "address_line1": "1 Main St", "city": "Chennai",
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


async def _create_posted_direct_invoice(client, supplier, product, unit, quantity: str = "10") -> dict:
    created = await client.post(
        INVOICES_ENDPOINT,
        json={"supplier_id": supplier["id"], "lines": [{"product_id": product["id"], "quantity": quantity, "uom_id": unit["id"], "unit_price": "50"}]},
        headers=_idem(),
    )
    assert created.status_code == 201
    invoice = created.json()["data"]
    posted = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    return posted.json()["data"]


# --- §5/§6/§13: supplier invoice date / due date header fields ---


async def test_create_direct_invoice_with_supplier_invoice_date_and_due_date(client):
    unit, product, supplier = await _setup_basic(client)
    response = await client.post(
        INVOICES_ENDPOINT,
        json={
            "supplier_id": supplier["id"], "supplier_invoice_number": "ABC/2026/00125", "supplier_invoice_date": "2026-09-01",
            "due_date": "2026-10-01", "lines": [{"product_id": product["id"], "quantity": "10", "uom_id": unit["id"], "unit_price": "50"}],
        },
        headers=_idem(),
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["supplier_invoice_number"] == "ABC/2026/00125"
    assert data["supplier_invoice_date"] == "2026-09-01"
    assert data["due_date"] == "2026-10-01"


# --- §7: duplicate supplier invoice number — non-blocking warning ---


async def test_duplicate_supplier_invoice_number_is_a_warning_not_a_rejection(client):
    unit, product, supplier = await _setup_basic(client)
    payload = {
        "supplier_id": supplier["id"], "supplier_invoice_number": "DUP-001",
        "lines": [{"product_id": product["id"], "quantity": "5", "uom_id": unit["id"], "unit_price": "50"}],
    }
    first = await client.post(INVOICES_ENDPOINT, json=payload, headers=_idem())
    assert first.status_code == 201
    assert first.json()["data"]["duplicate_supplier_invoice_warning"] is False

    second = await client.post(INVOICES_ENDPOINT, json=payload, headers=_idem())
    assert second.status_code == 201  # NOT rejected — uniqueness policy is an Open Decision
    assert second.json()["data"]["duplicate_supplier_invoice_warning"] is True


# --- §12/§46: system-determined stock_impact field ---


async def test_stock_impact_field_direct_vs_gr_based(client):
    unit, product, supplier = await _setup_basic(client)

    direct_created = await client.post(
        INVOICES_ENDPOINT, json={"supplier_id": supplier["id"], "lines": [{"product_id": product["id"], "quantity": "5", "uom_id": unit["id"], "unit_price": "50"}]},
        headers=_idem(),
    )
    assert direct_created.json()["data"]["stock_impact"] == "STOCK_IN_REQUIRED"

    order = await _create_confirmed_po(client, supplier, product, unit, "20")
    receipt = await _create_confirmed_receipt(client, order, "20")
    gr_line_id = receipt["lines"][0]["id"]
    gr_created = await client.post(
        f"{RECEIPTS_ENDPOINT}/{receipt['id']}/create-invoice", json={"lines": [{"source_goods_receipt_line_id": gr_line_id, "quantity": "20"}]}, headers=_idem(),
    )
    assert gr_created.json()["data"]["stock_impact"] == "STOCK_ALREADY_RECEIVED"


async def test_direct_invoice_exposes_stock_movement_id_once_posted(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")
    line = invoice["lines"][0]
    assert line["stock_movement_id"] is not None
    assert line["stock_movement_reversed"] is False


# --- "Supported Flow 2": PO-linked invoicing ---


async def test_po_invoiceable_items_reflects_received_minus_invoiced(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "100")
    await _create_confirmed_receipt(client, order, "60")

    response = await client.get(f"{ORDERS_ENDPOINT}/{order['id']}/invoiceable-items")
    assert response.status_code == 200
    line = response.json()["data"]["lines"][0]
    assert line["ordered_quantity"] == "100.000"
    assert line["received_quantity"] == "60.000"
    assert line["invoiced_quantity"] == "0.000"
    assert line["invoiceable_quantity"] == "60.000"


async def test_create_invoice_from_purchase_order_single_gr(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "100")
    await _create_confirmed_receipt(client, order, "60")

    po_line_id = order["lines"][0]["id"]
    response = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/create-invoice",
        json={"supplier_invoice_number": "PO-INV-001", "lines": [{"purchase_order_line_id": po_line_id, "quantity": "40"}]},
        headers=_idem(),
    )
    assert response.status_code == 201
    invoice = response.json()["data"]
    assert invoice["invoice_type"] == "PURCHASE_ORDER_PURCHASE_INVOICE"
    assert invoice["source_purchase_order_id"] == order["id"]
    assert invoice["stock_impact"] == "STOCK_ALREADY_RECEIVED"
    assert len(invoice["lines"]) == 1
    assert Decimal(invoice["lines"][0]["quantity"]) == Decimal("40")

    # No stock change from invoicing — it was already received.
    assert await _available_quantity(client, product["id"]) == "60.000"

    eligibility = await client.get(f"{ORDERS_ENDPOINT}/{order['id']}/invoiceable-items")
    assert eligibility.json()["data"]["lines"][0]["invoiced_quantity"] == "0.000"  # DRAFT — not yet posted


async def test_po_consolidated_invoice_spans_multiple_gr_lines(client):
    """§9/§18: one invoice consolidating eligible quantity across TWO
    confirmed Goods Receipts under the same PO — the requested quantity
    is fanned out into two purchase_invoice_line rows, one per
    contributing GR line."""
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "100")
    await _create_confirmed_receipt(client, order, "40")
    await _create_confirmed_receipt(client, order, "35")

    po_line_id = order["lines"][0]["id"]
    response = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/create-invoice",
        json={"lines": [{"purchase_order_line_id": po_line_id, "quantity": "75"}]},
        headers=_idem(),
    )
    assert response.status_code == 201
    invoice = response.json()["data"]
    assert len(invoice["lines"]) == 2  # fanned out across both GRs
    total_invoiced = sum(Decimal(line["quantity"]) for line in invoice["lines"])
    assert total_invoiced == Decimal("75")

    posted = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    assert await _available_quantity(client, product["id"]) == "75.000"  # unchanged by posting — already received


async def test_po_invoice_over_invoicing_rejected(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "50")
    await _create_confirmed_receipt(client, order, "20")

    po_line_id = order["lines"][0]["id"]
    response = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/create-invoice", json={"lines": [{"purchase_order_line_id": po_line_id, "quantity": "30"}]}, headers=_idem(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PINV-004"


async def test_po_and_gr_invoicing_share_one_invoiced_quantity_counter(client):
    """INVARIANT 5: one physical receipt must not be counted twice —
    invoicing part of a GR's quantity directly (GR-based) and the rest
    via the PO-consolidated flow must together never exceed what was
    actually received."""
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "100")
    receipt = await _create_confirmed_receipt(client, order, "50")

    gr_line_id = receipt["lines"][0]["id"]
    gr_invoice = await client.post(
        f"{RECEIPTS_ENDPOINT}/{receipt['id']}/create-invoice", json={"lines": [{"source_goods_receipt_line_id": gr_line_id, "quantity": "30"}]}, headers=_idem(),
    )
    assert gr_invoice.status_code == 201
    gr_invoice_data = gr_invoice.json()["data"]
    # invoiced_quantity is only incremented when the invoice is POSTED, not
    # at DRAFT creation — post it so the shared counter actually moves.
    gr_invoice_posted = await client.post(
        f"{INVOICES_ENDPOINT}/{gr_invoice_data['id']}/post", json={"expected_row_version": gr_invoice_data["row_version"]}, headers=_idem(),
    )
    assert gr_invoice_posted.status_code == 200

    # Only 20 units of the same GR remain invoiceable now — attempting to
    # PO-consolidate-invoice all 50 must be rejected.
    po_line_id = order["lines"][0]["id"]
    over_attempt = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/create-invoice", json={"lines": [{"purchase_order_line_id": po_line_id, "quantity": "50"}]}, headers=_idem(),
    )
    assert over_attempt.status_code == 422

    exact_attempt = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/create-invoice", json={"lines": [{"purchase_order_line_id": po_line_id, "quantity": "20"}]}, headers=_idem(),
    )
    assert exact_attempt.status_code == 201


# --- §36/§47 related documents ---


async def test_related_documents_for_po_consolidated_invoice(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "100")
    await _create_confirmed_receipt(client, order, "40")
    await _create_confirmed_receipt(client, order, "30")

    po_line_id = order["lines"][0]["id"]
    created = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/create-invoice", json={"lines": [{"purchase_order_line_id": po_line_id, "quantity": "70"}]}, headers=_idem(),
    )
    invoice = created.json()["data"]

    response = await client.get(f"{INVOICES_ENDPOINT}/{invoice['id']}/related-documents")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source_purchase_order_id"] == order["id"]
    assert len(data["goods_receipts"]) == 2
    assert data["purchase_returns"] == []


async def test_related_documents_cross_tenant_returns_404(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "5")

    await _signup_and_login_owner(client)  # tenant B
    response = await client.get(f"{INVOICES_ENDPOINT}/{invoice['id']}/related-documents")
    assert response.status_code == 404


# --- §51 audit history ---


async def test_audit_history_records_lifecycle(client):
    unit, product, supplier = await _setup_basic(client)
    created = await client.post(
        INVOICES_ENDPOINT, json={"supplier_id": supplier["id"], "lines": [{"product_id": product["id"], "quantity": "5", "uom_id": unit["id"], "unit_price": "50"}]},
        headers=_idem(),
    )
    invoice = created.json()["data"]
    posted = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert posted.status_code == 200

    response = await client.get(f"{INVOICES_ENDPOINT}/{invoice['id']}/audit-history")
    assert response.status_code == 200
    actions = [e["action"] for e in response.json()["data"]["events"]]
    assert "PURCHASE_INVOICE_CREATED" in actions
    assert "PURCHASE_INVOICE_POSTED" in actions
    assert actions.index("PURCHASE_INVOICE_CREATED") < actions.index("PURCHASE_INVOICE_POSTED")


async def test_salesperson_cannot_view_related_documents_or_audit_or_invoiceable_items(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "5")
    order = await _create_confirmed_po(client, supplier, product, unit, "10")

    await _create_salesperson_and_login(client)
    assert (await client.get(f"{INVOICES_ENDPOINT}/{invoice['id']}/related-documents")).status_code == 403
    assert (await client.get(f"{INVOICES_ENDPOINT}/{invoice['id']}/audit-history")).status_code == 403
    assert (await client.get(f"{ORDERS_ENDPOINT}/{order['id']}/invoiceable-items")).status_code == 403


# --- §33-35/INVARIANT 7/8: POSTED-invoice cancellation with reversal ---


async def test_cancel_posted_direct_invoice_creates_compensating_stock_out(client, db_session):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "20")
    assert await _available_quantity(client, product["id"]) == "20.000"

    response = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/cancel", json={"expected_row_version": invoice["row_version"]})
    assert response.status_code == 200
    cancelled = response.json()["data"]
    assert cancelled["status"] == "CANCELLED"

    assert await _available_quantity(client, product["id"]) == "0.000"

    from app.models.stock_ledger_entry import StockLedgerEntry

    result = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"])))
    entries = result.scalars().all()
    movement_types = sorted(e.movement_type for e in entries)
    assert movement_types == ["STOCK_IN", "STOCK_OUT"]  # original STOCK_IN never edited/deleted


async def test_cancel_posted_gr_based_invoice_does_not_touch_stock(client):
    """§35: cancelling a GR-based invoice must NEVER create a Stock OUT
    — the source GR remains the physical receipt. Only the bookkeeping
    claim on the GR line's invoiced_quantity is released."""
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "20")
    receipt = await _create_confirmed_receipt(client, order, "20")
    assert await _available_quantity(client, product["id"]) == "20.000"

    gr_line_id = receipt["lines"][0]["id"]
    created = await client.post(
        f"{RECEIPTS_ENDPOINT}/{receipt['id']}/create-invoice", json={"lines": [{"source_goods_receipt_line_id": gr_line_id, "quantity": "20"}]}, headers=_idem(),
    )
    invoice = created.json()["data"]
    posted = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    posted_invoice = posted.json()["data"]

    response = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/cancel", json={"expected_row_version": posted_invoice["row_version"]})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"

    # Stock unaffected — the GR still owns the physical receipt.
    assert await _available_quantity(client, product["id"]) == "20.000"

    # The invoiced quantity claim was released — invoiceable again.
    eligibility = await client.get(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/invoice-eligibility")
    assert eligibility.json()["data"]["lines"][0]["invoiceable_quantity"] == "20.000"


async def test_cancel_posted_invoice_blocked_by_downstream_return(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "20")

    invoice_line_id = invoice["lines"][0]["id"]
    ret = await client.post(
        RETURNS_ENDPOINT,
        json={"source_purchase_invoice_id": invoice["id"], "return_reason": "DAMAGED", "lines": [{"source_purchase_invoice_line_id": invoice_line_id, "quantity": "5"}]},
        headers=_idem(),
    )
    assert ret.status_code == 201
    purchase_return = ret.json()["data"]
    confirmed_return = await client.post(f"{RETURNS_ENDPOINT}/{purchase_return['id']}/confirm", json={"expected_row_version": purchase_return["row_version"]}, headers=_idem())
    assert confirmed_return.status_code == 200

    response = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/cancel", json={"expected_row_version": invoice["row_version"]})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PINV-008"

    # Stock untouched by the rejected cancellation.
    assert await _available_quantity(client, product["id"]) == "15.000"


async def test_cancel_posted_direct_invoice_blocked_when_stock_already_consumed(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "20")
    assert await _available_quantity(client, product["id"]) == "20.000"

    adjust_response = await client.post(
        f"{INVENTORY_ENDPOINT}/adjustments",
        json={"product_id": product["id"], "direction": "OUT", "quantity": "15", "uom_id": unit["id"], "reason": "Test consumption"},
        headers=_idem(),
    )
    assert adjust_response.status_code == 201
    assert await _available_quantity(client, product["id"]) == "5.000"

    response = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/cancel", json={"expected_row_version": invoice["row_version"]})
    assert response.status_code == 409

    assert await _available_quantity(client, product["id"]) == "5.000"
    detail = await client.get(f"{INVOICES_ENDPOINT}/{invoice['id']}")
    assert detail.json()["data"]["status"] == "POSTED"


async def test_double_cancel_posted_invoice_rejected(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "20")

    first = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/cancel", json={"expected_row_version": invoice["row_version"]})
    assert first.status_code == 200

    second = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/cancel", json={"expected_row_version": invoice["row_version"]})
    assert second.status_code in (409, 412, 422)

    assert await _available_quantity(client, product["id"]) == "0.000"


async def test_unauthorized_cancellation_rejected(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "5")

    await _create_salesperson_and_login(client)
    response = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/cancel", json={"expected_row_version": invoice["row_version"]})
    assert response.status_code == 403
