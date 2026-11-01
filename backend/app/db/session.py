from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()

_connect_args: dict = {}
if settings.database_ssl:
    _connect_args["ssl"] = "require"
if settings.database_use_pgbouncer:
    # PgBouncer (transaction mode) can't hold server-side prepared statements.
    _connect_args["statement_cache_size"] = 0
    _connect_args["prepared_statement_cache_size"] = 0

if settings.environment == "testing":
    # NullPool: every checkout is a fresh connection, closed on checkin. Required
    # under pytest-asyncio's per-test event loops (asyncpg connections cannot be
    # reused across event loops, which a pooled connection otherwise would be).
    engine = create_async_engine(str(settings.database_url), echo=settings.database_echo, poolclass=NullPool, connect_args=_connect_args)
else:
    engine = create_async_engine(
        str(settings.database_url),
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        # No pre_ping: it costs one extra network round trip per checkout.
        # pool_recycle retires connections before the pooler can drop them.
        pool_recycle=240,
        connect_args=_connect_args,
    )

AsyncSessionLocal = async_sessionmaker(
    bind=engine, expire_on_commit=False, autoflush=False
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped async DB session."""
    async with AsyncSessionLocal() as session:
        yield session
