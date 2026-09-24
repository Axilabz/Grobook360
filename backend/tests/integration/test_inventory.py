"""PROMPT-010 test catalogue for /api/v1/inventory.

Follows test_products.py's structure and helper style. Covers the
security-critical subset of PROMPT-010 S61/S62 (tenant isolation, RBAC incl.
the Salesperson no-manual-movement boundary, quantity/unit validation,
negative-stock protection, idempotent retry, concurrency, ledger
immutability) — INVENTORY-API ids noted for traceability.
"""

import asyncio
import uuid

import pytest

INVENTORY_ENDPOINT = "/api/v1/inventory"
PRODUCTS_ENDPOINT = "/api/v1/products"
UNITS_ENDPOINT = "/api/v1/units"
SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"
USERS_ENDPOINT = "/api/v1/users"
RESET_ENDPOINT = "/api/v1/auth/reset-password"

OWNER_PASSWORD = "SecurePass123"
SALESPERSON_PASSWORD = "AnotherSecurePass456"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _unique_email() -> str:
    return f"inv-{uuid.uuid4().hex[:12]}@example.com"


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
        "organization": {
            "business_name": "Inventory Test Co",
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


async def _create_unit(client, code: str, name: str) -> dict:
    response = await client.post(UNITS_ENDPOINT, json={"code": code, "name": name})
    assert response.status_code == 201
    return response.json()["data"]


async def _create_product(client, base_uom_id: str, **overrides) -> dict:
    payload = {"sku": _unique_sku(), "name": "Test Product", "base_uom_id": base_uom_id, "gst_rate": "18"}
    payload.update(overrides)
    response = await client.post(PRODUCTS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


def _idem() -> dict:
    return {"Idempotency-Key": str(uuid.uuid4())}


# --- Opening stock ---


async def test_inventory_api_014_valid_opening_stock(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock",
        json={"product_id": product["id"], "quantity": "100", "uom_id": pcs["id"]},
        headers=_idem(),
    )
    assert response.status_code == 201
    assert response.json()["data"]["movement_type"] == "OPENING_STOCK"

    avail = await client.get(f"{INVENTORY_ENDPOINT}/availability/{product['id']}")
    assert avail.json()["data"]["available_quantity"] == "100.000"


async def test_inventory_api_015_invalid_opening_quantity(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock",
        json={"product_id": product["id"], "quantity": "0", "uom_id": pcs["id"]},
        headers=_idem(),
    )
    assert response.status_code == 422


async def test_inventory_api_016_unauthorized_opening_stock_salesperson(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    await _create_salesperson_and_login(client)
    response = await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock",
        json={"product_id": product["id"], "quantity": "10", "uom_id": pcs["id"]},
        headers=_idem(),
    )
    assert response.status_code == 403


async def test_inventory_api_017_duplicate_opening_stock(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    first = await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock",
        json={"product_id": product["id"], "quantity": "50", "uom_id": pcs["id"]},
        headers=_idem(),
    )
    assert first.status_code == 201
    second = await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock",
        json={"product_id": product["id"], "quantity": "20", "uom_id": pcs["id"]},
        headers=_idem(),
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "INV-004"


async def test_inventory_api_018_opening_stock_audit(client, db_session):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])
    await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock",
        json={"product_id": product["id"], "quantity": "30", "uom_id": pcs["id"]},
        headers=_idem(),
    )

    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    result = await db_session.execute(select(AuditLog).where(AuditLog.action == "OPENING_STOCK_CREATED"))
    assert result.scalars().first() is not None


# --- Stock-in / stock-out ---


async def test_inventory_api_026_valid_stock_in(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "40", "uom_id": pcs["id"]},
        headers=_idem(),
    )
    assert response.status_code == 201
    avail = await client.get(f"{INVENTORY_ENDPOINT}/availability/{product['id']}")
    assert avail.json()["data"]["available_quantity"] == "40.000"


async def test_inventory_api_027_valid_stock_out(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])
    await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "40", "uom_id": pcs["id"]},
        headers=_idem(),
    )

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/stock-out",
        json={"product_id": product["id"], "quantity": "15", "uom_id": pcs["id"]},
        headers=_idem(),
    )
    assert response.status_code == 201
    avail = await client.get(f"{INVENTORY_ENDPOINT}/availability/{product['id']}")
    assert avail.json()["data"]["available_quantity"] == "25.000"


async def test_inventory_api_028_invalid_quantity(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "-5", "uom_id": pcs["id"]},
        headers=_idem(),
    )
    assert response.status_code == 422


async def test_inventory_api_029_insufficient_stock(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])
    await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "10", "uom_id": pcs["id"]},
        headers=_idem(),
    )

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/stock-out",
        json={"product_id": product["id"], "quantity": "15", "uom_id": pcs["id"]},
        headers=_idem(),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INV-003"
    # Requested-then-rejected: available quantity unchanged.
    avail = await client.get(f"{INVENTORY_ENDPOINT}/availability/{product['id']}")
    assert avail.json()["data"]["available_quantity"] == "10.000"


async def test_inventory_api_030_invalid_unit(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "10", "uom_id": str(uuid.uuid4())},
        headers=_idem(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INV-002"


async def test_inventory_api_031_unit_conversion(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    carton = await _create_unit(client, "CTN", "Carton")
    product = await _create_product(client, pcs["id"])

    conv = await client.post(
        f"{PRODUCTS_ENDPOINT}/{product['id']}/conversions",
        json={"from_uom_id": carton["id"], "to_uom_id": pcs["id"], "conversion_factor": "24"},
    )
    assert conv.status_code == 201

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "2", "uom_id": carton["id"]},
        headers=_idem(),
    )
    assert response.status_code == 201
    assert response.json()["data"]["base_quantity"] == "48.000"

    avail = await client.get(f"{INVENTORY_ENDPOINT}/availability/{product['id']}")
    assert avail.json()["data"]["available_quantity"] == "48.000"


async def test_inventory_unconvertible_unit_rejected(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    kg = await _create_unit(client, "KG", "Kilogram")
    product = await _create_product(client, pcs["id"])

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "5", "uom_id": kg["id"]},
        headers=_idem(),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INV-002"


async def test_inventory_api_032_duplicate_posting_prevented_by_idempotency(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])
    key = str(uuid.uuid4())

    first = await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "10", "uom_id": pcs["id"]},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 201

    second = await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "10", "uom_id": pcs["id"]},
        headers={"Idempotency-Key": key},
    )
    assert second.status_code == 201
    assert second.json()["data"]["id"] == first.json()["data"]["id"]  # replayed, not re-executed

    avail = await client.get(f"{INVENTORY_ENDPOINT}/availability/{product['id']}")
    assert avail.json()["data"]["available_quantity"] == "10.000"  # not 20


async def test_inventory_api_033_missing_idempotency_key_rejected(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "10", "uom_id": pcs["id"]},
    )
    assert response.status_code == 400


# --- Adjustments ---


async def test_inventory_api_019_positive_adjustment(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/adjustments",
        json={"product_id": product["id"], "quantity": "5", "uom_id": pcs["id"], "direction": "IN", "reason": "Physical count correction"},
        headers=_idem(),
    )
    assert response.status_code == 201
    assert response.json()["data"]["movement_type"] == "ADJUSTMENT_IN"
    avail = await client.get(f"{INVENTORY_ENDPOINT}/availability/{product['id']}")
    assert avail.json()["data"]["available_quantity"] == "5.000"


async def test_inventory_api_020_negative_adjustment(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])
    await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "20", "uom_id": pcs["id"]},
        headers=_idem(),
    )

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/adjustments",
        json={"product_id": product["id"], "quantity": "5", "uom_id": pcs["id"], "direction": "OUT", "reason": "Damaged stock"},
        headers=_idem(),
    )
    assert response.status_code == 201
    assert response.json()["data"]["movement_type"] == "ADJUSTMENT_OUT"
    avail = await client.get(f"{INVENTORY_ENDPOINT}/availability/{product['id']}")
    assert avail.json()["data"]["available_quantity"] == "15.000"


async def test_inventory_api_021_invalid_adjustment_missing_reason(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/adjustments",
        json={"product_id": product["id"], "quantity": "5", "uom_id": pcs["id"], "direction": "IN", "reason": ""},
        headers=_idem(),
    )
    assert response.status_code == 422


async def test_inventory_api_022_unauthorized_adjustment_salesperson(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    await _create_salesperson_and_login(client)
    response = await client.post(
        f"{INVENTORY_ENDPOINT}/adjustments",
        json={"product_id": product["id"], "quantity": "5", "uom_id": pcs["id"], "direction": "IN", "reason": "Test"},
        headers=_idem(),
    )
    assert response.status_code == 403


async def test_inventory_api_023_adjustment_reason_captured(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/adjustments",
        json={"product_id": product["id"], "quantity": "5", "uom_id": pcs["id"], "direction": "IN", "reason": "Wastage"},
        headers=_idem(),
    )
    assert response.json()["data"]["reason"] == "Wastage"
    assert response.json()["data"]["adjustment_number"].startswith("ADJ-")


async def test_inventory_api_024_negative_stock_protection_on_adjustment(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    response = await client.post(
        f"{INVENTORY_ENDPOINT}/adjustments",
        json={"product_id": product["id"], "quantity": "5", "uom_id": pcs["id"], "direction": "OUT", "reason": "Damage"},
        headers=_idem(),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INV-003"


async def test_inventory_api_025_adjustment_audit(client, db_session):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])
    await client.post(
        f"{INVENTORY_ENDPOINT}/adjustments",
        json={"product_id": product["id"], "quantity": "5", "uom_id": pcs["id"], "direction": "IN", "reason": "Count"},
        headers=_idem(),
    )

    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    result = await db_session.execute(select(AuditLog).where(AuditLog.action == "STOCK_ADJUSTMENT_CREATED"))
    assert result.scalars().first() is not None


# --- List / detail / movements / tenant isolation ---


async def test_inventory_api_001_003_list_and_tenant_isolation(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"], name="Findme Inventory Item")

    list_a = await client.get(INVENTORY_ENDPOINT)
    assert list_a.status_code == 200
    assert product["id"] in {item["product_id"] for item in list_a.json()["data"]}

    await _signup_and_login_owner(client)  # second, independent tenant
    list_b = await client.get(INVENTORY_ENDPOINT)
    assert product["id"] not in {item["product_id"] for item in list_b.json()["data"]}


async def test_inventory_api_002_unauthorized_list(client):
    response = await client.get(INVENTORY_ENDPOINT)
    assert response.status_code == 401


async def test_inventory_api_004_search(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    await _create_product(client, pcs["id"], name="Findme Widget")
    response = await client.get(INVENTORY_ENDPOINT, params={"search": "Findme"})
    names = [item["name"] for item in response.json()["data"]]
    assert "Findme Widget" in names


async def test_inventory_api_005_filtering_low_stock(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    # reorder_level has no create/update input in Product Master (PROMPT-009
    # left it read-only), so it's 0 for every product here — "low_stock"
    # filter (reorder_level>0 AND stock<=reorder_level) legitimately
    # returns nothing until a future prompt exposes reorder_level editing.
    await _create_product(client, pcs["id"])
    response = await client.get(INVENTORY_ENDPOINT, params={"stock_status": "low_stock"})
    assert response.status_code == 200
    assert response.json()["data"] == []


async def test_inventory_api_006_pagination(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    for _ in range(3):
        await _create_product(client, pcs["id"])
    response = await client.get(INVENTORY_ENDPOINT, params={"page": 1, "page_size": 2})
    body = response.json()
    assert len(body["data"]) == 2
    assert body["pagination"]["total_items"] >= 3


async def test_inventory_api_007_stock_detail(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])
    response = await client.get(f"{INVENTORY_ENDPOINT}/{product['id']}")
    assert response.status_code == 200
    assert response.json()["data"]["current_stock"] == "0.000"


async def test_inventory_api_008_product_not_found(client):
    await _signup_and_login_owner(client)
    response = await client.get(f"{INVENTORY_ENDPOINT}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INV-001"


async def test_inventory_api_009_cross_tenant_detail(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    await _signup_and_login_owner(client)
    response = await client.get(f"{INVENTORY_ENDPOINT}/{product['id']}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INV-001"


async def test_inventory_api_010_movement_history(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])
    await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock",
        json={"product_id": product["id"], "quantity": "10", "uom_id": pcs["id"]},
        headers=_idem(),
    )
    await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "5", "uom_id": pcs["id"]},
        headers=_idem(),
    )

    response = await client.get(f"{INVENTORY_ENDPOINT}/{product['id']}/movements")
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 2
    # Most recent first; running_balance reflects authoritative ledger order.
    assert data[0]["movement_type"] == "STOCK_IN"
    assert data[0]["running_balance"] == "15.000"
    assert data[1]["running_balance"] == "10.000"


async def test_inventory_api_011_movement_filtering(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])
    await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock",
        json={"product_id": product["id"], "quantity": "10", "uom_id": pcs["id"]},
        headers=_idem(),
    )
    await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "5", "uom_id": pcs["id"]},
        headers=_idem(),
    )

    response = await client.get(f"{INVENTORY_ENDPOINT}/{product['id']}/movements", params={"movement_type": "OPENING_STOCK"})
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["movement_type"] == "OPENING_STOCK"


async def test_inventory_api_012_source_reference_lookup(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])
    await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock",
        json={"product_id": product["id"], "quantity": "10", "uom_id": pcs["id"]},
        headers=_idem(),
    )
    response = await client.get(f"{INVENTORY_ENDPOINT}/{product['id']}/movements")
    entry = response.json()["data"][0]
    assert entry["source_type"] == "OPENING_STOCK"
    assert entry["source_id"] == product["id"]


async def test_inventory_api_013_cross_tenant_movement_protection(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])

    await _signup_and_login_owner(client)
    response = await client.get(f"{INVENTORY_ENDPOINT}/{product['id']}/movements")
    assert response.status_code == 404


# --- Concurrency ---


async def test_inventory_api_034_concurrent_stock_out_no_negative(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])
    await client.post(
        f"{INVENTORY_ENDPOINT}/stock-in",
        json={"product_id": product["id"], "quantity": "10", "uom_id": pcs["id"]},
        headers=_idem(),
    )

    async def _stock_out():
        return await client.post(
            f"{INVENTORY_ENDPOINT}/stock-out",
            json={"product_id": product["id"], "quantity": "8", "uom_id": pcs["id"]},
            headers=_idem(),
        )

    results = await asyncio.gather(_stock_out(), _stock_out())
    statuses = sorted(r.status_code for r in results)
    # Row-level locking (§40) must serialize these: 10 - 8 = 2 succeeds once,
    # the second 8-unit request must be rejected as insufficient stock —
    # never both succeeding (which would drive stock to -6).
    assert statuses == [201, 409]

    avail = await client.get(f"{INVENTORY_ENDPOINT}/availability/{product['id']}")
    assert avail.json()["data"]["available_quantity"] == "2.000"


# --- Immutability ---


async def test_inventory_api_037_ledger_update_rejected_at_db_level(client, db_session):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, "PCS", "Pieces")
    product = await _create_product(client, pcs["id"])
    created = await client.post(
        f"{INVENTORY_ENDPOINT}/opening-stock",
        json={"product_id": product["id"], "quantity": "10", "uom_id": pcs["id"]},
        headers=_idem(),
    )
    entry_id = created.json()["data"]["id"]

    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("UPDATE stock_ledger_entry SET quantity = 999 WHERE id = :id"), {"id": entry_id}
        )
        await db_session.commit()
    await db_session.rollback()
