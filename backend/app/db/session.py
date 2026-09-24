from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()

if settings.environment == "testing":
    # NullPool: every checkout is a fresh connection, closed on checkin. Required
    # under pytest-asyncio's per-test event loops (asyncpg connections cannot be
    # reused across event loops, which a pooled connection otherwise would be).
    engine = create_async_engine(str(settings.database_url), echo=settings.database_echo, poolclass=NullPool)
else:
    engine = create_async_engine(
        str(settings.database_url),
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
    )

AsyncSessionLocal = async_sessionmaker(
    bind=engine, expire_on_commit=False, autoflush=False
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped async DB session."""
    async with AsyncSessionLocal() as session:
        yield session
