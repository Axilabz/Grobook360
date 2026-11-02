"""Gateway's own health endpoints (under /gateway so they never shadow the
monolith's existing /api/v1/health, which the proxy still relays)."""

import asyncio
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.routing import ROUTE_TABLE
from shared.middleware import get_correlation_id

router = APIRouter(prefix="/gateway", tags=["gateway"])


def _meta() -> dict:
    return {"correlation_id": get_correlation_id(), "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/health")
async def liveness() -> dict:
    """Process is up. Does not touch any upstream."""
    return {"data": {"status": "ok", "service": "gateway"}, "meta": _meta()}


@router.get("/health/ready")
async def readiness(request: Request) -> JSONResponse:
    """Ready only if every distinct configured upstream answers /api/v1/health."""
    settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.http_client
    upstreams = {settings.monolith_url.rstrip("/")} | {u.rstrip("/") for u in settings.service_urls.values()}

    async def probe(base: str) -> tuple[str, str]:
        try:
            r = await client.get(f"{base}{settings.api_v1_prefix}/health", timeout=3.0)
            return base, "ok" if r.status_code == 200 else f"http_{r.status_code}"
        except httpx.HTTPError:
            return base, "unreachable"

    results = dict(await asyncio.gather(*[probe(b) for b in sorted(upstreams)]))
    healthy = all(v == "ok" for v in results.values())
    return JSONResponse(
        {"data": {"status": "ok" if healthy else "degraded", "upstreams": results}, "meta": _meta()},
        status_code=200 if healthy else 503,
    )


@router.get("/routes")
async def routes(request: Request) -> dict:
    """The effective routing table (service names only; upstream URLs omitted)."""
    configured = sorted(request.app.state.settings.service_urls)
    return {"data": {"routes": ROUTE_TABLE, "services_with_dedicated_url": configured}, "meta": _meta()}
