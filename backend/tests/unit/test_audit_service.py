"""Item 11 (PROMPT-001 S18): audit mechanism can record an event."""

import uuid

from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.tenant import Tenant
from app.services.audit.audit_service import AuditService


async def test_audit_service_records_event(db_session):
    # audit_log.tenant_id is a real FK, so a tenant row must exist first.
    tenant = Tenant(business_name="Test Tenant For Audit")
    db_session.add(tenant)
    await db_session.flush()

    service = AuditService(db_session)

    entry = await service.record(
        tenant_id=tenant.id,
        actor_user_id=None,  # no real user FK exists yet in this isolated test
        action="CREATE",
        entity_type="test_entity",
        entity_id=uuid.uuid4(),
        after={"name": "example"},
    )

    assert entry.id is not None
    assert entry.action == "CREATE"
    assert entry.entity_type == "test_entity"
    assert entry.after_json == {"name": "example"}
    assert entry.correlation_id is not None

    result = await db_session.execute(select(AuditLog).where(AuditLog.id == entry.id))
    stored = result.scalar_one()
    assert stored.action == "CREATE"
