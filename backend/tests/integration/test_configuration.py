"""Configuration Center test catalogue — /api/v1/configuration/*.

Follows test_customers.py's structure and helper style. Covers the
security-critical subset: lazy provisioning, RBAC (Manager view-only,
Salesperson none), tenant isolation, hex-color validation, optimistic
concurrency, and logo upload validation (type/size/removal).
"""

import io
import uuid

import pytest

CONFIG_ENDPOINT = "/api/v1/configuration/invoice-template-config"
LOGO_ENDPOINT = "/api/v1/configuration/business-logo"
SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"
USERS_ENDPOINT = "/api/v1/users"
RESET_ENDPOINT = "/api/v1/auth/reset-password"

OWNER_PASSWORD = "SecurePass123"
OTHER_PASSWORD = "AnotherSecurePass456"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _unique_email() -> str:
    return f"cfg-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    from app.core.rate_limit import reset_rate_limits
    from app.core.login_lockout import reset_all

    reset_rate_limits()
    reset_all()
    yield


async def _signup_and_login_owner(client, business_name: str = "Config Test Co") -> dict:
    phone = _unique_phone()
    payload = {
        "organization": {
            "business_name": business_name, "address_line1": "1 Main St", "city": "Chennai",
            "state_code": "33", "pin_code": "600001", "gstin": None,
        },
        "owner": {"phone": phone, "email": _unique_email(), "password": OWNER_PASSWORD, "confirm_password": OWNER_PASSWORD},
    }
    signup_response = await client.post(SIGNUP_ENDPOINT, json=payload, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert signup_response.status_code == 201
    login_response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": OWNER_PASSWORD})
    assert login_response.status_code == 200
    return signup_response.json()["data"]


async def _create_user_and_login(client, *, role: str) -> None:
    from app.services.password_recovery.provider import ConsolePasswordRecoveryProvider

    phone = _unique_phone()
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "U", "phone": phone, "email": _unique_email(), "role": role}
    )
    assert create_response.status_code == 201
    reset_token = ConsolePasswordRecoveryProvider.outbox[-1].reset_link.split("token=")[1]
    reset_response = await client.post(
        RESET_ENDPOINT, json={"token": reset_token, "new_password": OTHER_PASSWORD, "confirm_password": OTHER_PASSWORD}
    )
    assert reset_response.status_code == 200
    login = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": OTHER_PASSWORD})
    assert login.status_code == 200


def _valid_update_payload(**overrides) -> dict:
    payload = {
        "template_id": "MODERN",
        "primary_color": "#123ABC",
        "secondary_color": "#0F172A",
        "accent_color": "#10B981",
        "text_color": "#111827",
        "table_header_color": "#E5E7EB",
        "show_logo": True,
        "show_business_address": True,
        "show_gstin": True,
        "show_customer_gstin": True,
        "show_hsn": True,
        "show_discount": True,
        "show_tax_breakup": True,
        "show_bank_details": False,
        "show_terms": True,
        "show_amount_in_words": True,
        "show_round_off": True,
        "terms_text": "Goods once sold cannot be returned.",
        "bank_name": None, "bank_account_name": None, "bank_account_number": None, "bank_ifsc": None, "bank_upi_id": None,
        "expected_row_version": 1,
    }
    payload.update(overrides)
    return payload


# --- Lazy provisioning + defaults ---


async def test_get_config_lazily_provisions_with_defaults(client):
    await _signup_and_login_owner(client)
    response = await client.get(CONFIG_ENDPOINT)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["template_id"] == "CLASSIC"
    assert data["primary_color"] == "#2563EB"
    assert data["row_version"] == 1
    assert data["logo_data_uri"] is None


# --- Update / save ---


async def test_update_config_saves_and_returns_new_values(client):
    await _signup_and_login_owner(client)
    await client.get(CONFIG_ENDPOINT)  # provision

    response = await client.put(CONFIG_ENDPOINT, json=_valid_update_payload())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["template_id"] == "MODERN"
    assert data["primary_color"] == "#123ABC"
    assert data["row_version"] == 2

    refetch = await client.get(CONFIG_ENDPOINT)
    assert refetch.json()["data"]["template_id"] == "MODERN"


async def test_update_rejects_invalid_hex_color(client):
    await _signup_and_login_owner(client)
    response = await client.put(CONFIG_ENDPOINT, json=_valid_update_payload(primary_color="not-a-color"))
    assert response.status_code == 422


async def test_update_rejects_invalid_template_id(client):
    await _signup_and_login_owner(client)
    response = await client.put(CONFIG_ENDPOINT, json=_valid_update_payload(template_id="FANCY"))
    assert response.status_code == 422


async def test_update_concurrency_conflict(client):
    await _signup_and_login_owner(client)
    await client.get(CONFIG_ENDPOINT)  # provision, row_version=1

    first = await client.put(CONFIG_ENDPOINT, json=_valid_update_payload(expected_row_version=1))
    assert first.status_code == 200  # now row_version=2

    stale = await client.put(CONFIG_ENDPOINT, json=_valid_update_payload(expected_row_version=1))
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "CONCURRENCY_CONFLICT" or "row_version" in str(stale.json())


# --- RBAC ---


async def test_manager_can_view_but_not_manage(client):
    await _signup_and_login_owner(client)
    await _create_user_and_login(client, role="MANAGER")

    view_response = await client.get(CONFIG_ENDPOINT)
    assert view_response.status_code == 200

    update_response = await client.put(CONFIG_ENDPOINT, json=_valid_update_payload())
    assert update_response.status_code == 403


async def test_salesperson_has_no_configuration_access(client):
    await _signup_and_login_owner(client)
    await _create_user_and_login(client, role="SALESPERSON")

    view_response = await client.get(CONFIG_ENDPOINT)
    assert view_response.status_code == 403


async def test_unauthenticated_request_rejected(client):
    response = await client.get(CONFIG_ENDPOINT)
    assert response.status_code == 401


# --- Tenant isolation ---


async def test_tenant_isolation_on_configuration(client):
    await _signup_and_login_owner(client, business_name="Tenant A Co")
    await client.put(CONFIG_ENDPOINT, json=_valid_update_payload(template_id="MODERN", expected_row_version=1))

    await _signup_and_login_owner(client, business_name="Tenant B Co")
    response = await client.get(CONFIG_ENDPOINT)
    assert response.status_code == 200
    assert response.json()["data"]["template_id"] == "CLASSIC"  # Tenant B's own default, not Tenant A's MODERN


# --- Logo upload ---


async def test_logo_upload_and_removal(client):
    await _signup_and_login_owner(client)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # not a real image, but a valid-looking PNG header for this test

    files = {"file": ("logo.png", io.BytesIO(png_bytes), "image/png")}
    upload_response = await client.post(LOGO_ENDPOINT, files=files)
    assert upload_response.status_code == 200
    data = upload_response.json()["data"]
    assert data["logo_data_uri"].startswith("data:image/png;base64,")

    remove_response = await client.delete(LOGO_ENDPOINT)
    assert remove_response.status_code == 200
    assert remove_response.json()["data"]["logo_data_uri"] is None


async def test_logo_upload_rejects_unsupported_type(client):
    await _signup_and_login_owner(client)
    files = {"file": ("logo.svg", io.BytesIO(b"<svg></svg>"), "image/svg+xml")}
    response = await client.post(LOGO_ENDPOINT, files=files)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CFG-003"


async def test_logo_upload_rejects_oversized_file(client):
    await _signup_and_login_owner(client)
    oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (600 * 1024)
    files = {"file": ("logo.png", io.BytesIO(oversized), "image/png")}
    response = await client.post(LOGO_ENDPOINT, files=files)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CFG-004"


async def test_logo_upload_rejects_empty_file(client):
    await _signup_and_login_owner(client)
    files = {"file": ("logo.png", io.BytesIO(b""), "image/png")}
    response = await client.post(LOGO_ENDPOINT, files=files)
    assert response.status_code == 422
