from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers
from app.logging.config import configure_logging
from app.middleware.correlation_id import CorrelationIdMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.project_name,
        version="1.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    @app.on_event("startup")
    async def _warm_db_pool() -> None:
        # Open a few connections up front: with a remote DB each fresh
        # connection costs 1-5s (TLS + pooler auth), which the first user
        # requests would otherwise pay. Best-effort — never blocks startup.
        if settings.environment == "testing":
            return
        import asyncio

        from sqlalchemy import text

        from app.db.session import engine

        async def _ping() -> None:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        try:
            await asyncio.gather(*[_ping() for _ in range(min(settings.database_pool_size, 4))])
        except Exception:  # noqa: BLE001
            pass

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
