"""PROMPT-023 test catalogue for Purchase Return Management
(/api/v1/purchase/returns) — completes the workflow PROMPT-019 (and
`test_purchase_foundation.py`) established as a foundation: create/
draft/edit/confirm/list/view, eligible-invoice-line loading, returnable-
quantity tracking, over-return prevention, numbering, concurrency,
idempotency, RBAC, tenant isolation, and the mandatory one-Stock-OUT-
per-line-on-confirm rule are already covered there. This file covers
ONLY the genuinely new PROMPT-023 surface area: CONFIRMED-return
cancellation with a compensating Stock IN reversal, related-documents,
and audit-history — mirroring PROMPT-021's own `test_goods_receipt_
management.py` split exactly.
"""

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
    return f"prm-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "Purchase Return Test Co", "address_line1": "1 Main St", "city": "Chennai",
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


async def _create_confirmed_return(client, invoice: dict, quantity: str, reason: str = "DAMAGED") -> dict:
    invoice_line_id = invoice["lines"][0]["id"]
    created = await client.post(
        RETURNS_ENDPOINT,
        json={"source_purchase_invoice_id": invoice["id"], "return_reason": reason, "lines": [{"source_purchase_invoice_line_id": invoice_line_id, "quantity": quantity}]},
        headers=_idem(),
    )
    assert created.status_code == 201
    purchase_return = created.json()["data"]
    confirmed = await client.post(f"{RETURNS_ENDPOINT}/{purchase_return['id']}/confirm", json={"expected_row_version": purchase_return["row_version"]}, headers=_idem())
    assert confirmed.status_code == 200
    return confirmed.json()["data"]


# --- Cancellation with reversal (§33-35, INVARIANT 11) ---


async def test_cancel_confirmed_return_creates_compensating_stock_in(client, db_session):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "20")
    confirmed = await _create_confirmed_return(client, invoice, "5")
    assert await _available_quantity(client, product["id"]) == "15.000"

    cancelled = await client.post(f"{RETURNS_ENDPOINT}/{confirmed['id']}/cancel", json={"expected_row_version": confirmed["row_version"]})
    assert cancelled.status_code == 200
    data = cancelled.json()["data"]
    assert data["status"] == "CANCELLED"

    # restocked — the returned goods are back in inventory
    assert await _available_quantity(client, product["id"]) == "20.000"

    from app.models.stock_ledger_entry import StockLedgerEntry

    result = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.product_id == uuid.UUID(product["id"])))
    entries = {e.source_type: e for e in result.scalars().all()}
    assert "PURCHASE_RETURN" in entries and entries["PURCHASE_RETURN"].movement_type == "STOCK_OUT"
    assert "PURCHASE_RETURN_REVERSAL" in entries and entries["PURCHASE_RETURN_REVERSAL"].movement_type == "STOCK_IN"


async def test_original_stock_out_remains_immutable_after_reversal(client, db_session):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "20")
    confirmed = await _create_confirmed_return(client, invoice, "5")

    from app.models.stock_ledger_entry import StockLedgerEntry

    before_result = await db_session.execute(
        select(StockLedgerEntry).where(StockLedgerEntry.source_type == "PURCHASE_RETURN", StockLedgerEntry.product_id == uuid.UUID(product["id"]))
    )
    original = before_result.scalar_one()
    original_quantity, original_id = original.quantity, original.id

    await client.post(f"{RETURNS_ENDPOINT}/{confirmed['id']}/cancel", json={"expected_row_version": confirmed["row_version"]})

    db_session.expire_all()
    after_result = await db_session.execute(select(StockLedgerEntry).where(StockLedgerEntry.id == original_id))
    still_there = after_result.scalar_one()
    assert still_there.quantity == original_quantity == Decimal("5.000")
    assert still_there.movement_type == "STOCK_OUT"


async def test_cancelled_return_releases_returned_quantity_for_reuse(client):
    """Cancelling a CONFIRMED return frees up the invoice line's
    returnable quantity so it can be returned again (a corrected return,
    for instance)."""
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")
    confirmed = await _create_confirmed_return(client, invoice, "10")  # fully returned

    # No further return possible while the first one stands.
    invoice_line_id = invoice["lines"][0]["id"]
    blocked = await client.post(
        RETURNS_ENDPOINT,
        json={"source_purchase_invoice_id": invoice["id"], "return_reason": "DAMAGED", "lines": [{"source_purchase_invoice_line_id": invoice_line_id, "quantity": "1"}]},
        headers=_idem(),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "PRET-004"

    await client.post(f"{RETURNS_ENDPOINT}/{confirmed['id']}/cancel", json={"expected_row_version": confirmed["row_version"]})

    # Now the full quantity is returnable again.
    allowed = await client.post(
        RETURNS_ENDPOINT,
        json={"source_purchase_invoice_id": invoice["id"], "return_reason": "DAMAGED", "lines": [{"source_purchase_invoice_line_id": invoice_line_id, "quantity": "10"}]},
        headers=_idem(),
    )
    assert allowed.status_code == 201


async def test_double_cancel_confirmed_return_rejected(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")
    confirmed = await _create_confirmed_return(client, invoice, "5")

    first = await client.post(f"{RETURNS_ENDPOINT}/{confirmed['id']}/cancel", json={"expected_row_version": confirmed["row_version"]})
    assert first.status_code == 200
    cancelled = first.json()["data"]

    second = await client.post(f"{RETURNS_ENDPOINT}/{confirmed['id']}/cancel", json={"expected_row_version": cancelled["row_version"]})
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "PRET-002"


async def test_cancel_draft_return_has_no_stock_impact(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")
    invoice_line_id = invoice["lines"][0]["id"]
    created = await client.post(
        RETURNS_ENDPOINT, json={"source_purchase_invoice_id": invoice["id"], "return_reason": "DAMAGED", "lines": [{"source_purchase_invoice_line_id": invoice_line_id, "quantity": "5"}]}, headers=_idem()
    )
    draft = created.json()["data"]
    assert await _available_quantity(client, product["id"]) == "10.000"

    cancelled = await client.post(f"{RETURNS_ENDPOINT}/{draft['id']}/cancel", json={"expected_row_version": draft["row_version"]})
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "CANCELLED"
    assert await _available_quantity(client, product["id"]) == "10.000"  # unchanged, never confirmed


async def test_unauthorized_cancellation_rejected(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")
    confirmed = await _create_confirmed_return(client, invoice, "5")

    await _create_salesperson_and_login(client)
    response = await client.post(f"{RETURNS_ENDPOINT}/{confirmed['id']}/cancel", json={"expected_row_version": confirmed["row_version"]})
    assert response.status_code == 403


# --- Stock impact visibility (§18/§42) ---


async def test_return_line_exposes_stock_movement_id_and_reversal_flag(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")
    confirmed = await _create_confirmed_return(client, invoice, "5")
    assert confirmed["lines"][0]["stock_movement_id"] is not None
    assert confirmed["lines"][0]["stock_movement_reversed"] is False

    cancelled_resp = await client.post(f"{RETURNS_ENDPOINT}/{confirmed['id']}/cancel", json={"expected_row_version": confirmed["row_version"]})
    cancelled = cancelled_resp.json()["data"]
    assert cancelled["lines"][0]["stock_movement_reversed"] is True


# --- Related documents / audit history (§4/§44/§48) ---


async def test_related_documents_traces_invoice_gr_and_po(client):
    unit, product, supplier = await _setup_basic(client)
    order_created = await client.post(
        ORDERS_ENDPOINT, json={"supplier_id": supplier["id"], "lines": [{"product_id": product["id"], "quantity": "20", "uom_id": unit["id"], "unit_price": "50"}]}, headers=_idem()
    )
    order = order_created.json()["data"]
    confirmed_order = await client.post(f"{ORDERS_ENDPOINT}/{order['id']}/confirm", json={"expected_row_version": order["row_version"]})
    order = confirmed_order.json()["data"]

    po_line_id = order["lines"][0]["id"]
    receipt_created = await client.post(RECEIPTS_ENDPOINT, json={"purchase_order_id": order["id"], "lines": [{"purchase_order_line_id": po_line_id, "quantity": "20"}]}, headers=_idem())
    receipt = receipt_created.json()["data"]
    receipt_confirmed = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/confirm", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    receipt = receipt_confirmed.json()["data"]

    po_line_id_for_invoice = order["lines"][0]["id"]
    invoice_created = await client.post(
        f"{ORDERS_ENDPOINT}/{order['id']}/create-invoice", json={"lines": [{"purchase_order_line_id": po_line_id_for_invoice, "quantity": "20"}]}, headers=_idem()
    )
    invoice = invoice_created.json()["data"]
    invoice_posted = await client.post(f"{INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    invoice = invoice_posted.json()["data"]

    confirmed_return = await _create_confirmed_return(client, invoice, "5")

    response = await client.get(f"{RETURNS_ENDPOINT}/{confirmed_return['id']}/related-documents")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source_purchase_invoice_id"] == invoice["id"]
    assert data["source_purchase_order_id"] == order["id"]
    assert len(data["goods_receipts"]) == 1
    assert data["goods_receipts"][0]["id"] == receipt["id"]


async def test_related_documents_cross_tenant_returns_404(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")
    confirmed = await _create_confirmed_return(client, invoice, "5")

    await _signup_and_login_owner(client)  # tenant B
    response = await client.get(f"{RETURNS_ENDPOINT}/{confirmed['id']}/related-documents")
    assert response.status_code == 404


async def test_audit_history_records_lifecycle(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")
    confirmed = await _create_confirmed_return(client, invoice, "5")
    cancelled_resp = await client.post(f"{RETURNS_ENDPOINT}/{confirmed['id']}/cancel", json={"expected_row_version": confirmed["row_version"]})
    assert cancelled_resp.status_code == 200

    response = await client.get(f"{RETURNS_ENDPOINT}/{confirmed['id']}/audit-history")
    assert response.status_code == 200
    actions = [event["action"] for event in response.json()["data"]["events"]]
    assert "PURCHASE_RETURN_CREATED" in actions
    assert "PURCHASE_RETURN_CONFIRMED" in actions
    assert "PURCHASE_RETURN_CANCELLED" in actions


async def test_salesperson_cannot_view_related_documents_or_audit(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "10")
    confirmed = await _create_confirmed_return(client, invoice, "5")

    await _create_salesperson_and_login(client)
    assert (await client.get(f"{RETURNS_ENDPOINT}/{confirmed['id']}/related-documents")).status_code == 403
    assert (await client.get(f"{RETURNS_ENDPOINT}/{confirmed['id']}/audit-history")).status_code == 403


# --- Multiple partial returns against one invoice (§12/§13, TC-015/016/017/018) ---


async def test_multiple_partial_returns_accumulate_and_cap(client):
    unit, product, supplier = await _setup_basic(client)
    invoice = await _create_posted_direct_invoice(client, supplier, product, unit, "100")

    r1 = await _create_confirmed_return(client, invoice, "20")
    r2 = await _create_confirmed_return(client, invoice, "30")
    r3 = await _create_confirmed_return(client, invoice, "50")
    assert {r1["status"], r2["status"], r3["status"]} == {"CONFIRMED"}
    assert await _available_quantity(client, product["id"]) == "0.000"

    invoice_line_id = invoice["lines"][0]["id"]
    blocked = await client.post(
        RETURNS_ENDPOINT,
        json={"source_purchase_invoice_id": invoice["id"], "return_reason": "DAMAGED", "lines": [{"source_purchase_invoice_line_id": invoice_line_id, "quantity": "1"}]},
        headers=_idem(),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "PRET-004"
