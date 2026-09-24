"""PROMPT-009 test catalogue for /api/v1/products (and /api/v1/units).

Follows test_customers.py's structure and helper style. Covers the
security-critical subset of PROMPT-009 S66/S67 (tenant isolation, RBAC incl.
the Salesperson read-only boundary, SKU/HSN/unit/price validation,
duplicate detection, concurrency) — PRODUCT-API ids noted for traceability.
"""

import uuid

import pytest

PRODUCTS_ENDPOINT = "/api/v1/products"
UNITS_ENDPOINT = "/api/v1/units"
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
    return f"prod-{uuid.uuid4().hex[:12]}@example.com"


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
            "business_name": "Product Test Co",
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


async def _create_unit(client, code: str = "PCS", name: str = "Pieces") -> dict:
    response = await client.post(UNITS_ENDPOINT, json={"code": code, "name": name})
    assert response.status_code == 201
    return response.json()["data"]


async def _create_supplier(client, **overrides) -> dict:
    payload = {"name": "Sunrise Distributors", "contact_person": "Vijay Rao", "phone": _unique_phone(), "email": _unique_email()}
    payload.update(overrides)
    response = await client.post(SUPPLIERS_ENDPOINT, json=payload)
    assert response.status_code == 201
    return response.json()["data"]


def _valid_product_payload(base_uom_id: str, **overrides) -> dict:
    payload = {
        "sku": _unique_sku(),
        "name": "Basmati Rice 1kg",
        "base_uom_id": base_uom_id,
        "hsn_code": "1006",
        "gst_rate": "5.00",
        "cost_price": "80.00",
        "selling_price": "100.00",
        "mrp": "120.00",
    }
    payload.update(overrides)
    return payload


# --- Units ---


async def test_unit_create_and_list(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client, code="KG", name="Kilogram")
    assert unit["code"] == "KG"

    response = await client.get(UNITS_ENDPOINT)
    assert response.status_code == 200
    codes = {u["code"] for u in response.json()["data"]}
    assert "KG" in codes


async def test_unit_duplicate_code_rejected(client):
    await _signup_and_login_owner(client)
    await _create_unit(client, code="BOX", name="Box")
    response = await client.post(UNITS_ENDPOINT, json={"code": "BOX", "name": "Carton"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROD-006"


# --- PRODUCT-API-010/011/012/013/014/017/018/019: create ---


async def test_product_api_010_valid_creation(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["name"] == "Basmati Rice 1kg"
    assert data["status"] == "ACTIVE"
    assert data["base_uom"]["code"] == "PCS"
    assert data["unit_conversions"] == []
    # Reserved fields exist and are read-only zero — never invented input.
    assert data["reorder_level"] in ("0.000", "0")
    assert data["stock_qty_cache"] in ("0.000", "0")
    assert "category" not in data
    assert "brand" not in data


async def test_product_api_011_missing_required_field(client):
    await _signup_and_login_owner(client)
    response = await client.post(PRODUCTS_ENDPOINT, json={"name": "No SKU"})
    assert response.status_code == 422


async def test_product_api_012_duplicate_sku(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    sku = _unique_sku()
    first = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], sku=sku))
    assert first.status_code == 201
    second = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], sku=sku))
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "PROD-002"


async def test_product_api_013_invalid_hsn(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], hsn_code="12"))
    assert response.status_code == 422


async def test_product_api_014_invalid_gst_rate(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], gst_rate="150.00"))
    assert response.status_code == 422


async def test_product_api_015_invalid_unit(client):
    await _signup_and_login_owner(client)
    response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(str(uuid.uuid4())))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PROD-004"


async def test_product_api_017_invalid_cost_price(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], cost_price="-5.00"))
    assert response.status_code == 422


async def test_product_api_018_invalid_selling_price(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], selling_price="-1.00"))
    assert response.status_code == 422


async def test_product_api_019_invalid_mrp(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], mrp="-1.00"))
    assert response.status_code == 422


async def test_product_api_020_unauthorized_creation_no_session(client):
    response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(str(uuid.uuid4())))
    assert response.status_code == 401


async def test_product_api_020b_salesperson_cannot_create(client):
    # FR-PROD-04: Salesperson has read-only visibility — no create.
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    await _create_salesperson_and_login(client)
    response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    assert response.status_code == 403


async def test_product_api_021_tenant_id_not_client_controlled(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], tenant_id=str(uuid.uuid4())))
    assert response.status_code == 201  # extraneous field silently ignored


# --- PRODUCT-API-001/002/003: list / tenant isolation ---


async def test_product_api_001_003_list_and_tenant_isolation(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    tenant_a_id = created.json()["data"]["id"]

    list_a = await client.get(PRODUCTS_ENDPOINT)
    assert list_a.status_code == 200
    assert tenant_a_id in {item["id"] for item in list_a.json()["data"]}

    await _signup_and_login_owner(client)  # second, independent tenant
    list_b = await client.get(PRODUCTS_ENDPOINT)
    tenant_b_ids = {item["id"] for item in list_b.json()["data"]}
    assert tenant_a_id not in tenant_b_ids


async def test_product_api_002_unauthorized_list(client):
    response = await client.get(PRODUCTS_ENDPOINT)
    assert response.status_code == 401


async def test_product_api_004_search(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], name="Findme Snacks"))
    response = await client.get(PRODUCTS_ENDPOINT, params={"search": "Findme"})
    names = [item["name"] for item in response.json()["data"]]
    assert "Findme Snacks" in names


async def test_product_api_006_pagination(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    for _ in range(3):
        await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    response = await client.get(PRODUCTS_ENDPOINT, params={"page": 1, "page_size": 2})
    body = response.json()
    assert len(body["data"]) == 2
    assert body["pagination"]["total_items"] >= 3


async def test_product_salesperson_can_view(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))

    await _create_salesperson_and_login(client)
    response = await client.get(PRODUCTS_ENDPOINT)
    assert response.status_code == 200


# --- PRODUCT-API-007/008/009: detail ---


async def test_product_api_007_authorized_detail(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    product_id = created.json()["data"]["id"]
    response = await client.get(f"{PRODUCTS_ENDPOINT}/{product_id}")
    assert response.status_code == 200


async def test_product_api_008_not_found(client):
    await _signup_and_login_owner(client)
    response = await client.get(f"{PRODUCTS_ENDPOINT}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROD-001"


async def test_product_api_009_cross_tenant_detail_not_found(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    product_id = created.json()["data"]["id"]

    await _signup_and_login_owner(client)  # second tenant
    response = await client.get(f"{PRODUCTS_ENDPOINT}/{product_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROD-001"


# --- PRODUCT-API-022/023/024/025/026/027/028: update ---


async def test_product_api_022_valid_update(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    data = created.json()["data"]
    response = await client.patch(
        f"{PRODUCTS_ENDPOINT}/{data['id']}",
        json={"name": "Basmati Rice 5kg", "expected_row_version": data["row_version"]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Basmati Rice 5kg"


async def test_product_api_023_invalid_update(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    data = created.json()["data"]
    response = await client.patch(
        f"{PRODUCTS_ENDPOINT}/{data['id']}",
        json={"hsn_code": "abc", "expected_row_version": data["row_version"]},
    )
    assert response.status_code == 422


async def test_product_api_024_unauthorized_update_by_salesperson(client):
    # FR-PROD-04: Salesperson has read-only visibility — no edit.
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    data = created.json()["data"]

    await _create_salesperson_and_login(client)
    response = await client.patch(
        f"{PRODUCTS_ENDPOINT}/{data['id']}",
        json={"name": "Hacked", "expected_row_version": data["row_version"]},
    )
    assert response.status_code == 403


async def test_product_api_025_cross_tenant_update_not_found(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    data = created.json()["data"]

    await _signup_and_login_owner(client)
    response = await client.patch(
        f"{PRODUCTS_ENDPOINT}/{data['id']}",
        json={"name": "Hijacked", "expected_row_version": data["row_version"]},
    )
    assert response.status_code == 404


async def test_product_api_026_stale_row_version(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    data = created.json()["data"]

    response = await client.patch(
        f"{PRODUCTS_ENDPOINT}/{data['id']}",
        json={"name": "First Edit", "expected_row_version": data["row_version"]},
    )
    assert response.status_code == 200

    stale_response = await client.patch(
        f"{PRODUCTS_ENDPOINT}/{data['id']}",
        json={"name": "Stale Edit", "expected_row_version": data["row_version"]},
    )
    assert stale_response.status_code == 412


async def test_product_api_027_gst_change_audited_not_historical(client, db_session):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    data = created.json()["data"]

    response = await client.patch(
        f"{PRODUCTS_ENDPOINT}/{data['id']}",
        json={"gst_rate": "12.00", "expected_row_version": data["row_version"]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["gst_rate"] == "12.00"

    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.entity_id == uuid.UUID(data["id"]), AuditLog.action == "PRODUCT_UPDATED")
    )
    assert result.scalars().first() is not None


async def test_product_api_028_price_change(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    data = created.json()["data"]

    response = await client.patch(
        f"{PRODUCTS_ENDPOINT}/{data['id']}",
        json={"selling_price": "150.00", "expected_row_version": data["row_version"]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["selling_price"] == "150.00"


# --- PRODUCT-API-029/030/031/032: status ---


async def test_product_api_029_030_activate_deactivate(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    data = created.json()["data"]

    deactivate = await client.post(
        f"{PRODUCTS_ENDPOINT}/{data['id']}/deactivate", json={"expected_row_version": data["row_version"]}
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["data"]["status"] == "INACTIVE"

    activate = await client.post(
        f"{PRODUCTS_ENDPOINT}/{data['id']}/activate",
        json={"expected_row_version": deactivate.json()["data"]["row_version"]},
    )
    assert activate.status_code == 200
    assert activate.json()["data"]["status"] == "ACTIVE"


async def test_product_api_031_unauthorized_status_change_by_salesperson(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    data = created.json()["data"]

    await _create_salesperson_and_login(client)
    response = await client.post(
        f"{PRODUCTS_ENDPOINT}/{data['id']}/deactivate", json={"expected_row_version": data["row_version"]}
    )
    assert response.status_code == 403


async def test_product_api_032_deactivation_preserves_record(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    data = created.json()["data"]
    await client.post(f"{PRODUCTS_ENDPOINT}/{data['id']}/deactivate", json={"expected_row_version": data["row_version"]})

    response = await client.get(f"{PRODUCTS_ENDPOINT}/{data['id']}")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "INACTIVE"


# --- PRODUCT-API-033/034/035/036/037: unit conversion ---


async def test_product_api_033_valid_conversion(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, code="PCS", name="Pieces")
    carton = await _create_unit(client, code="CTN", name="Carton")
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(pcs["id"]))
    product_id = created.json()["data"]["id"]

    response = await client.post(
        f"{PRODUCTS_ENDPOINT}/{product_id}/conversions",
        json={"from_uom_id": carton["id"], "to_uom_id": pcs["id"], "conversion_factor": "24"},
    )
    assert response.status_code == 201
    assert response.json()["data"]["conversion_factor"] == "24"

    detail = await client.get(f"{PRODUCTS_ENDPOINT}/{product_id}")
    assert len(detail.json()["data"]["unit_conversions"]) == 1


async def test_product_api_034_zero_conversion_factor(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, code="PCS", name="Pieces")
    carton = await _create_unit(client, code="CTN", name="Carton")
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(pcs["id"]))
    product_id = created.json()["data"]["id"]

    response = await client.post(
        f"{PRODUCTS_ENDPOINT}/{product_id}/conversions",
        json={"from_uom_id": carton["id"], "to_uom_id": pcs["id"], "conversion_factor": "0"},
    )
    assert response.status_code == 422


async def test_product_api_035_negative_conversion_factor(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, code="PCS", name="Pieces")
    carton = await _create_unit(client, code="CTN", name="Carton")
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(pcs["id"]))
    product_id = created.json()["data"]["id"]

    response = await client.post(
        f"{PRODUCTS_ENDPOINT}/{product_id}/conversions",
        json={"from_uom_id": carton["id"], "to_uom_id": pcs["id"], "conversion_factor": "-5"},
    )
    assert response.status_code == 422


async def test_product_api_036_invalid_unit(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, code="PCS", name="Pieces")
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(pcs["id"]))
    product_id = created.json()["data"]["id"]

    response = await client.post(
        f"{PRODUCTS_ENDPOINT}/{product_id}/conversions",
        json={"from_uom_id": str(uuid.uuid4()), "to_uom_id": pcs["id"], "conversion_factor": "24"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PROD-004"


async def test_product_api_037_duplicate_conversion(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, code="PCS", name="Pieces")
    carton = await _create_unit(client, code="CTN", name="Carton")
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(pcs["id"]))
    product_id = created.json()["data"]["id"]

    first = await client.post(
        f"{PRODUCTS_ENDPOINT}/{product_id}/conversions",
        json={"from_uom_id": carton["id"], "to_uom_id": pcs["id"], "conversion_factor": "24"},
    )
    assert first.status_code == 201
    second = await client.post(
        f"{PRODUCTS_ENDPOINT}/{product_id}/conversions",
        json={"from_uom_id": carton["id"], "to_uom_id": pcs["id"], "conversion_factor": "12"},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "PROD-005"


async def test_product_api_self_conversion_rejected(client):
    await _signup_and_login_owner(client)
    pcs = await _create_unit(client, code="PCS", name="Pieces")
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(pcs["id"]))
    product_id = created.json()["data"]["id"]

    response = await client.post(
        f"{PRODUCTS_ENDPOINT}/{product_id}/conversions",
        json={"from_uom_id": pcs["id"], "to_uom_id": pcs["id"], "conversion_factor": "1"},
    )
    assert response.status_code == 422


# --- GST rate: now mandatory, closed slab set (user-requested follow-up) ---


async def test_product_gst_rate_required(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    payload = _valid_product_payload(unit["id"])
    del payload["gst_rate"]
    response = await client.post(PRODUCTS_ENDPOINT, json=payload)
    assert response.status_code == 422


async def test_product_gst_rate_must_be_a_valid_slab(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    # 7 is a real, in-range percentage but not one of the standard GST slabs.
    response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], gst_rate="7"))
    assert response.status_code == 422


async def test_product_gst_rate_accepts_every_standard_slab(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    for slab in ("0", "3", "5", "12", "18", "28"):
        response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], gst_rate=slab))
        assert response.status_code == 201, slab
        assert response.json()["data"]["gst_rate"] == f"{slab}.00"


async def test_product_update_cannot_clear_gst_rate(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    data = created.json()["data"]
    response = await client.patch(
        f"{PRODUCTS_ENDPOINT}/{data['id']}", json={"gst_rate": None, "expected_row_version": data["row_version"]}
    )
    assert response.status_code == 422


# --- Supplier linkage (user-requested follow-up) ---


async def test_product_create_with_supplier(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    supplier = await _create_supplier(client)

    response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], supplier_id=supplier["id"]))
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["supplier"]["id"] == supplier["id"]
    assert data["supplier"]["name"] == supplier["name"]
    assert data["supplier"]["phone"] == supplier["phone"]


async def test_product_create_without_supplier_is_valid(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    response = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"]))
    assert response.status_code == 201
    assert response.json()["data"]["supplier"] is None


async def test_product_invalid_supplier_rejected(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    response = await client.post(
        PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], supplier_id=str(uuid.uuid4()))
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PROD-007"


async def test_product_cross_tenant_supplier_rejected(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    other_tenant_supplier = await _create_supplier(client)

    # A fresh tenant must not be able to attach another tenant's supplier.
    await _signup_and_login_owner(client)
    unit2 = await _create_unit(client)
    response = await client.post(
        PRODUCTS_ENDPOINT, json=_valid_product_payload(unit2["id"], supplier_id=other_tenant_supplier["id"])
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PROD-007"


async def test_product_update_supplier(client):
    await _signup_and_login_owner(client)
    unit = await _create_unit(client)
    supplier_a = await _create_supplier(client, name="Supplier A")
    supplier_b = await _create_supplier(client, name="Supplier B")

    created = await client.post(PRODUCTS_ENDPOINT, json=_valid_product_payload(unit["id"], supplier_id=supplier_a["id"]))
    data = created.json()["data"]
    assert data["supplier"]["id"] == supplier_a["id"]

    updated = await client.patch(
        f"{PRODUCTS_ENDPOINT}/{data['id']}",
        json={"supplier_id": supplier_b["id"], "expected_row_version": data["row_version"]},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["supplier"]["id"] == supplier_b["id"]

    cleared = await client.patch(
        f"{PRODUCTS_ENDPOINT}/{data['id']}",
        json={"supplier_id": None, "expected_row_version": updated.json()["data"]["row_version"]},
    )
    assert cleared.status_code == 200
    assert cleared.json()["data"]["supplier"] is None
