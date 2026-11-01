"""Run independent read-only report "lanes" concurrently, each on its OWN DB
session/connection.

Why: one AsyncSession runs one statement at a time, so a dashboard that issues
30+ independent aggregate queries pays 30+ sequential network round trips to a
hosted database (~190 ms each). Splitting them into a few lanes that run in
parallel divides that wait by roughly the lane count.

Safety: read-only only. Each lane re-applies the tenant context so RLS still
applies on its own connection. Off by default (`report_parallel_lanes = 0`) —
then every lane simply runs sequentially on the caller's session, exactly as
before (this is what the test suite exercises).
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.db.tenant_context import set_tenant_context

Lane = Callable[[AsyncSession], Awaitable[Any]]


async def run_lanes(session: AsyncSession, tenant_id: uuid.UUID, lanes: list[Lane]) -> list[Any]:
    if get_settings().report_parallel_lanes <= 0 or len(lanes) < 2:
        return [await lane(session) for lane in lanes]

    async def _run(lane: Lane) -> Any:
        async with AsyncSessionLocal() as lane_session:
            await set_tenant_context(lane_session, tenant_id)
            try:
                return await lane(lane_session)
            finally:
                await lane_session.rollback()  # read-only: never leave a txn open

    return list(await asyncio.gather(*[_run(lane) for lane in lanes]))
