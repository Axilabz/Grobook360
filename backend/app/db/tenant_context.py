"""Server-controlled tenant context propagation into PostgreSQL Row-Level Security.

Tenant context is resolved from the authenticated session only (never from a client
request body or query string). Since migration 0038 the database ENFORCES it:
the runtime role (grobook_app) is not a table owner, RLS is FORCEd, and every
policy keys off the `app.tenant_id` setting. No tenant context => zero rows.

Pool safety: the value is set with set_config(..., is_local=True), i.e. scoped to
the current TRANSACTION, so it cannot leak to another request that later reuses
the pooled connection. Because a session may run several transactions (an
explicit commit mid-request starts a new one), the chosen tenant is remembered on
`session.info` and re-applied automatically at the start of each new transaction
(`after_begin` below) - it is never carried on the connection itself.
"""

import uuid

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_INFO_KEY = "tenant_id"
_SET_SQL = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(session: Session, transaction, connection) -> None:
    tenant_id = session.info.get(_INFO_KEY)
    if tenant_id:
        connection.execute(_SET_SQL, {"tenant_id": tenant_id})


async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID | None) -> None:
    """Set the Postgres setting that RLS policies key off, for this and later
    transactions of `session`. `None` clears it (fail closed: no rows visible)."""
    value = str(tenant_id) if tenant_id else ""
    session.sync_session.info[_INFO_KEY] = value
    await session.execute(_SET_SQL, {"tenant_id": value})


async def clear_tenant_context(session: AsyncSession) -> None:
    await set_tenant_context(session, None)
