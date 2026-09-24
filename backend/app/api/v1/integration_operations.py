"""Integration operation log endpoint (PROMPT-018 §27/§29).

Read-only operational visibility into a single GENERATE/CANCEL/
STATUS_CHECK attempt — for support/debugging (§29/§36), not a business
action in itself. Viewing an operation requires EITHER `einvoice.view`
OR `eway_bill.view` (checked directly, since one endpoint serves both
entity types) and is tenant-scoped like every other lookup.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, get_current_user
from app.core.exceptions import AuthorizationError
from app.core.permissions import EINVOICE_VIEW, EWAY_BILL_VIEW
from app.db.session import get_db_session
from app.models.integration_operation import IntegrationOperation
from app.schemas.gst_integration import IntegrationOperationDetail
from app.services.gst_integration.integration_operation_service import IntegrationOperationService

router = APIRouter(prefix="/integration/operations", tags=["integration-operations"])


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


def _to_detail(operation: IntegrationOperation) -> IntegrationOperationDetail:
    return IntegrationOperationDetail(
        id=str(operation.id),
        entity_type=operation.entity_type,
        entity_id=str(operation.entity_id),
        operation_type=operation.operation_type,
        status=operation.status,
        attempt_count=operation.attempt_count,
        provider=operation.provider,
        provider_reference=operation.provider_reference,
        response_code=operation.response_code,
        error_code=operation.error_code,
        error_message=operation.error_message,
        correlation_id=str(operation.correlation_id) if operation.correlation_id else None,
        requested_at=operation.requested_at.isoformat() if operation.requested_at else None,
        responded_at=operation.responded_at.isoformat() if operation.responded_at else None,
        created_at=operation.created_at.isoformat(),
    )


@router.get("/{operation_id}")
async def get_operation(
    operation_id: uuid.UUID,
    context: AuthenticatedContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    if EINVOICE_VIEW not in context.permissions and EWAY_BILL_VIEW not in context.permissions:
        raise AuthorizationError(f"Missing required permission: {EINVOICE_VIEW} or {EWAY_BILL_VIEW}")
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")

    service = IntegrationOperationService(session)
    operation = await service.get(tenant_id=context.tenant_id, operation_id=operation_id)
    return {"data": _to_detail(operation).model_dump(), "meta": _meta()}
