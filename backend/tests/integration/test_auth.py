"""PROMPT-003 S39 test catalogue for /api/v1/auth/login, /logout, /me, /session-status."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.rate_limit import reset_rate_limits
from app.models.auth_session import AuthSession
from app.models.user import User

SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"
LOGOUT_ENDPOINT = "/api/v1/auth/logout"
ME_ENDPOINT = "/api/v1/auth/me"
STATUS_ENDPOINT = "/api/v1/auth/session-status"

TEST_PASSWORD = "SecurePass123"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _signup_payload(phone: str) -> dict:
    return {
        "organization": {
            "business_name": "Auth Test Co",
            "address_line1": "1 Main St",
            "city": "Chennai",
            "state_code": "33",
            "pin_code": "600001",
            "gstin": None,
        },
        "owner": {"phone": phone, "email": "owner@example.com", "password": TEST_PASSWORD, "confirm_password": TEST_PASSWORD},
    }


async def _create_active_user(client) -> tuple[str, dict]:
    phone = _unique_phone()
    response = await client.post(SIGNUP_ENDPOINT, json=_signup_payload(phone), headers={"Idempotency-Key": str(uuid.uuid4())})
    assert response.status_code == 201
    return phone, response.json()["data"]


@pytest.fixture(autouse=True)
def _reset_rate_limits_between_tests():
    reset_rate_limits()
    from app.core.login_lockout import reset_all

    reset_all()
    yield


async def test_auth_api_001_valid_credentials(client):
    phone, signup_data = await _create_active_user(client)
    response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": TEST_PASSWORD})
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["user"]["id"] == signup_data["owner_user_id"]
    assert body["tenant"]["id"] == signup_data["tenant_id"]


async def test_auth_api_002_invalid_password(client):
    phone, _ = await _create_active_user(client)
    response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": "WrongPassword123"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH-001"


async def test_auth_api_003_invalid_login_identifier(client):
    response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": "9000000000", "password": TEST_PASSWORD})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH-001"


async def test_auth_api_004_missing_identifier(client):
    response = await client.post(LOGIN_ENDPOINT, json={"password": TEST_PASSWORD})
    assert response.status_code == 422


async def test_auth_api_005_missing_password(client):
    response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": "9000000000"})
    assert response.status_code == 422


async def test_auth_api_006_disabled_account(client, db_session):
    phone, signup_data = await _create_active_user(client)

    user = (await db_session.execute(select(User).where(User.id == uuid.UUID(signup_data["owner_user_id"])))).scalar_one()
    user.status = "INACTIVE"
    await db_session.commit()

    response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": TEST_PASSWORD})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTH-002"


async def test_auth_api_007_successful_session_creation(client, db_session):
    phone, signup_data = await _create_active_user(client)
    response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": TEST_PASSWORD})
    assert response.status_code == 200
    assert "access_token" in response.cookies

    result = await db_session.execute(
        select(AuthSession).where(AuthSession.user_id == uuid.UUID(signup_data["owner_user_id"]))
    )
    sessions = result.scalars().all()
    assert len(sessions) == 1
    assert sessions[0].revoked_at is None


async def test_auth_api_008_tenant_resolution(client):
    phone, signup_data = await _create_active_user(client)
    response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": TEST_PASSWORD})
    body = response.json()["data"]
    assert body["tenant"]["business_name"] == "Auth Test Co"
    assert body["tenant"]["id"] == signup_data["tenant_id"]


async def test_auth_api_009_role_resolution(client):
    phone, _ = await _create_active_user(client)
    response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": TEST_PASSWORD})
    assert response.json()["data"]["user"]["role"] == "OWNER"


async def test_auth_api_010_permission_resolution(client):
    # PROMPT-006 populates role_permission for the first time — Owner now
    # resolves real effective permissions (was documented as [] in
    # PROMPT-003-NOTES.md, pending exactly this work).
    phone, _ = await _create_active_user(client)
    response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": TEST_PASSWORD})
    permissions = response.json()["data"]["permissions"]
    assert "users.view" in permissions
    assert "users.create" in permissions


async def test_auth_api_011_rate_limiting(client):
    settings = get_settings()
    phone = _unique_phone()
    for _ in range(settings.login_rate_limit_per_ip_per_hour):
        await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": "wrong"})

    response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": "wrong"})
    assert response.status_code == 429


async def test_auth_api_012_sensitive_data_not_returned(client):
    phone, _ = await _create_active_user(client)
    response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": TEST_PASSWORD})
    text_lower = response.text.lower()
    assert "password" not in text_lower
    assert "$2b$" not in response.text  # bcrypt hash prefix must never leak


async def test_auth_api_013_valid_logout(client):
    phone, _ = await _create_active_user(client)
    await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": TEST_PASSWORD})
    response = await client.post(LOGOUT_ENDPOINT)
    assert response.status_code == 204


async def test_auth_api_014_repeated_logout(client):
    phone, _ = await _create_active_user(client)
    await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": TEST_PASSWORD})
    first = await client.post(LOGOUT_ENDPOINT)
    assert first.status_code == 204

    second = await client.post(LOGOUT_ENDPOINT)
    assert second.status_code == 401  # nothing left to log out of — safe failure


async def test_auth_api_015_access_after_logout(client):
    phone, _ = await _create_active_user(client)
    await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": TEST_PASSWORD})
    await client.post(LOGOUT_ENDPOINT)

    response = await client.get(ME_ENDPOINT)
    assert response.status_code == 401


async def test_auth_api_016_valid_session(client):
    phone, signup_data = await _create_active_user(client)
    await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": TEST_PASSWORD})

    response = await client.get(ME_ENDPOINT)
    assert response.status_code == 200
    assert response.json()["data"]["user_id"] == signup_data["owner_user_id"]

    status_response = await client.get(STATUS_ENDPOINT)
    assert status_response.status_code == 200
    assert status_response.json()["data"]["authenticated"] is True


async def test_auth_api_018_invalid_session(client):
    client.cookies.set("access_token", "not-a-real-jwt")
    response = await client.get(ME_ENDPOINT)
    assert response.status_code == 401


async def test_auth_api_019_revoked_session(client, db_session):
    phone, _ = await _create_active_user(client)
    await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": TEST_PASSWORD})

    # Directly revoke server-side (simulating logout from elsewhere / admin action).
    result = await db_session.execute(select(AuthSession).order_by(AuthSession.created_at.desc()))
    session_record = result.scalars().first()
    from app.db.base import utcnow

    session_record.revoked_at = utcnow()
    await db_session.commit()

    response = await client.get(ME_ENDPOINT)
    assert response.status_code == 401


async def test_auth_api_020_cross_tenant_isolation(client):
    phone_a, signup_a = await _create_active_user(client)
    phone_b, signup_b = await _create_active_user(client)
    assert signup_a["tenant_id"] != signup_b["tenant_id"]

    login_a = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone_a, "password": TEST_PASSWORD})
    assert login_a.json()["data"]["tenant"]["id"] == signup_a["tenant_id"]

    me_a = await client.get(ME_ENDPOINT)
    # The cookie jar now holds tenant A's session — it must resolve ONLY to
    # tenant A, never tenant B, regardless of what tenant B's ID happens to be.
    assert me_a.json()["data"]["tenant_id"] == signup_a["tenant_id"]
    assert me_a.json()["data"]["tenant_id"] != signup_b["tenant_id"]
