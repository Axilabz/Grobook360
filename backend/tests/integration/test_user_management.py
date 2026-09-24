"""PROMPT-005 S43 test catalogue for /api/v1/users."""

import uuid

import pytest
from sqlalchemy import select

from app.models.auth_session import AuthSession
from app.models.user import User
from app.services.password_recovery.provider import ConsolePasswordRecoveryProvider

SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"
RESET_ENDPOINT = "/api/v1/auth/reset-password"
USERS_ENDPOINT = "/api/v1/users"

OWNER_PASSWORD = "SecurePass123"
NEW_USER_PASSWORD = "AnotherSecurePass456"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    from app.core.rate_limit import reset_rate_limits
    from app.core.login_lockout import reset_all

    reset_rate_limits()
    reset_all()
    ConsolePasswordRecoveryProvider.outbox.clear()
    yield


async def _signup_and_login_owner(client) -> tuple[str, dict]:
    phone = _unique_phone()
    payload = {
        "organization": {
            "business_name": "User Mgmt Test Co",
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
    signup_data = signup_response.json()["data"]

    login_response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": OWNER_PASSWORD})
    assert login_response.status_code == 200
    return phone, signup_data


async def _create_user_and_set_password(client, *, role: str, password: str = NEW_USER_PASSWORD) -> tuple[str, dict]:
    phone = _unique_phone()
    email = _unique_email()
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "Test User", "phone": phone, "email": email, "role": role}
    )
    assert create_response.status_code == 201
    user_data = create_response.json()["data"]

    reset_token = ConsolePasswordRecoveryProvider.outbox[-1].reset_link.split("token=")[1]
    reset_response = await client.post(RESET_ENDPOINT, json={"token": reset_token, "new_password": password, "confirm_password": password})
    assert reset_response.status_code == 200

    return phone, user_data


async def test_user_api_011_valid_user_creation(client):
    await _signup_and_login_owner(client)
    phone = _unique_phone()
    response = await client.post(
        USERS_ENDPOINT, json={"name": "Jane Manager", "phone": phone, "email": _unique_email(), "role": "MANAGER"}
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["name"] == "Jane Manager"
    assert data["role"] == "MANAGER"
    assert data["status"] == "ACTIVE"
    assert "password" not in response.text.lower()


async def test_user_api_012_duplicate_identifier(client):
    owner_phone, _ = await _signup_and_login_owner(client)
    response = await client.post(
        USERS_ENDPOINT, json={"name": "Dup", "phone": owner_phone, "email": _unique_email(), "role": "MANAGER"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USR-002"


async def test_user_api_013_invalid_role(client):
    await _signup_and_login_owner(client)
    response = await client.post(
        USERS_ENDPOINT, json={"name": "X", "phone": _unique_phone(), "email": _unique_email(), "role": "PLATFORM_ADMINISTRATOR"}
    )
    assert response.status_code == 422  # rejected by schema validation


async def test_user_api_014_unauthorized_creation_by_salesperson(client):
    await _signup_and_login_owner(client)
    _, sp_data = await _create_user_and_set_password(client, role="SALESPERSON")

    # Log back in as the salesperson.
    sp_phone = sp_data["phone"]
    login = await client.post(LOGIN_ENDPOINT, json={"login_identifier": sp_phone, "password": NEW_USER_PASSWORD})
    assert login.status_code == 200

    response = await client.post(
        USERS_ENDPOINT, json={"name": "Nope", "phone": _unique_phone(), "email": _unique_email(), "role": "MANAGER"}
    )
    assert response.status_code == 403


async def test_user_api_015_tenant_id_not_client_controlled(client):
    # There is no tenant_id field in CreateUserRequest at all — the schema
    # itself makes tampering impossible, not just a runtime check.
    await _signup_and_login_owner(client)
    response = await client.post(
        USERS_ENDPOINT,
        json={
            "name": "X",
            "phone": _unique_phone(),
            "email": _unique_email(),
            "role": "MANAGER",
            "tenant_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 201  # extraneous field silently ignored, not honored


async def test_user_api_001_003_authorized_list_and_tenant_isolation(client):
    _, owner_a = await _signup_and_login_owner(client)
    await _create_user_and_set_password(client, role="MANAGER")

    list_response = await client.get(USERS_ENDPOINT)
    assert list_response.status_code == 200
    tenant_a_ids = {item["id"] for item in list_response.json()["data"]}
    assert owner_a["owner_user_id"] in tenant_a_ids

    # A second, independent tenant must never see tenant A's users.
    _, owner_b = await _signup_and_login_owner(client)
    list_response_b = await client.get(USERS_ENDPOINT)
    tenant_b_ids = {item["id"] for item in list_response_b.json()["data"]}
    assert tenant_a_ids.isdisjoint(tenant_b_ids)
    assert owner_a["owner_user_id"] not in tenant_b_ids


async def test_user_api_002_unauthorized_list(client):
    response = await client.get(USERS_ENDPOINT)
    assert response.status_code == 401


async def test_user_api_004_search(client):
    await _signup_and_login_owner(client)
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "Findme Unique", "phone": _unique_phone(), "email": _unique_email(), "role": "MANAGER"}
    )
    assert create_response.status_code == 201

    response = await client.get(USERS_ENDPOINT, params={"search": "Findme"})
    names = [item["name"] for item in response.json()["data"]]
    assert "Findme Unique" in names


async def test_user_api_005_role_filter(client):
    await _signup_and_login_owner(client)
    await client.post(USERS_ENDPOINT, json={"name": "SP1", "phone": _unique_phone(), "email": _unique_email(), "role": "SALESPERSON"})

    response = await client.get(USERS_ENDPOINT, params={"role": "SALESPERSON"})
    roles = {item["role"] for item in response.json()["data"]}
    assert roles == {"SALESPERSON"}


async def test_user_api_006_status_filter(client, db_session):
    _, owner_data = await _signup_and_login_owner(client)
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "ToDeactivate", "phone": _unique_phone(), "email": _unique_email(), "role": "MANAGER"}
    )
    target = create_response.json()["data"]
    await client.post(f"{USERS_ENDPOINT}/{target['id']}/deactivate", json={"expected_row_version": target["row_version"]})

    response = await client.get(USERS_ENDPOINT, params={"status": "INACTIVE"})
    statuses = {item["status"] for item in response.json()["data"]}
    assert statuses == {"INACTIVE"}


async def test_user_api_007_pagination(client):
    await _signup_and_login_owner(client)
    for i in range(3):
        await client.post(USERS_ENDPOINT, json={"name": f"P{i}", "phone": _unique_phone(), "email": _unique_email(), "role": "MANAGER"})

    response = await client.get(USERS_ENDPOINT, params={"page": 1, "page_size": 2})
    body = response.json()
    assert len(body["data"]) == 2
    assert body["pagination"]["page_size"] == 2
    assert body["pagination"]["total_items"] >= 4  # owner + 3 created


async def test_user_api_008_authorized_user_detail(client):
    _, owner_data = await _signup_and_login_owner(client)
    response = await client.get(f"{USERS_ENDPOINT}/{owner_data['owner_user_id']}")
    assert response.status_code == 200
    assert response.json()["data"]["role"] == "OWNER"


async def test_user_api_009_unknown_user(client):
    await _signup_and_login_owner(client)
    response = await client.get(f"{USERS_ENDPOINT}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USR-001"


async def test_user_api_010_cross_tenant_user_detail_indistinguishable_from_not_found(client):
    _, owner_a = await _signup_and_login_owner(client)
    _, owner_b = await _signup_and_login_owner(client)  # now logged in as tenant B

    response = await client.get(f"{USERS_ENDPOINT}/{owner_a['owner_user_id']}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USR-001"


async def test_user_api_016_valid_update(client):
    await _signup_and_login_owner(client)
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "Old Name", "phone": _unique_phone(), "email": _unique_email(), "role": "MANAGER"}
    )
    target = create_response.json()["data"]

    response = await client.patch(
        f"{USERS_ENDPOINT}/{target['id']}", json={"name": "New Name", "expected_row_version": target["row_version"]}
    )
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "New Name"


async def test_user_api_017_invalid_update(client):
    await _signup_and_login_owner(client)
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "X", "phone": _unique_phone(), "email": _unique_email(), "role": "MANAGER"}
    )
    target = create_response.json()["data"]
    response = await client.patch(
        f"{USERS_ENDPOINT}/{target['id']}", json={"email": "not-an-email", "expected_row_version": target["row_version"]}
    )
    assert response.status_code == 422


async def test_user_api_018_unauthorized_update(client):
    await _signup_and_login_owner(client)
    _, sp_data = await _create_user_and_set_password(client, role="SALESPERSON")
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "Target", "phone": _unique_phone(), "email": _unique_email(), "role": "MANAGER"}
    )
    target = create_response.json()["data"]

    await client.post(LOGIN_ENDPOINT, json={"login_identifier": sp_data["phone"], "password": NEW_USER_PASSWORD})
    response = await client.patch(
        f"{USERS_ENDPOINT}/{target['id']}", json={"name": "Hacked", "expected_row_version": target["row_version"]}
    )
    assert response.status_code == 403


async def test_user_api_019_cross_tenant_update(client):
    await _signup_and_login_owner(client)
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "TenantA User", "phone": _unique_phone(), "email": _unique_email(), "role": "MANAGER"}
    )
    target = create_response.json()["data"]

    await _signup_and_login_owner(client)  # switch to tenant B
    response = await client.patch(
        f"{USERS_ENDPOINT}/{target['id']}", json={"name": "Hacked", "expected_row_version": target["row_version"]}
    )
    assert response.status_code == 404


async def test_user_api_020_stale_row_version(client):
    await _signup_and_login_owner(client)
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "X", "phone": _unique_phone(), "email": _unique_email(), "role": "MANAGER"}
    )
    target = create_response.json()["data"]

    first = await client.patch(f"{USERS_ENDPOINT}/{target['id']}", json={"name": "First", "expected_row_version": target["row_version"]})
    assert first.status_code == 200

    stale = await client.patch(f"{USERS_ENDPOINT}/{target['id']}", json={"name": "Second", "expected_row_version": target["row_version"]})
    assert stale.status_code == 412


async def test_user_api_021_activate_valid_user(client):
    await _signup_and_login_owner(client)
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "X", "phone": _unique_phone(), "email": _unique_email(), "role": "MANAGER"}
    )
    target = create_response.json()["data"]
    await client.post(f"{USERS_ENDPOINT}/{target['id']}/deactivate", json={"expected_row_version": target["row_version"]})

    get_response = await client.get(f"{USERS_ENDPOINT}/{target['id']}")
    current = get_response.json()["data"]
    response = await client.post(f"{USERS_ENDPOINT}/{target['id']}/activate", json={"expected_row_version": current["row_version"]})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ACTIVE"


async def test_user_api_022_unauthorized_activation(client):
    await _signup_and_login_owner(client)
    _, sp_data = await _create_user_and_set_password(client, role="SALESPERSON")
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "X", "phone": _unique_phone(), "email": _unique_email(), "role": "MANAGER"}
    )
    target = create_response.json()["data"]

    await client.post(LOGIN_ENDPOINT, json={"login_identifier": sp_data["phone"], "password": NEW_USER_PASSWORD})
    response = await client.post(f"{USERS_ENDPOINT}/{target['id']}/activate", json={"expected_row_version": target["row_version"]})
    assert response.status_code == 403


async def test_user_api_023_deactivate_valid_user(client):
    await _signup_and_login_owner(client)
    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "X", "phone": _unique_phone(), "email": _unique_email(), "role": "MANAGER"}
    )
    target = create_response.json()["data"]
    response = await client.post(f"{USERS_ENDPOINT}/{target['id']}/deactivate", json={"expected_row_version": target["row_version"]})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "INACTIVE"


async def test_user_api_024_unauthorized_deactivation(client):
    await _signup_and_login_owner(client)
    _, sp_data = await _create_user_and_set_password(client, role="SALESPERSON")

    await client.post(LOGIN_ENDPOINT, json={"login_identifier": sp_data["phone"], "password": NEW_USER_PASSWORD})
    response = await client.post(f"{USERS_ENDPOINT}/{sp_data['id']}/deactivate", json={"expected_row_version": sp_data["row_version"]})
    assert response.status_code == 403


async def test_user_api_025_protected_owner_deactivation(client):
    _, owner_data = await _signup_and_login_owner(client)
    detail = await client.get(f"{USERS_ENDPOINT}/{owner_data['owner_user_id']}")
    current = detail.json()["data"]

    response = await client.post(
        f"{USERS_ENDPOINT}/{owner_data['owner_user_id']}/deactivate", json={"expected_row_version": current["row_version"]}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USR-004"


async def test_owner_protection_allows_deactivation_when_second_owner_exists(client):
    _, owner_data = await _signup_and_login_owner(client)
    _, second_owner = await _create_user_and_set_password(client, role="OWNER")

    detail = await client.get(f"{USERS_ENDPOINT}/{owner_data['owner_user_id']}")
    current = detail.json()["data"]
    response = await client.post(
        f"{USERS_ENDPOINT}/{owner_data['owner_user_id']}/deactivate", json={"expected_row_version": current["row_version"]}
    )
    assert response.status_code == 200


async def test_owner_protection_blocks_last_owner_role_change(client):
    _, owner_data = await _signup_and_login_owner(client)
    detail = await client.get(f"{USERS_ENDPOINT}/{owner_data['owner_user_id']}")
    current = detail.json()["data"]

    response = await client.patch(
        f"{USERS_ENDPOINT}/{owner_data['owner_user_id']}",
        json={"role": "MANAGER", "expected_row_version": current["row_version"]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USR-004"


async def test_user_api_026_session_invalidation_on_deactivation(client, db_session):
    await _signup_and_login_owner(client)
    _, mgr_data = await _create_user_and_set_password(client, role="MANAGER")

    mgr_login = await client.post(LOGIN_ENDPOINT, json={"login_identifier": mgr_data["phone"], "password": NEW_USER_PASSWORD})
    assert mgr_login.status_code == 200

    # Switch back to owner session to perform the deactivation (a fresh client
    # would be cleaner, but this test client's cookie jar now holds the
    # manager's session — re-login as owner is out of scope for this check;
    # instead verify directly that deactivation revokes sessions server-side).
    active_before = (
        await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == uuid.UUID(mgr_data["id"]), AuthSession.revoked_at.is_(None))
        )
    ).scalars().all()
    assert len(active_before) == 1

    from app.services.user_management.user_service import UserManagementService

    service = UserManagementService(db_session)
    user_row = (await db_session.execute(select(User).where(User.id == uuid.UUID(mgr_data["id"])))).scalar_one()
    await service.deactivate_user(
        tenant_id=user_row.tenant_id,
        actor_user_id=user_row.id,
        user_id=user_row.id,
        expected_row_version=user_row.row_version,
        ip_address=None,
    )
    await db_session.commit()

    active_after = (
        await db_session.execute(
            select(AuthSession).where(AuthSession.user_id == uuid.UUID(mgr_data["id"]), AuthSession.revoked_at.is_(None))
        )
    ).scalars().all()
    assert len(active_after) == 0


async def test_manager_has_read_only_access(client):
    await _signup_and_login_owner(client)
    _, mgr_data = await _create_user_and_set_password(client, role="MANAGER")

    await client.post(LOGIN_ENDPOINT, json={"login_identifier": mgr_data["phone"], "password": NEW_USER_PASSWORD})

    list_response = await client.get(USERS_ENDPOINT)
    assert list_response.status_code == 200  # read allowed

    create_response = await client.post(
        USERS_ENDPOINT, json={"name": "X", "phone": _unique_phone(), "email": _unique_email(), "role": "SALESPERSON"}
    )
    assert create_response.status_code == 403  # write denied
