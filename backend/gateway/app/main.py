from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api import health, proxy
from app.core.config import GatewaySettings, get_settings
from app.middleware.rate_limit import SlidingWindowLimiter
from app.middleware.request_logging import RequestLoggingMiddleware
from shared.exceptions import register_exception_handlers
from shared.logging import configure_logging
from shared.middleware import CorrelationIdMiddleware


def create_app(
    settings: GatewaySettings | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    """`transport` lets tests replace the network with an in-process upstream."""
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)

    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.read_timeout_seconds, connect=settings.connect_timeout_seconds),
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        transport=transport,
        follow_redirects=False,  # relay redirects to the browser, never follow them
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await http_client.aclose()

    app = FastAPI(
        title="Grobook 360 API Gateway",
        version="1.0.0",
        docs_url="/gateway/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/gateway/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.http_client = http_client
    app.state.rate_limiter = SlidingWindowLimiter(settings.rate_limit_per_minute)

    # Added last = outermost. Order: correlation id -> access log -> gzip -> CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(proxy.router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
