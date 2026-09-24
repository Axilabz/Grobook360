"""PROMPT-019 test catalogue for Purchase Management Foundation
(/api/v1/purchase/orders, /purchase/goods-receipts, /purchase/invoices,
/purchase/returns).

Follows the established Sales-chain test file structure. Covers §44's
core TC-001 through TC-023 scenarios (responsive UI tests TC-024/025/026
are covered separately, not in this backend suite).
"""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

ORDERS_ENDPOINT = "/api/v1/purchase/orders"
RECEIPTS_ENDPOINT = "/api/v1/purchase/goods-receipts"
INVOICES_ENDPOINT = "/api/v1/purchase/invoices"
RETURNS_ENDPOINT = "/api/v1/purchase/returns"
PRODUCTS_ENDPOINT = "/api/v1/products"
UNITS_ENDPOINT = "/api/v1/units"
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
    return f"pf-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "Purchase Foundation Test Co", "address_line1": "1 Main St", "city": "Chennai",
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


async def _create_manager_and_login(client) -> None:
    from app.services.password_recovery.provider import ConsolePasswordRecoveryProvider

    phone = _unique_phone()
    create_response = await client.post(USERS_ENDPOINT, json={"name": "Mgr", "phone": phone, "email": _unique_email(), "role": "MANAGER"})
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


def _direct_invoice_payload(supplier_id: str, product_id: str, uom_id: str, quantity: str = "10", **overrides) -> dict:
    payload = {"supplier_id": supplier_id, "lines": [{"product_id": product_id, "quantity": quantity, "uom_id": uom_id, "unit_price": "50"}]}
    payload.update(overrides)
    return payload


async def _create_posted_direct_invoice(client, supplier, product, unit, quantity: str = "10") -> dict:
    created = await client.post(INVOICES_ENDPOINT, json=_direct_invoice_payload(supplier["id"], product["id"], unit["id"], quantity), headers=_idem())
    assert created.status_code == 201
    invoice = created.json()["data"]
    posted = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    return posted.json()["data"]


# --- TC-001/002/003: Purchase Order create/confirm/no-stock-change ---


async def test_create_valid_draft_po(client):
    unit, product, supplier = await _setup_basic(client)
    response = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"]), headers=_idem())
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["po_number"].startswith("PO-")


async def test_po_creation_does_not_change_stock(client):
    unit, product, supplier = await _setup_basic(client)
    before = await _available_quantity(client, product["id"])
    await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"]), headers=_idem())
    after = await _available_quantity(client, product["id"])
    assert before == after == "0.000"


async def test_po_confirmation_does_not_change_stock(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit)
    assert order["status"] == "CONFIRMED"
    assert await _available_quantity(client, product["id"]) == "0.000"

    from app.models.stock_ledger_entry import StockLedgerEntry

    # (no db_session fixture needed here — availability check above is
    # sufficient proof of §10's "PO never moves stock" rule)


async def test_cross_tenant_po_access(client):
    unit, product, supplier = await _setup_basic(client)
    created = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"]), headers=_idem())
    order_id = created.json()["data"]["id"]

    await _signup_and_login_owner(client)  # tenant B
    response = await client.get(f"{ORDERS_ENDPOINT}/{order_id}")
    assert response.status_code == 404


async def test_salesperson_cannot_view_purchase_orders(client):
    """FR Table 7: Purchase is Owner/Manager only — Salesperson gets
    ZERO purchase permissions in this foundation."""
    await _setup_basic(client)
    await _create_salesperson_and_login(client)
    response = await client.get(ORDERS_ENDPOINT)
    assert response.status_code == 403


# --- TC-004/005/006/007/008: Goods Receipt / partial receiving / over-receipt ---


async def test_gr_confirmation_creates_stock_in(client, db_session):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "100")

    receipt = await _create_confirmed_receipt(client, order, "40")
    assert receipt["status"] == "CONFIRMED"
    assert await _available_quantity(client, product["id"]) == "40.000"

    from app.models.stock_ledger_entry import StockLedgerEntry

    result = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"]), StockLedgerEntry.movement_type == "STOCK_IN"))
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].quantity == Decimal("40.000")


async def test_partial_receiving_cumulative(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "100")

    await _create_confirmed_receipt(client, order, "40")
    assert await _available_quantity(client, product["id"]) == "40.000"

    order_after = (await client.get(f"{ORDERS_ENDPOINT}/{order['id']}")).json()["data"]
    assert order_after["status"] == "PARTIALLY_RECEIVED"
    assert order_after["lines"][0]["received_quantity"] == "40.000"

    await _create_confirmed_receipt(client, order, "30")
    assert await _available_quantity(client, product["id"]) == "70.000"

    order_final = (await client.get(f"{ORDERS_ENDPOINT}/{order['id']}")).json()["data"]
    assert order_final["status"] == "PARTIALLY_RECEIVED"
    assert order_final["lines"][0]["received_quantity"] == "70.000"


async def test_full_receipt_marks_po_fully_received(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "50")
    await _create_confirmed_receipt(client, order, "50")

    order_after = (await client.get(f"{ORDERS_ENDPOINT}/{order['id']}")).json()["data"]
    assert order_after["status"] == "FULLY_RECEIVED"


async def test_over_receipt_prevented(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "50")
    po_line_id = order["lines"][0]["id"]

    response = await client.post(
        RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "60"}]}, headers=_idem()
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "GR-004"


async def test_duplicate_gr_confirmation_rejected(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "50")
    po_line_id = order["lines"][0]["id"]
    created = await client.post(RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "20"}]}, headers=_idem())
    receipt = created.json()["data"]

    first = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/confirm", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert first.status_code == 200
    confirmed = first.json()["data"]

    second = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/confirm", json={"expected_row_version": confirmed["row_version"]}, headers=_idem())
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "GR-002"


async def test_idempotent_gr_confirm_retry(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "50")
    po_line_id = order["lines"][0]["id"]
    created = await client.post(RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "20"}]}, headers=_idem())
    receipt = created.json()["data"]
    key = str(uuid.uuid4())

    first = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/confirm", json={"expected_row_version": receipt["row_version"]}, headers={"Idempotency-Key": key})
    assert first.status_code == 200
    second = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/confirm", json={"expected_row_version": receipt["row_version"]}, headers={"Idempotency-Key": key})
    assert second.status_code == 200
    assert second.json()["data"] == first.json()["data"]
    assert await _available_quantity(client, product["id"]) == "20.000"  # only ONE stock-in applied


# --- TC-019 Concurrent receipt ---


async def test_concurrent_receipt_only_one_succeeds(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "50")
    po_line_id = order["lines"][0]["id"]

    async def _create_and_confirm(qty: str):
        created = await client.post(RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": qty}]}, headers=_idem())
        if created.status_code != 201:
            return created
        receipt = created.json()["data"]
        return await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/confirm", json={"expected_row_version": receipt["row_version"]}, headers=_idem())

    results = await asyncio.gather(_create_and_confirm("40"), _create_and_confirm("40"))
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 422]  # one succeeds (40), the other exceeds the now-10-remaining

    order_final = (await client.get(f"{ORDERS_ENDPOINT}/{order['id']}")).json()["data"]
    assert Decimal(order_final["lines"][0]["received_quantity"]) <= Decimal("50")


# --- TC-009/010/011/012: Purchase Invoice direct / from GR / no duplicate ---


async def test_direct_purchase_invoice_creates_stock_in(client, db_session):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "15")
    assert invoice["status"] == "POSTED"
    assert invoice["invoice_type"] == "DIRECT_PURCHASE_INVOICE"
    assert await _available_quantity(client, product["id"]) == "15.000"

    from app.models.stock_ledger_entry import StockLedgerEntry

    result = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"]), StockLedgerEntry.movement_type == "STOCK_IN"))
    assert len(result.scalars().all()) == 1


async def test_mandatory_no_duplicate_stock_in_from_gr_invoice(client, db_session):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "20")
    receipt = await _create_confirmed_receipt(client, order, "20")
    assert await _available_quantity(client, product["id"]) == "20.000"

    gr_line_id = receipt["lines"][0]["id"]
    created = await client.post(
        f"{RECEIPTS_ENDPOINT}/{receipt['id']}/create-invoice", json={"lines": [{"source_goods_receipt_line_id": gr_line_id, "quantity": "20"}]}, headers=_idem()
    )
    assert created.status_code == 201
    invoice = created.json()["data"]
    assert invoice["invoice_type"] == "GOODS_RECEIPT_PURCHASE_INVOICE"

    posted = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert posted.status_code == 200

    # CRITICAL: stock must remain 20, NOT double to 40.
    assert await _available_quantity(client, product["id"]) == "20.000"

    from app.models.stock_ledger_entry import StockLedgerEntry

    result = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"])))
    stock_in_entries = [e for e in result.scalars().all() if e.movement_type == "STOCK_IN"]
    assert len(stock_in_entries) == 1  # from the Goods Receipt confirm — NOT a second one from the invoice


async def test_invoice_from_unconfirmed_gr_rejected(client):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "20")
    po_line_id = order["lines"][0]["id"]
    created = await client.post(RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "10"}]}, headers=_idem())
    draft_receipt = created.json()["data"]  # never confirmed

    response = await client.get(f"{RECEIPTS_ENDPOINT}/{draft_receipt['id']}/invoice-eligibility")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PINV-007"


async def test_duplicate_purchase_invoice_posting_rejected(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")

    second = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "PINV-002"


async def test_idempotent_invoice_post_retry(client):
    unit, product, supplier = await _setup_basic(client)
    created = await client.post(INVOICES_ENDPOINT, json=_direct_invoice_payload(supplier["id"], product["id"], unit["id"], "10"), headers=_idem())
    invoice = created.json()["data"]
    key = str(uuid.uuid4())

    first = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers={"Idempotency-Key": key})
    assert first.status_code == 200
    second = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers={"Idempotency-Key": key})
    assert second.status_code == 200
    assert second.json()["data"] == first.json()["data"]
    assert await _available_quantity(client, product["id"]) == "10.000"


# --- TC-013/014/015/018: Purchase Return ---


async def test_purchase_return_creates_stock_out(client, db_session):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "20")
    assert await _available_quantity(client, product["id"]) == "20.000"

    invoice_line_id = invoice["lines"][0]["id"]
    created = await client.post(
        RETURNS_ENDPOINT,
        json={"source_purchase_invoice_id": invoice["id"], "return_reason": "DAMAGED", "lines": [{"source_purchase_invoice_line_id": invoice_line_id, "quantity": "5"}]},
        headers=_idem(),
    )
    assert created.status_code == 201
    purchase_return = created.json()["data"]
    assert purchase_return["status"] == "DRAFT"
    assert await _available_quantity(client, product["id"]) == "20.000"  # DRAFT: no stock impact yet

    confirmed = await client.post(f"{RETURNS_ENDPOINT}/{purchase_return['id']}/confirm", json={"expected_row_version": purchase_return["row_version"]}, headers=_idem())
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "CONFIRMED"

    assert await _available_quantity(client, product["id"]) == "15.000"

    from app.models.stock_ledger_entry import StockLedgerEntry

    result = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"]), StockLedgerEntry.movement_type == "STOCK_OUT"))
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].quantity == Decimal("5.000")


async def test_purchase_return_exceeding_eligible_quantity_rejected(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")
    invoice_line_id = invoice["lines"][0]["id"]

    response = await client.post(
        RETURNS_ENDPOINT,
        json={"source_purchase_invoice_id": invoice["id"], "return_reason": "DAMAGED", "lines": [{"source_purchase_invoice_line_id": invoice_line_id, "quantity": "15"}]},
        headers=_idem(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PRET-004"


async def test_duplicate_purchase_return_confirmation_rejected(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")
    invoice_line_id = invoice["lines"][0]["id"]
    created = await client.post(
        RETURNS_ENDPOINT, json={"source_purchase_invoice_id": invoice["id"], "return_reason": "DAMAGED", "lines": [{"source_purchase_invoice_line_id": invoice_line_id, "quantity": "5"}]}, headers=_idem()
    )
    purchase_return = created.json()["data"]

    first = await client.post(f"{RETURNS_ENDPOINT}/{purchase_return['id']}/confirm", json={"expected_row_version": purchase_return["row_version"]}, headers=_idem())
    assert first.status_code == 200
    confirmed = first.json()["data"]

    second = await client.post(f"{RETURNS_ENDPOINT}/{purchase_return['id']}/confirm", json={"expected_row_version": confirmed["row_version"]}, headers=_idem())
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "PRET-002"


async def test_idempotent_purchase_return_confirm_retry(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")
    invoice_line_id = invoice["lines"][0]["id"]
    created = await client.post(
        RETURNS_ENDPOINT, json={"source_purchase_invoice_id": invoice["id"], "return_reason": "DAMAGED", "lines": [{"source_purchase_invoice_line_id": invoice_line_id, "quantity": "5"}]}, headers=_idem()
    )
    purchase_return = created.json()["data"]
    key = str(uuid.uuid4())

    first = await client.post(f"{RETURNS_ENDPOINT}/{purchase_return['id']}/confirm", json={"expected_row_version": purchase_return["row_version"]}, headers={"Idempotency-Key": key})
    assert first.status_code == 200
    second = await client.post(f"{RETURNS_ENDPOINT}/{purchase_return['id']}/confirm", json={"expected_row_version": purchase_return["row_version"]}, headers={"Idempotency-Key": key})
    assert second.status_code == 200
    assert second.json()["data"] == first.json()["data"]
    assert await _available_quantity(client, product["id"]) == "5.000"  # only ONE stock-out applied (10 - 5)


# --- Immutability / cancellation ---


async def test_posted_purchase_invoice_immutable(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")
    response = await client.patch(f"{INVOICES_ENDPOINT}/{invoice['id']}", json={"notes": "x", "expected_row_version": invoice["row_version"]})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PINV-002"


async def test_cancel_draft_po(client):
    unit, product, supplier = await _setup_basic(client)
    created = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"]), headers=_idem())
    order = created.json()["data"]
    response = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/cancel", json={"expected_row_version": order["row_version"]})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"


async def test_row_version_conflict_on_po(client):
    unit, product, supplier = await _setup_basic(client)
    created = await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"]), headers=_idem())
    order = created.json()["data"]

    first = await client.patch(f"{ORDERS_ENDPOINT}/{order['id']}", json={"notes": "first", "expected_row_version": order["row_version"]})
    assert first.status_code == 200
    stale = await client.patch(f"{ORDERS_ENDPOINT}/{order['id']}", json={"notes": "stale", "expected_row_version": order["row_version"]})
    assert stale.status_code == 412


# --- Audit ---


async def test_audit_events_recorded(client, db_session):
    unit, product, supplier = await _setup_basic(client)
    order = await _create_confirmed_po(client, supplier, product, unit, "10")
    await _create_confirmed_receipt(client, order, "10")

    from app.models.audit_log import AuditLog

    po_result = await db_session.execute(select(AuditLog).where(AuditLog.entity_type == "purchase_order"))
    po_actions = {e.action for e in po_result.scalars().all()}
    assert "PURCHASE_ORDER_CREATED" in po_actions
    assert "PURCHASE_ORDER_CONFIRMED" in po_actions
    assert "PURCHASE_ORDER_RECEIPT_UPDATED" in po_actions

    gr_result = await db_session.execute(select(AuditLog).where(AuditLog.entity_type == "goods_receipt"))
    gr_actions = {e.action for e in gr_result.scalars().all()}
    assert "GOODS_RECEIPT_CREATED" in gr_actions
    assert "GOODS_RECEIPT_CONFIRMED" in gr_actions


# --- List / search / filter ---


async def test_list_purchase_orders_search_and_filter(client):
    unit, product, supplier = await _setup_basic(client)
    await client.post(ORDERS_ENDPOINT, json=_po_payload(supplier["id"], product["id"], unit["id"]), headers=_idem())

    listed = await client.get(ORDERS_ENDPOINT, params={"search": supplier["name"]})
    assert listed.status_code == 200
    assert listed.json()["pagination"]["total_items"] == 1

    filtered = await client.get(ORDERS_ENDPOINT, params={"status": "DRAFT"})
    assert filtered.json()["pagination"]["total_items"] == 1

    filtered_none = await client.get(ORDERS_ENDPOINT, params={"status": "CANCELLED"})
    assert filtered_none.json()["pagination"]["total_items"] == 0


# --- GST calculation server-authoritative ---


async def test_gst_calculation_and_client_tampering_ignored(client):
    unit, product, supplier = await _setup_basic(client)
    payload = _po_payload(supplier["id"], product["id"], unit["id"], "10")
    payload["grand_total"] = "1"  # client tampering attempt
    response = await client.post(ORDERS_ENDPOINT, json=payload, headers=_idem())
    data = response.json()["data"]
    line = data["lines"][0]
    assert Decimal(line["cgst_amount"]) == Decimal("45.00")  # 10*50=500 taxable * 18% / 2
    assert Decimal(line["sgst_amount"]) == Decimal("45.00")
    assert Decimal(data["grand_total"]) == Decimal("590.00")
