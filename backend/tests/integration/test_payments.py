"""PROMPT-024 test catalogue for Payments & Collections Management
(/api/v1/customer-receipts, /api/v1/supplier-payments).

Covers the core mandatory scenarios from §48: create (cash/cheque, both
directions), full/partial/multi-invoice allocation, over-allocation
rejection, wrong-party rejection, invoice payment_status transitions,
unallocated-amount tracking, idempotency (HTTP key + client_transaction_id),
concurrency, reversal + immutability + double-reversal rejection, cheque
lifecycle (pending/cleared/bounced) and its restore-outstanding effect,
tenant isolation, RBAC, and zero/negative amount rejection.
"""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

RECEIPTS_ENDPOINT = "/api/v1/customer-receipts"
PAYMENTS_ENDPOINT = "/api/v1/supplier-payments"
SALES_INVOICES_ENDPOINT = "/api/v1/sales/invoices"
PURCHASE_INVOICES_ENDPOINT = "/api/v1/purchase/invoices"
PRODUCTS_ENDPOINT = "/api/v1/products"
UNITS_ENDPOINT = "/api/v1/units"
CUSTOMERS_ENDPOINT = "/api/v1/customers"
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
    return f"pay-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "Payments Test Co", "address_line1": "1 Main St", "city": "Chennai",
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


async def _create_customer(client, **overrides) -> dict:
    payload = {"name": "Test Customer", "owner_name": "Owner", "phone": _unique_phone()}
    payload.update(overrides)
    response = await client.post(CUSTOMERS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


async def _create_supplier(client, **overrides) -> dict:
    payload = {"name": "Test Supplier", "contact_person": "Contact", "phone": _unique_phone(), "email": _unique_email()}
    payload.update(overrides)
    response = await client.post(SUPPLIERS_ENDPOINT, json=payload)
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
    supplier = await _create_supplier(client)
    await _seed_opening_stock(client, product["id"], unit["id"])
    return unit, product, customer, supplier


async def _create_posted_sales_invoice(client, customer, product, unit, amount_qty: str = "10", unit_price: str = "100") -> dict:
    payload = {"customer_id": customer["id"], "lines": [{"product_id": product["id"], "quantity": amount_qty, "uom_id": unit["id"], "unit_price": unit_price}]}
    created = await client.post(SALES_INVOICES_ENDPOINT, json=payload, headers=_idem())
    assert created.status_code == 201
    invoice = created.json()["data"]
    posted = await client.post(f"{SALES_INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    return posted.json()["data"]


async def _create_posted_purchase_invoice(client, supplier, product, unit, amount_qty: str = "10", unit_price: str = "50") -> dict:
    payload = {"supplier_id": supplier["id"], "lines": [{"product_id": product["id"], "quantity": amount_qty, "uom_id": unit["id"], "unit_price": unit_price}]}
    created = await client.post(PURCHASE_INVOICES_ENDPOINT, json=payload, headers=_idem())
    assert created.status_code == 201
    invoice = created.json()["data"]
    posted = await client.post(f"{PURCHASE_INVOICES_ENDPOINT}/{invoice['id']}/post", json={"expected_row_version": invoice["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    return posted.json()["data"]


async def _get_sales_invoice(client, invoice_id: str) -> dict:
    response = await client.get(f"{SALES_INVOICES_ENDPOINT}/{invoice_id}")
    assert response.status_code == 200
    return response.json()["data"]


async def _get_purchase_invoice(client, invoice_id: str) -> dict:
    response = await client.get(f"{PURCHASE_INVOICES_ENDPOINT}/{invoice_id}")
    assert response.status_code == 200
    return response.json()["data"]


# --- TC-001/002/004: create receipt (cash / cheque) ---


async def test_create_cash_receipt_draft(client):
    unit, product, customer, supplier = await _setup_basic(client)
    response = await client.post(
        RECEIPTS_ENDPOINT,
        json={"customer_id": customer["id"], "payment_method": "CASH", "amount": "5000", "allocations": []},
        headers=_idem(),
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["payment_number"].startswith("REC-")
    assert data["party_type"] == "CUSTOMER"


async def test_create_cheque_receipt_requires_cheque_fields(client):
    unit, product, customer, supplier = await _setup_basic(client)
    missing = await client.post(
        RECEIPTS_ENDPOINT, json={"customer_id": customer["id"], "payment_method": "CHEQUE", "amount": "5000", "allocations": []}, headers=_idem(),
    )
    assert missing.status_code == 422

    ok = await client.post(
        RECEIPTS_ENDPOINT,
        json={
            "customer_id": customer["id"], "payment_method": "CHEQUE", "amount": "5000",
            "cheque_number": "CHQ001", "cheque_date": "2026-01-01", "cheque_bank_name": "Test Bank", "allocations": [],
        },
        headers=_idem(),
    )
    assert ok.status_code == 201
    data = ok.json()["data"]
    assert data["cheque_status"] == "PENDING"


async def test_create_supplier_cheque_payment(client):
    unit, product, customer, supplier = await _setup_basic(client)
    response = await client.post(
        PAYMENTS_ENDPOINT,
        json={
            "supplier_id": supplier["id"], "payment_method": "CHEQUE", "amount": "3000",
            "cheque_number": "SCHQ01", "cheque_date": "2026-01-02", "allocations": [],
        },
        headers=_idem(),
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["payment_number"].startswith("PAY-")
    assert data["party_type"] == "SUPPLIER"


# --- TC-009/010/011: allocation (full / partial / multi-invoice) ---


async def test_full_allocation_to_one_invoice_marks_paid(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")
    grand_total = invoice["grand_total"]

    created = await client.post(
        RECEIPTS_ENDPOINT,
        json={"customer_id": customer["id"], "payment_method": "CASH", "amount": grand_total, "allocations": [{"invoice_id": invoice["id"], "allocated_amount": grand_total}]},
        headers=_idem(),
    )
    assert created.status_code == 201
    receipt = created.json()["data"]
    assert receipt["unallocated_amount"] == "0.00"

    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    assert posted.json()["data"]["status"] == "POSTED"

    invoice_after = await _get_sales_invoice(client, invoice["id"])
    assert invoice_after["payment_status"] == "PAID"
    assert invoice_after["paid_amount"] == grand_total


async def test_partial_allocation_marks_partially_paid(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")

    created = await client.post(
        RECEIPTS_ENDPOINT,
        json={"customer_id": customer["id"], "payment_method": "CASH", "amount": "40", "allocations": [{"invoice_id": invoice["id"], "allocated_amount": "40"}]},
        headers=_idem(),
    )
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert posted.status_code == 200

    invoice_after = await _get_sales_invoice(client, invoice["id"])
    assert invoice_after["payment_status"] == "PARTIALLY_PAID"
    assert invoice_after["paid_amount"] == "40.00"


async def test_allocation_across_multiple_invoices(client):
    unit, product, customer, supplier = await _setup_basic(client)
    inv1 = await _create_posted_sales_invoice(client, customer, product, unit, "1", "100")  # small total
    inv2 = await _create_posted_sales_invoice(client, customer, product, unit, "1", "100")
    total_amount = str(Decimal(inv1["grand_total"]) + Decimal(inv2["grand_total"]))

    created = await client.post(
        RECEIPTS_ENDPOINT,
        json={
            "customer_id": customer["id"], "payment_method": "CASH", "amount": total_amount,
            "allocations": [
                {"invoice_id": inv1["id"], "allocated_amount": inv1["grand_total"]},
                {"invoice_id": inv2["id"], "allocated_amount": inv2["grand_total"]},
            ],
        },
        headers=_idem(),
    )
    assert created.status_code == 201
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    assert len(posted.json()["data"]["allocations"]) == 2


# --- TC-012/013: over-allocation rejection ---


async def test_allocation_exceeding_outstanding_rejected(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")
    over = str(Decimal(invoice["grand_total"]) + Decimal("100"))

    response = await client.post(
        RECEIPTS_ENDPOINT,
        json={"customer_id": customer["id"], "payment_method": "CASH", "amount": over, "allocations": [{"invoice_id": invoice["id"], "allocated_amount": over}]},
        headers=_idem(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PAY-006"


async def test_total_allocation_exceeding_payment_amount_rejected(client):
    unit, product, customer, supplier = await _setup_basic(client)
    inv1 = await _create_posted_sales_invoice(client, customer, product, unit, "5", "100")
    inv2 = await _create_posted_sales_invoice(client, customer, product, unit, "5", "100")

    response = await client.post(
        RECEIPTS_ENDPOINT,
        json={
            "customer_id": customer["id"], "payment_method": "CASH", "amount": "10",
            "allocations": [
                {"invoice_id": inv1["id"], "allocated_amount": inv1["grand_total"]},
                {"invoice_id": inv2["id"], "allocated_amount": inv2["grand_total"]},
            ],
        },
        headers=_idem(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PAY-007"


# --- TC-014/015: wrong party/document allocation rejected ---


async def test_customer_receipt_cannot_allocate_purchase_invoice(client):
    unit, product, customer, supplier = await _setup_basic(client)
    purchase_invoice = await _create_posted_purchase_invoice(client, supplier, product, unit)

    response = await client.post(
        RECEIPTS_ENDPOINT,
        json={"customer_id": customer["id"], "payment_method": "CASH", "amount": "500", "allocations": [{"invoice_id": purchase_invoice["id"], "allocated_amount": "500"}]},
        headers=_idem(),
    )
    assert response.status_code == 404  # tenant-owned Sales Invoice lookup fails — a Purchase Invoice id is not one


async def test_supplier_payment_cannot_allocate_sales_invoice(client):
    unit, product, customer, supplier = await _setup_basic(client)
    sales_invoice = await _create_posted_sales_invoice(client, customer, product, unit)

    response = await client.post(
        PAYMENTS_ENDPOINT,
        json={"supplier_id": supplier["id"], "payment_method": "CASH", "amount": "500", "allocations": [{"invoice_id": sales_invoice["id"], "allocated_amount": "500"}]},
        headers=_idem(),
    )
    assert response.status_code == 404


# --- TC-018: unallocated amount is tracked, never discarded ---


async def test_unallocated_amount_tracked(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")

    created = await client.post(
        RECEIPTS_ENDPOINT,
        json={"customer_id": customer["id"], "payment_method": "CASH", "amount": "5000", "allocations": [{"invoice_id": invoice["id"], "allocated_amount": invoice["grand_total"]}]},
        headers=_idem(),
    )
    receipt = created.json()["data"]
    expected_unallocated = str(Decimal("5000") - Decimal(invoice["grand_total"]))
    assert receipt["unallocated_amount"] == expected_unallocated

    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert posted.status_code == 200
    assert posted.json()["data"]["unallocated_amount"] == expected_unallocated


# --- TC-019: idempotency (HTTP key + client_transaction_id) ---


async def test_idempotent_post_retry(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")
    created = await client.post(
        RECEIPTS_ENDPOINT,
        json={"customer_id": customer["id"], "payment_method": "CASH", "amount": invoice["grand_total"], "allocations": [{"invoice_id": invoice["id"], "allocated_amount": invoice["grand_total"]}]},
        headers=_idem(),
    )
    receipt = created.json()["data"]
    key = str(uuid.uuid4())

    first = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers={"Idempotency-Key": key})
    assert first.status_code == 200
    second = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers={"Idempotency-Key": key})
    assert second.status_code == 200
    assert second.json()["data"] == first.json()["data"]

    invoice_after = await _get_sales_invoice(client, invoice["id"])
    assert invoice_after["paid_amount"] == invoice["grand_total"]  # not doubled


async def test_duplicate_client_transaction_id_returns_existing_payment(client):
    unit, product, customer, supplier = await _setup_basic(client)
    ctid = str(uuid.uuid4())
    payload = {"customer_id": customer["id"], "payment_method": "CASH", "amount": "1000", "client_transaction_id": ctid, "allocations": []}

    first = await client.post(RECEIPTS_ENDPOINT, json=payload, headers=_idem())
    assert first.status_code == 201
    second = await client.post(RECEIPTS_ENDPOINT, json=payload, headers=_idem())
    assert second.status_code == 201
    assert first.json()["data"]["id"] == second.json()["data"]["id"]


# --- TC-020: concurrent allocation cannot exceed outstanding ---


async def test_concurrent_allocation_cannot_exceed_outstanding(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "1", "100")  # grand_total ~118

    async def _create_and_post(amount: str):
        created = await client.post(
            RECEIPTS_ENDPOINT,
            json={"customer_id": customer["id"], "payment_method": "CASH", "amount": amount, "allocations": [{"invoice_id": invoice["id"], "allocated_amount": amount}]},
            headers=_idem(),
        )
        if created.status_code != 201:
            return created
        receipt = created.json()["data"]
        return await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())

    grand_total = Decimal(invoice["grand_total"])
    half = str(grand_total)  # each attempt uses the full outstanding — only one should succeed
    results = await asyncio.gather(_create_and_post(half), _create_and_post(half))
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 422]

    invoice_after = await _get_sales_invoice(client, invoice["id"])
    assert Decimal(invoice_after["paid_amount"]) <= grand_total


# --- TC-021/022/023: reversal ---


async def test_reverse_posted_receipt_restores_outstanding(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")

    created = await client.post(
        RECEIPTS_ENDPOINT,
        json={"customer_id": customer["id"], "payment_method": "CASH", "amount": invoice["grand_total"], "allocations": [{"invoice_id": invoice["id"], "allocated_amount": invoice["grand_total"]}]},
        headers=_idem(),
    )
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    posted_data = posted.json()["data"]

    invoice_paid = await _get_sales_invoice(client, invoice["id"])
    assert invoice_paid["payment_status"] == "PAID"

    reversed_resp = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/reverse", json={"expected_row_version": posted_data["row_version"]})
    assert reversed_resp.status_code == 200
    assert reversed_resp.json()["data"]["status"] == "REVERSED"

    invoice_after = await _get_sales_invoice(client, invoice["id"])
    assert invoice_after["payment_status"] == "UNPAID"
    assert invoice_after["paid_amount"] == "0.00"

    # original payment amount/method/allocation fields remain immutable
    unchanged = reversed_resp.json()["data"]
    assert unchanged["amount"] == receipt["amount"]
    assert unchanged["allocations"][0]["allocated_amount"] == invoice["grand_total"]


async def test_double_reversal_rejected(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")
    created = await client.post(
        RECEIPTS_ENDPOINT,
        json={"customer_id": customer["id"], "payment_method": "CASH", "amount": invoice["grand_total"], "allocations": [{"invoice_id": invoice["id"], "allocated_amount": invoice["grand_total"]}]},
        headers=_idem(),
    )
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    posted_data = posted.json()["data"]

    first = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/reverse", json={"expected_row_version": posted_data["row_version"]})
    assert first.status_code == 200
    reversed_data = first.json()["data"]

    second = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/reverse", json={"expected_row_version": reversed_data["row_version"]})
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "PAY-009"


# --- TC-024/025/026/027: cheque lifecycle ---


async def test_cheque_bounce_restores_outstanding(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")

    created = await client.post(
        RECEIPTS_ENDPOINT,
        json={
            "customer_id": customer["id"], "payment_method": "CHEQUE", "amount": invoice["grand_total"],
            "cheque_number": "CHQ100", "cheque_date": "2026-02-01",
            "allocations": [{"invoice_id": invoice["id"], "allocated_amount": invoice["grand_total"]}],
        },
        headers=_idem(),
    )
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    posted_data = posted.json()["data"]
    assert posted_data["cheque_status"] == "PENDING"

    invoice_paid = await _get_sales_invoice(client, invoice["id"])
    assert invoice_paid["payment_status"] == "PAID"  # POSTED cheque payment reduces outstanding immediately (§7)

    bounced = await client.post(
        f"{RECEIPTS_ENDPOINT}/{receipt['id']}/cheque-status", json={"expected_row_version": posted_data["row_version"], "cheque_status": "BOUNCED"},
    )
    assert bounced.status_code == 200
    bounced_data = bounced.json()["data"]
    assert bounced_data["status"] == "REVERSED"
    assert bounced_data["cheque_status"] == "BOUNCED"

    invoice_after = await _get_sales_invoice(client, invoice["id"])
    assert invoice_after["payment_status"] == "UNPAID"  # no longer treated as settled (§19/§27)


async def test_cheque_cleared_status_update(client):
    unit, product, customer, supplier = await _setup_basic(client)
    created = await client.post(
        RECEIPTS_ENDPOINT,
        json={"customer_id": customer["id"], "payment_method": "CHEQUE", "amount": "1000", "cheque_number": "CHQ200", "cheque_date": "2026-02-01", "allocations": []},
        headers=_idem(),
    )
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    posted_data = posted.json()["data"]

    cleared = await client.post(
        f"{RECEIPTS_ENDPOINT}/{receipt['id']}/cheque-status", json={"expected_row_version": posted_data["row_version"], "cheque_status": "CLEARED"},
    )
    assert cleared.status_code == 200
    data = cleared.json()["data"]
    assert data["cheque_status"] == "CLEARED"
    assert data["status"] == "POSTED"  # cheque clearing is a label update only, no re-posting


async def test_already_bounced_cheque_rejects_further_status_change(client):
    unit, product, customer, supplier = await _setup_basic(client)
    created = await client.post(
        RECEIPTS_ENDPOINT,
        json={"customer_id": customer["id"], "payment_method": "CHEQUE", "amount": "1000", "cheque_number": "CHQ300", "cheque_date": "2026-02-01", "allocations": []},
        headers=_idem(),
    )
    receipt = created.json()["data"]
    posted = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    posted_data = posted.json()["data"]

    bounced = await client.post(
        f"{RECEIPTS_ENDPOINT}/{receipt['id']}/cheque-status", json={"expected_row_version": posted_data["row_version"], "cheque_status": "BOUNCED"},
    )
    bounced_data = bounced.json()["data"]

    again = await client.post(
        f"{RECEIPTS_ENDPOINT}/{receipt['id']}/cheque-status", json={"expected_row_version": bounced_data["row_version"], "cheque_status": "CLEARED"},
    )
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "PAY-014"


# --- TC-028/029/030: tenant isolation & RBAC ---


async def test_cross_tenant_payment_access_denied(client):
    unit, product, customer, supplier = await _setup_basic(client)
    created = await client.post(RECEIPTS_ENDPOINT, json={"customer_id": customer["id"], "payment_method": "CASH", "amount": "500", "allocations": []}, headers=_idem())
    payment_id = created.json()["data"]["id"]

    await _signup_and_login_owner(client)  # tenant B
    response = await client.get(f"{RECEIPTS_ENDPOINT}/{payment_id}")
    assert response.status_code == 404


async def test_salesperson_cannot_create_supplier_payment(client):
    unit, product, customer, supplier = await _setup_basic(client)
    await _create_salesperson_and_login(client)
    response = await client.post(PAYMENTS_ENDPOINT, json={"supplier_id": supplier["id"], "payment_method": "CASH", "amount": "500", "allocations": []}, headers=_idem())
    assert response.status_code == 403


async def test_salesperson_cannot_post_customer_receipt(client):
    unit, product, customer, supplier = await _setup_basic(client)
    created = await client.post(RECEIPTS_ENDPOINT, json={"customer_id": customer["id"], "payment_method": "CASH", "amount": "500", "allocations": []}, headers=_idem())
    receipt = created.json()["data"]

    await _create_salesperson_and_login(client)
    response = await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())
    assert response.status_code == 403


# --- TC-036: zero/negative amount rejected ---


async def test_zero_and_negative_amount_rejected(client):
    unit, product, customer, supplier = await _setup_basic(client)
    zero = await client.post(RECEIPTS_ENDPOINT, json={"customer_id": customer["id"], "payment_method": "CASH", "amount": "0", "allocations": []}, headers=_idem())
    assert zero.status_code == 422

    negative = await client.post(RECEIPTS_ENDPOINT, json={"customer_id": customer["id"], "payment_method": "CASH", "amount": "-100", "allocations": []}, headers=_idem())
    assert negative.status_code == 422


# --- outstanding-invoices supporting endpoint ---


async def test_outstanding_invoices_reflects_payment_status(client):
    unit, product, customer, supplier = await _setup_basic(client)
    invoice = await _create_posted_sales_invoice(client, customer, product, unit, "10", "100")

    before = await client.get(f"{RECEIPTS_ENDPOINT}/outstanding-invoices", params={"customer_id": customer["id"]})
    assert before.status_code == 200
    ids = [i["invoice_id"] for i in before.json()["data"]["invoices"]]
    assert invoice["id"] in ids

    created = await client.post(
        RECEIPTS_ENDPOINT,
        json={"customer_id": customer["id"], "payment_method": "CASH", "amount": invoice["grand_total"], "allocations": [{"invoice_id": invoice["id"], "allocated_amount": invoice["grand_total"]}]},
        headers=_idem(),
    )
    receipt = created.json()["data"]
    await client.post(f"{RECEIPTS_ENDPOINT}/{receipt['id']}/post", json={"expected_row_version": receipt["row_version"]}, headers=_idem())

    after = await client.get(f"{RECEIPTS_ENDPOINT}/outstanding-invoices", params={"customer_id": customer["id"]})
    ids_after = [i["invoice_id"] for i in after.json()["data"]["invoices"]]
    assert invoice["id"] not in ids_after  # fully paid, no longer outstanding
