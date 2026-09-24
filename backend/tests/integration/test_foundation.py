"""Foundation tests required by PROMPT-001 S18 (items 1-10, 12).

Item 11 (audit mechanism can record an event) lives in
tests/unit/test_audit_service.py since it doesn't need the HTTP layer.
"""

import uuid

import pytest
from sqlalchemy import select, text


async def test_app_starts_and_health_ok(client):
    # Item 1: application starts successfully.
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


async def test_database_connection_works(client):
    # Item 2: database connection works.
    response = await client.get("/api/v1/health/db")
    assert response.status_code == 200
    assert response.json()["data"]["database"] == "connected"


async def test_migration_mechanism_created_foundation_tables(db_session):
    # Item 3: migration mechanism works (tables from migration 0001 exist).
    result = await db_session.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name IN "
            "('tenant','user','role','permission','user_role','role_permission','audit_log')"
        )
    )
    tables = {row[0] for row in result.fetchall()}
    assert tables == {
        "tenant", "user", "role", "permission", "user_role", "role_permission", "audit_log",
    }


async def test_api_version_route_works(client):
    # Item 4: API version route works.
    response = await client.get("/api/v1/version")
    assert response.status_code == 200
    assert response.json()["data"]["api_version"] == "v1"


async def test_standard_success_response_format(client):
    # Item 5: standard response format works.
    body = (await client.get("/api/v1/health")).json()
    assert set(body.keys()) == {"data", "meta"}
    assert "correlation_id" in body["meta"]
    uuid.UUID(body["meta"]["correlation_id"])  # must be a valid UUID


async def test_standard_error_response_format(client):
    # Item 6: standard error format works (unknown route -> 404 envelope).
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert "correlation_id" in body["meta"]


async def test_correlation_id_echoed_when_supplied(client):
    # Item 7: correlation ID works — supplied value is echoed back.
    supplied = str(uuid.uuid4())
    response = await client.get("/api/v1/health", headers={"X-Correlation-Id": supplied})
    assert response.headers["X-Correlation-Id"] == supplied
    assert response.json()["meta"]["correlation_id"] == supplied


async def test_correlation_id_generated_when_absent(client):
    response = await client.get("/api/v1/health")
    generated = response.headers["X-Correlation-Id"]
    uuid.UUID(generated)  # must be a valid generated UUID


def test_configuration_loads_correctly():
    # Item 8: configuration loads correctly.
    from app.core.config import get_settings

    settings = get_settings()
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.jwt_secret_key  # required, must not be empty


async def test_unauthorized_access_is_rejected(client):
    # Item 9: unauthorized access is rejected where applicable.
    # /auth/me (PROMPT-003) is a real protected route that depends on
    # get_current_user: no cookie/Authorization header must fail closed (401).
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_audit_log_update_rejected_at_db_level(db_session):
    # audit_log must be append-only (Table Register IMMUTABLE/APPEND-ONLY=YES).
    # Migration 0001's REVOKE UPDATE, DELETE ... FROM PUBLIC does not actually
    # enforce this since the app's DB role owns the table; migration 0012 adds
    # a BEFORE UPDATE/DELETE trigger that does (mirrors
    # test_inventory_api_037_ledger_update_rejected_at_db_level's pattern for
    # stock_ledger_entry).
    from app.db.session import AsyncSessionLocal
    from app.models.audit_log import AuditLog
    from app.models.tenant import Tenant
    from app.services.audit.audit_service import AuditService
    from sqlalchemy.exc import DBAPIError

    tenant = Tenant(business_name="Test Tenant For Audit Immutability")
    db_session.add(tenant)
    await db_session.flush()

    service = AuditService(db_session)
    entry = await service.record(
        tenant_id=tenant.id,
        actor_user_id=None,
        action="CREATE",
        entity_type="test_entity",
        entity_id=uuid.uuid4(),
        after={"name": "example"},
    )
    await db_session.commit()

    entry_id = entry.id  # captured before rollback: an async ORM attribute
    # access after rollback would trigger an implicit expired-attribute
    # refresh, which SQLAlchemy's async extension cannot do outside an
    # awaited context (raises MissingGreenlet).

    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("UPDATE audit_log SET action = 'TAMPERED' WHERE id = :id"), {"id": entry_id}
        )
        await db_session.commit()
    await db_session.rollback()

    async with AsyncSessionLocal() as verify_session:
        result = await verify_session.execute(select(AuditLog).where(AuditLog.id == entry_id))
        assert result.scalar_one().action == "CREATE"


async def test_tenant_context_infrastructure_is_available(db_session):
    # Item 10: tenant context infrastructure is available.
    from app.db.tenant_context import clear_tenant_context, set_tenant_context

    tenant_id = uuid.uuid4()
    await set_tenant_context(db_session, tenant_id)
    result = await db_session.execute(text("SELECT current_setting('app.tenant_id', true)"))
    assert result.scalar() == str(tenant_id)

    await clear_tenant_context(db_session)
    result = await db_session.execute(text("SELECT current_setting('app.tenant_id', true)"))
    assert result.scalar() == ""
