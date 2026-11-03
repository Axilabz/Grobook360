import asyncio
import os
import sys
import uuid
from collections.abc import AsyncGenerator

if sys.platform == "win32":
    # asyncpg does not fully support Windows' default ProactorEventLoop
    # (connection cancellation/teardown breaks under it); Selector is required.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Must be set before the first app.core.config.get_settings() call anywhere in the
# process, so app.db.session picks NullPool (safe under per-test event loops).
os.environ.setdefault("ENVIRONMENT", "testing")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text

from app.db.session import engine
from app.db.tenant_context import set_tenant_context
from app.main import app

# --- Phase 1C: tests run as the restricted runtime role, so row-level security
# is real for them too. A test that inspects the database directly must say
# WHOSE rows it is looking at. For the common case - "verify what the API call
# I just made did to the tenant under test" - the harness follows the tenant
# the HTTP client most recently signed up / logged in as. Tests about a
# different tenant (or none) call set_tenant_context(db_session, ...) explicitly.
_current_tenant: dict[str, uuid.UUID | None] = {"id": None}


@pytest.fixture(autouse=True)
def _reset_tenant_under_test():
    _current_tenant["id"] = None
    yield
    _current_tenant["id"] = None


async def _track_tenant(response) -> None:
    try:
        await response.aread()
        body = response.json()
    except Exception:  # noqa: BLE001 - non-JSON responses carry no tenant
        return
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return
    tenant = data.get("tenant")
    raw = data.get("tenant_id") or (tenant.get("id") if isinstance(tenant, dict) else None)
    if raw:
        try:
            _current_tenant["id"] = uuid.UUID(str(raw))
        except ValueError:
            pass


class TenantAwareTestSession(AsyncSession):
    """AsyncSession that applies the tenant under test before each statement."""

    async def _follow_tenant(self) -> None:
        tid = _current_tenant["id"]
        if tid is None or self.info.get("test_followed") == (tid, id(self.sync_session.get_transaction())):
            return
        explicit = self.info.get("tenant_id")
        if explicit and explicit != self.info.get("test_follow_value"):
            return  # the test chose a tenant itself (set_tenant_context): never override it
        self.info["test_follow_value"] = str(tid)
        # Mark first: set_tenant_context() itself calls self.execute().
        self.info["test_followed"] = (tid, id(self.sync_session.get_transaction()))
        await set_tenant_context(self, tid)  # also remembered for later transactions

    def add(self, instance, *args, **kwargs):
        # Creating a Tenant directly (unit-style fixtures): the session then works
        # as that tenant, exactly as it would after signing it up via the API.
        from app.models.tenant import Tenant

        if isinstance(instance, Tenant):
            if instance.id is None:
                instance.id = uuid.uuid4()
            _current_tenant["id"] = instance.id
        elif getattr(instance, "tenant_id", None):
            _current_tenant["id"] = instance.tenant_id  # a row for tenant X: act as tenant X
        return super().add(instance, *args, **kwargs)

    async def execute(self, *args, **kwargs):
        await self._follow_tenant()
        return await super().execute(*args, **kwargs)

    def add_all(self, instances, *args, **kwargs):
        instances = list(instances)
        for instance in instances:
            self.add(instance)
        return None

    async def flush(self, *args, **kwargs):
        await self._follow_tenant()
        return await super().flush(*args, **kwargs)

    async def commit(self):
        await self._follow_tenant()  # commit flushes internally, bypassing flush() above
        return await super().commit()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TenantAwareTestSession(bind=engine, expire_on_commit=False, autoflush=False) as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from app.core.rate_limit import reset_rate_limits

    reset_rate_limits()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", event_hooks={"response": [_track_tenant]}) as ac:
        yield ac


@pytest.fixture
def new_uuid() -> uuid.UUID:
    return uuid.uuid4()
