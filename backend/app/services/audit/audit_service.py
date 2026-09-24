"""Reusable audit-write service (PROMPT-001 S10).

Future business operations call AuditService.record(...) rather than writing to
audit_log directly. Records are append-only: the database revokes UPDATE/DELETE
on audit_log for the application role (see migrations), so this service has no
update/delete methods by design.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.db.base import utcnow
from app.models.audit_log import AuditLog


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        ip_address: str | None = None,
        device_info: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=before,
            after_json=after,
            occurred_at=utcnow(),
            ip_address=ip_address,
            device_info=device_info,
            correlation_id=get_correlation_id(),
        )
        self._session.add(entry)
        await self._session.flush()
        return entry
