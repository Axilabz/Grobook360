"""Export orchestration service (Global Table/Grid Export Framework).

Architecture (mirrors the source prompt's own §2 diagram exactly):

    Resource registry lookup (allowlist, §17)
        -> Permission check (caller-supplied at the router layer via
           require_permission(resource.export_permission) — the SAME
           dependency-injection pattern every other endpoint in this
           codebase uses, never a bespoke check)
        -> tenant_id resolved from AuthenticatedContext, NEVER from the
           request body (§14 — the exact rule every service in this
           codebase already follows)
        -> resource adapter's own EXISTING list query, reusing that
           module's own search/filter/tenant-scoping verbatim (record-
           level authorization is therefore inherited for free: the
           grid and the export run the identical query, so a user can
           never export a row they couldn't already see on screen —
           §15)
        -> row cap enforced as the SQL page_size itself (never fetch-
           then-truncate)
        -> Excel/PDF generator (pure, no DB access, no business logic)
        -> audit (AuditService — EXPORT_COMPLETED/EXPORT_FAILED)
        -> bytes returned directly to the router for a synchronous
           StreamingResponse download.

Synchronous only for M1 — no background-job/queue infrastructure exists
anywhere in this codebase (the same confirmed absence PROMPT-018 §43,
PROMPT-028 §51, and this session's own PROMPT-034-SPECIFICATION.md §21
each independently reached). A dedicated `export_job` table with fake
QUEUED/PROCESSING states that never actually occur would misrepresent a
capability that isn't real — this framework's own row cap (below) keeps
every export within what a single HTTP request can comfortably return,
which is the same resolution PROMPT-034 already reached for CSV export.
If genuine background-job infrastructure is ever added, THIS is the
single place that would grow an async path — the resource registry,
generators and column allowlists would not need to change at all.

Audit uses the EXISTING `AuditService`/`audit_log` directly (no new
`export_job` table) — an export is exactly the kind of "privileged bulk
data access" action that codebase's own audit conventions already
treat as compliance-grade (see PROMPT-031-SPECIFICATION.md's own
identical reasoning for `EXPORT_COMPLETED`/`EXPORT_FAILED`).
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import (
    EXPORT_INVALID_FORMAT,
    EXPORT_INVALID_RESOURCE,
    EXPORT_INVALID_SCOPE,
    EXPORT_TOO_LARGE,
)
from app.core.exceptions import ValidationAppError
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit.audit_service import AuditService
from app.services.export.excel_generator import generate_excel
from app.services.export.pdf_generator import generate_pdf
from app.services.export.resources import ExportFilters, get_resource
from sqlalchemy import select

# §26 of the source prompt: "do not generate a misleading report" — an
# empty result set still produces a real, correctly-headered file (with
# a "No records found" line), never a silently-wrong one.
CURRENT_PAGE = "CURRENT_PAGE"
ALL_FILTERED = "ALL_FILTERED"
VALID_SCOPES = frozenset({CURRENT_PAGE, ALL_FILTERED})
VALID_FORMATS = frozenset({"xlsx", "pdf"})

# Synchronous row cap (§20/§26 of the source prompt's own "configurable
# threshold" instruction) — a single HTTP request generating either file
# format for this many rows completes well within normal request
# timeouts at this MVP's realistic per-tenant data volumes (the same
# reasoning PROMPT-034-SPECIFICATION.md §21 already used for CSV).
MAX_EXPORT_ROWS = 10_000


@dataclass(frozen=True)
class ExportResult:
    content: bytes
    filename: str
    content_type: str
    row_count: int


async def run_export(
    *,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    resource_key: str,
    export_format: str,
    scope: str,
    search: str | None,
    status_filter: str | None,
    date_from: date | None,
    date_to: date | None,
    party_id: uuid.UUID | None,
    current_page: int,
    current_page_size: int,
    ip_address: str | None,
) -> ExportResult:
    resource = get_resource(resource_key)
    if resource is None:
        raise ValidationAppError("Unknown export resource.", code=EXPORT_INVALID_RESOURCE)
    if export_format not in VALID_FORMATS:
        raise ValidationAppError("Export format must be 'xlsx' or 'pdf'.", code=EXPORT_INVALID_FORMAT)
    if scope not in VALID_SCOPES:
        raise ValidationAppError("Export scope must be 'CURRENT_PAGE' or 'ALL_FILTERED'.", code=EXPORT_INVALID_SCOPE)

    filters = ExportFilters(search=search, status=status_filter, date_from=date_from, date_to=date_to, party_id=party_id)

    if scope == CURRENT_PAGE:
        page, page_size = max(current_page, 1), min(max(current_page_size, 1), 100)
    else:
        page, page_size = 1, MAX_EXPORT_ROWS

    # Deliberately NOT wrapped in a broad try/except: if the underlying
    # fetch raises an unexpected error, the session's transaction is left
    # aborted (Postgres rejects further commands until rollback) — trying
    # to ALSO write a FAILURE audit row here would itself fail against
    # that same aborted transaction. Let it propagate to the app's
    # existing generic exception handler instead, which already logs
    # full detail server-side (PROMPT-032 §26) — audit only wraps the
    # CONTROLLED failure paths below, where the session is still healthy.
    rows, total_items = await resource.fetch(session, tenant_id, filters, page_size, page)

    if scope == ALL_FILTERED and total_items > MAX_EXPORT_ROWS:
        await _audit(session, tenant_id, actor_user_id, resource_key, export_format, scope, total_items, "FAILURE", ip_address)
        await session.commit()
        raise ValidationAppError(
            f"{total_items} records match your filters, which exceeds the {MAX_EXPORT_ROWS}-row export limit. "
            "Please narrow your filters (e.g. a shorter date range) and try again.",
            code=EXPORT_TOO_LARGE,
        )

    tenant = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    actor = (await session.execute(select(User).where(User.id == actor_user_id))).scalar_one_or_none()
    tenant_name = tenant.business_name if tenant else "—"
    generated_by = (actor.name or actor.email) if actor else "—"
    generated_at = datetime.now(timezone.utc)

    applied_filters = {
        "Search": search, "Status": status_filter,
        "Date From": date_from.isoformat() if date_from else None,
        "Date To": date_to.isoformat() if date_to else None,
        "Scope": "All Filtered Records" if scope == ALL_FILTERED else "Current Page",
    }

    if export_format == "xlsx":
        content = generate_excel(
            title=resource.title, tenant_name=tenant_name, generated_by=generated_by, generated_at=generated_at,
            applied_filters=applied_filters, columns=resource.columns, rows=rows,
        )
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        extension = "xlsx"
    else:
        content = generate_pdf(
            title=resource.title, tenant_name=tenant_name, generated_by=generated_by, generated_at=generated_at,
            applied_filters=applied_filters, columns=resource.columns, rows=rows,
        )
        content_type = "application/pdf"
        extension = "pdf"

    await _audit(session, tenant_id, actor_user_id, resource_key, export_format, scope, len(rows), "SUCCESS", ip_address)
    await session.commit()

    filename = f"{resource_key}-{generated_at.strftime('%Y%m%d-%H%M%S')}.{extension}"
    return ExportResult(content=content, filename=filename, content_type=content_type, row_count=len(rows))


async def _audit(
    session: AsyncSession, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, resource_key: str,
    export_format: str, scope: str, row_count: int, result: str, ip_address: str | None,
) -> None:
    await AuditService(session).record(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="EXPORT_COMPLETED" if result == "SUCCESS" else "EXPORT_FAILED",
        entity_type="export",
        entity_id=None,
        after={"resource": resource_key, "format": export_format, "scope": scope, "row_count": row_count, "result": result},
        ip_address=ip_address,
    )
