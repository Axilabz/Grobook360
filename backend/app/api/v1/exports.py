"""Global Table/Grid Export API (cross-cutting Export Framework prompt).

One centralized endpoint for every applicable table/grid's Excel/PDF
export, rather than a bespoke export endpoint duplicated per module —
`resource` is an allowlisted identifier (app/services/export/resources.py),
never a client-supplied table/query. Authorization is a DYNAMIC,
per-request permission check (mirrors `credit_debit_notes.py`'s own
established `_require_note_permission` pattern, PROMPT-017) since the
required permission code depends on which resource was requested — a
single static `Depends(require_permission(...))` can't express that.
"""

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthenticatedContext, get_current_user
from app.core.error_codes import EXPORT_INVALID_RESOURCE, EXPORT_UNAUTHORIZED
from app.core.exceptions import AuthorizationError, ValidationAppError
from app.db.session import get_db_session
from app.schemas.export import ExportRequest
from app.services.export.export_service import run_export
from app.services.export.resources import get_resource

router = APIRouter(prefix="/exports", tags=["exports"])


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


@router.post("")
async def create_export(
    request: Request,
    payload: ExportRequest,
    context: AuthenticatedContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"

    resource = get_resource(payload.resource)
    if resource is None:
        raise ValidationAppError("Unknown export resource.", code=EXPORT_INVALID_RESOURCE)

    # Dynamic permission check — the resource named in the REQUEST BODY
    # decides which permission is required, so this cannot be expressed
    # as a static require_permission(...) route dependency. §13 of the
    # source prompt: hiding the export button is NOT sufficient — the
    # backend must independently reject an unauthorized call here.
    if resource.export_permission not in context.permissions:
        raise AuthorizationError(
            f"Missing required permission: {resource.export_permission}", code=EXPORT_UNAUTHORIZED
        )

    result = await run_export(
        session=session,
        tenant_id=tenant_id,
        actor_user_id=context.user_id,
        resource_key=payload.resource,
        export_format=payload.format,
        scope=payload.scope,
        search=payload.search,
        status_filter=payload.status,
        date_from=payload.date_from,
        date_to=payload.date_to,
        party_id=uuid.UUID(payload.party_id) if payload.party_id else None,
        current_page=payload.page,
        current_page_size=payload.page_size,
        ip_address=client_ip,
    )

    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )
