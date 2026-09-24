"""Integration operation log service (PROMPT-018 §29).

Every GENERATE/CANCEL/STATUS_CHECK attempt against an `einvoice`/
`eway_bill` row is recorded here — the operational history §29 requires,
and the trail `EInvoiceService`/`EWayBillService` reconcile against
(§24/§39) when a prior attempt's outcome is `STATUS_UNKNOWN`.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.exceptions import NotFoundError
from app.models.integration_operation import IN_PROGRESS, IntegrationOperation


class IntegrationOperationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        operation_type: str,
        idempotency_key: str | None,
        provider: str,
    ) -> IntegrationOperation:
        operation = IntegrationOperation(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            operation_type=operation_type,
            idempotency_key=idempotency_key,
            status=IN_PROGRESS,
            attempt_count=1,
            provider=provider,
            correlation_id=get_correlation_id(),
            requested_at=datetime.now(timezone.utc),
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(operation)
        await self._session.flush()
        return operation

    async def mark_result(
        self,
        *,
        operation: IntegrationOperation,
        status: str,
        provider_reference: str | None,
        response_code: str | None,
        error_code: str | None,
        error_message: str | None,
    ) -> IntegrationOperation:
        operation.status = status
        operation.provider_reference = provider_reference
        operation.response_code = response_code
        operation.error_code = error_code
        operation.error_message = error_message
        operation.responded_at = datetime.now(timezone.utc)
        await self._session.flush()
        return operation

    async def get(self, *, tenant_id: uuid.UUID, operation_id: uuid.UUID) -> IntegrationOperation:
        result = await self._session.execute(
            select(IntegrationOperation).where(
                IntegrationOperation.id == operation_id, IntegrationOperation.tenant_id == tenant_id
            )
        )
        operation = result.scalar_one_or_none()
        if operation is None:
            raise NotFoundError("Integration operation not found")
        return operation

    async def list_for_entity(
        self, *, tenant_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID
    ) -> list[IntegrationOperation]:
        result = await self._session.execute(
            select(IntegrationOperation)
            .where(
                IntegrationOperation.tenant_id == tenant_id,
                IntegrationOperation.entity_type == entity_type,
                IntegrationOperation.entity_id == entity_id,
            )
            .order_by(IntegrationOperation.created_at.desc())
        )
        return list(result.scalars().all())
