"""PROMPT-004 S42 test catalogue for forgot-password / reset-password."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.rate_limit import reset_rate_limits
from app.models.auth_session import AuthSession
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.services.password_recovery.provider import ConsolePasswordRecoveryProvider

SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"
FORGOT_ENDPOINT = "/api/v1/auth/forgot-password"
VALIDATE_ENDPOINT = "/api/v1/auth/reset-password/validate"
RESET_ENDPOINT = "/api/v1/auth/reset-password"

ORIGINAL_PASSWORD = "SecurePass123"
NEW_PASSWORD = "AnotherSecurePass456"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    reset_rate_limits()
    ConsolePasswordRecoveryProvider.outbox.clear()
    yield


async def _create_active_user(client, *, email: str | None = None) -> tuple[str, str, dict]:
    phone = _unique_phone()
    email = email or _unique_email()
    payload = {
        "organization": {
            "business_name": "Reset Test Co",
            "address_line1": "1 Main St",
            "city": "Chennai",
            "state_code": "33",
            "pin_code": "600001",
            "gstin": None,
        },
        "owner": {"phone": phone, "email": email, "password": ORIGINAL_PASSWORD, "confirm_password": ORIGINAL_PASSWORD},
    }
    response = await client.post(SIGNUP_ENDPOINT, json=payload, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert response.status_code == 201
    return phone, email, response.json()["data"]


def _last_sent_token(reset_link: str) -> str:
    return reset_link.split("token=")[1]


async def test_auth_reset_api_001_valid_recovery_request(client):
    _, email, _ = await _create_active_user(client)
    response = await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})
    assert response.status_code == 200
    assert len(ConsolePasswordRecoveryProvider.outbox) == 1
    assert ConsolePasswordRecoveryProvider.outbox[0].to_email == email


async def test_auth_reset_api_002_003_unknown_identifier_same_generic_response(client):
    known_response = await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": _unique_email()})
    unknown_response = await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": "nobody-here@example.com"})

    assert known_response.status_code == unknown_response.status_code == 200
    assert known_response.json()["data"]["message"] == unknown_response.json()["data"]["message"]
    # Neither request should have sent anything (first identifier isn't registered either)
    assert len(ConsolePasswordRecoveryProvider.outbox) == 0


async def test_auth_reset_api_004_missing_identifier(client):
    response = await client.post(FORGOT_ENDPOINT, json={})
    assert response.status_code == 422


async def test_auth_reset_api_005_invalid_identifier_format(client):
    response = await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": "not-an-email"})
    assert response.status_code == 422


async def test_auth_reset_api_006_rate_limiting(client):
    settings = get_settings()
    email = _unique_email()
    for _ in range(settings.password_reset_identifier_rate_limit_per_hour):
        await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})

    response = await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})
    assert response.status_code == 429
    # Still the generic message — rate limiting must not leak account existence.
    assert response.json()["error"]["message"] == "If an account matches the information provided, recovery instructions will be sent."


async def test_disabled_account_gets_generic_response_and_no_email(client, db_session):
    _, email, signup_data = await _create_active_user(client)
    user = (await db_session.execute(select(User).where(User.id == uuid.UUID(signup_data["owner_user_id"])))).scalar_one()
    user.status = "INACTIVE"
    await db_session.commit()

    response = await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})
    assert response.status_code == 200
    assert len(ConsolePasswordRecoveryProvider.outbox) == 0


async def test_auth_reset_api_008_valid_token_and_016_018_successful_update(client, db_session):
    phone, email, _ = await _create_active_user(client)
    await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})
    token = _last_sent_token(ConsolePasswordRecoveryProvider.outbox[0].reset_link)

    valid_check = await client.post(VALIDATE_ENDPOINT, json={"token": token})
    assert valid_check.json()["data"]["valid"] is True

    reset_response = await client.post(
        RESET_ENDPOINT, json={"token": token, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}
    )
    assert reset_response.status_code == 200

    # AUTH-RESET-API-017: old password rejected.
    old_login = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": ORIGINAL_PASSWORD})
    assert old_login.status_code == 401

    # AUTH-RESET-API-018: new password accepted.
    new_login = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": NEW_PASSWORD})
    assert new_login.status_code == 200


async def test_auth_reset_api_009_invalid_token(client):
    response = await client.post(
        RESET_ENDPOINT, json={"token": "not-a-real-token", "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "RESET-002"


async def test_auth_reset_api_010_expired_token(client, db_session):
    _, email, _ = await _create_active_user(client)
    await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})
    token = _last_sent_token(ConsolePasswordRecoveryProvider.outbox[0].reset_link)

    from datetime import datetime, timedelta, timezone

    record = (await db_session.execute(select(PasswordResetToken).order_by(PasswordResetToken.created_at.desc()))).scalars().first()
    record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()

    response = await client.post(
        RESET_ENDPOINT, json={"token": token, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "RESET-003"


async def test_auth_reset_api_011_019_consumed_token_cannot_be_reused(client):
    _, email, _ = await _create_active_user(client)
    await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})
    token = _last_sent_token(ConsolePasswordRecoveryProvider.outbox[0].reset_link)

    first = await client.post(
        RESET_ENDPOINT, json={"token": token, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}
    )
    assert first.status_code == 200

    second = await client.post(
        RESET_ENDPOINT, json={"token": token, "new_password": "YetAnotherPass789", "confirm_password": "YetAnotherPass789"}
    )
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "RESET-004"


async def test_auth_reset_api_012_revoked_token_via_second_request(client, db_session):
    _, email, _ = await _create_active_user(client)
    await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})
    first_token = _last_sent_token(ConsolePasswordRecoveryProvider.outbox[0].reset_link)

    # A second forgot-password request must revoke the first token (S19).
    await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})

    response = await client.post(
        RESET_ENDPOINT, json={"token": first_token, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "RESET-005"


async def test_auth_reset_api_013_token_tampering(client):
    _, email, _ = await _create_active_user(client)
    await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})
    token = _last_sent_token(ConsolePasswordRecoveryProvider.outbox[0].reset_link)
    tampered = token[:-4] + "xxxx"

    response = await client.post(
        RESET_ENDPOINT, json={"token": tampered, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "RESET-002"


async def test_auth_reset_api_014_password_mismatch(client):
    _, email, _ = await _create_active_user(client)
    await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})
    token = _last_sent_token(ConsolePasswordRecoveryProvider.outbox[0].reset_link)

    response = await client.post(
        RESET_ENDPOINT, json={"token": token, "new_password": NEW_PASSWORD, "confirm_password": "Different123"}
    )
    assert response.status_code == 422


async def test_auth_reset_api_015_weak_password(client):
    _, email, _ = await _create_active_user(client)
    await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})
    token = _last_sent_token(ConsolePasswordRecoveryProvider.outbox[0].reset_link)

    response = await client.post(RESET_ENDPOINT, json={"token": token, "new_password": "abc", "confirm_password": "abc"})
    assert response.status_code == 422


async def test_auth_reset_api_020_session_invalidation(client, db_session):
    phone, email, signup_data = await _create_active_user(client)
    await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": ORIGINAL_PASSWORD})

    active_before = (
        await db_session.execute(
            select(AuthSession).where(
                AuthSession.user_id == uuid.UUID(signup_data["owner_user_id"]), AuthSession.revoked_at.is_(None)
            )
        )
    ).scalars().all()
    assert len(active_before) == 1

    await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})
    token = _last_sent_token(ConsolePasswordRecoveryProvider.outbox[0].reset_link)
    await client.post(RESET_ENDPOINT, json={"token": token, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD})

    active_after = (
        await db_session.execute(
            select(AuthSession).where(
                AuthSession.user_id == uuid.UUID(signup_data["owner_user_id"]), AuthSession.revoked_at.is_(None)
            )
        )
    ).scalars().all()
    assert len(active_after) == 0

    # The cookie from the pre-reset login must no longer authenticate.
    me_response = await client.get("/api/v1/auth/me")
    assert me_response.status_code == 401


async def test_auth_reset_api_021_cross_tenant_token_isolation(client, db_session):
    _, email_a, signup_a = await _create_active_user(client)
    _, email_b, signup_b = await _create_active_user(client)

    await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email_a})
    token_a = _last_sent_token(ConsolePasswordRecoveryProvider.outbox[0].reset_link)

    from app.db.tenant_context import set_tenant_context

    await set_tenant_context(db_session, uuid.UUID(signup_a["tenant_id"]))  # inspect tenant A's rows explicitly
    record = (
        await db_session.execute(select(PasswordResetToken).order_by(PasswordResetToken.created_at.desc()))
    ).scalars().first()
    # The token belongs to user A's tenant only — resetting with it must never
    # touch user B, regardless of what tenant_id is implied anywhere else.
    assert str(record.tenant_id) == signup_a["tenant_id"]
    assert str(record.tenant_id) != signup_b["tenant_id"]
    assert str(record.user_id) == signup_a["owner_user_id"]


async def test_auth_reset_api_022_reset_password_rate_limiting(client):
    settings = get_settings()
    for _ in range(settings.password_reset_rate_limit_per_ip_per_hour):
        await client.post(
            RESET_ENDPOINT, json={"token": "x", "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}
        )
    response = await client.post(
        RESET_ENDPOINT, json={"token": "x", "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}
    )
    assert response.status_code == 429


async def test_password_and_token_never_appear_in_response(client):
    _, email, _ = await _create_active_user(client)
    forgot_response = await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})
    assert "password" not in forgot_response.text.lower()

    token = _last_sent_token(ConsolePasswordRecoveryProvider.outbox[0].reset_link)
    reset_response = await client.post(
        RESET_ENDPOINT, json={"token": token, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}
    )
    assert NEW_PASSWORD not in reset_response.text
    assert token not in reset_response.text


async def test_role_and_tenant_unchanged_after_reset(client, db_session):
    phone, email, signup_data = await _create_active_user(client)
    await client.post(FORGOT_ENDPOINT, json={"recovery_identifier": email})
    token = _last_sent_token(ConsolePasswordRecoveryProvider.outbox[0].reset_link)
    await client.post(RESET_ENDPOINT, json={"token": token, "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD})

    login_response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": NEW_PASSWORD})
    data = login_response.json()["data"]
    assert data["user"]["role"] == "OWNER"
    assert data["tenant"]["id"] == signup_data["tenant_id"]
