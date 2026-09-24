"""Server-controlled tenant context propagation into PostgreSQL Row-Level Security.

Tenant context is resolved from the authenticated session only (never from a client
request body or query string). Setting the Postgres session variable here is the
second line of defense behind application-level tenant filtering (ERD v2.0 S4).

Whether RLS is force-enabled in production remains an open architectural decision
(ERD-DEC-01 / API-OD-07 in the approved baseline) — this module prepares the
mechanism without silently closing that decision.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID | None) -> None:
    """Set the Postgres session-local GUC that RLS policies key off.

    Uses set_config(..., is_local=True) so the value is scoped to the current
    transaction and cannot leak across pooled connections/requests.
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id) if tenant_id else ""},
    )


async def clear_tenant_context(session: AsyncSession) -> None:
    await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
