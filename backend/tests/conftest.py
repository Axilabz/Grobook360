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

from app.db.session import AsyncSessionLocal
from app.main import app


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from app.core.rate_limit import reset_rate_limits

    reset_rate_limits()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def new_uuid() -> uuid.UUID:
    return uuid.uuid4()
