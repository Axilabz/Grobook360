"""Catch-all reverse proxy for /api/v1/*.

The gateway never interprets request/response bodies: it authenticates (if
enabled), stamps trusted identity headers, forwards, and relays. Business
rules, validation and authorization stay in the owning service.
"""

import asyncio
import logging

import httpx
from fastapi import APIRouter, Request, Response

from app.core.config import GatewaySettings
from app.core.routing import resolve_upstream
from app.dependencies.auth import authenticate
from shared.exceptions import ServiceError
from shared.middleware import HEADER_NAME, get_correlation_id
from shared.security import INTERNAL_IDENTITY_HEADERS

logger = logging.getLogger("gateway.proxy")

router = APIRouter()

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
    "transfer-encoding", "upgrade", "host", "content-length",
}
# httpx transparently decodes the upstream body, so the encoding/length headers
# of the original response no longer describe what we send.
_STRIP_RESPONSE = _HOP_BY_HOP | {"content-encoding"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _client_ip(request: Request, settings: GatewaySettings) -> str:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _forward_headers(request: Request, settings: GatewaySettings, claims) -> list[tuple[str, str]]:
    headers = [
        (k, v)
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP
        and k.lower() not in INTERNAL_IDENTITY_HEADERS  # a client can never assert identity
        and k.lower() != HEADER_NAME.lower()
    ]
    headers.append((HEADER_NAME, get_correlation_id()))
    peer = request.client.host if request.client else "unknown"
    prior = request.headers.get("x-forwarded-for")
    headers = [(k, v) for k, v in headers if k.lower() != "x-forwarded-for"]
    headers.append(("X-Forwarded-For", f"{prior}, {peer}" if prior else peer))
    headers.append(("X-Forwarded-Proto", request.headers.get("x-forwarded-proto", request.url.scheme)))
    if claims is not None:
        headers.append(("X-User-Id", str(claims.user_id)))
        if claims.tenant_id:
            headers.append(("X-Tenant-Id", str(claims.tenant_id)))
        if claims.role:
            headers.append(("X-User-Role", claims.role))
    return headers


@router.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"], include_in_schema=False
)
async def proxy(path: str, request: Request) -> Response:
    settings: GatewaySettings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.http_client

    request.app.state.rate_limiter.check(_client_ip(request, settings))

    claims = authenticate(request, path, settings) if settings.auth_mode == "verify" else None
    service, base_url = resolve_upstream(path, settings.service_urls, settings.monolith_url)

    url = f"{base_url}{settings.api_v1_prefix}/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    body = await request.body()
    headers = _forward_headers(request, settings, claims)

    attempts = 1 + (settings.safe_retry_attempts if request.method in _SAFE_METHODS else 0)
    upstream: httpx.Response | None = None
    for attempt in range(1, attempts + 1):
        try:
            upstream = await client.request(request.method, url, headers=headers, content=body)
            break
        except httpx.TimeoutException:
            logger.warning("Upstream timeout", extra={"extra_fields": {"upstream": service}})
            raise ServiceError(504, "UPSTREAM_TIMEOUT", "The service took too long to respond")
        except httpx.ConnectError:
            if attempt == attempts:
                logger.error("Upstream unavailable", extra={"extra_fields": {"upstream": service}})
                raise ServiceError(502, "UPSTREAM_UNAVAILABLE", "The service is temporarily unavailable")
            await asyncio.sleep(0.1 * attempt)
        except httpx.TransportError:
            logger.error("Upstream transport error", extra={"extra_fields": {"upstream": service}})
            raise ServiceError(502, "UPSTREAM_UNAVAILABLE", "The service is temporarily unavailable")

    assert upstream is not None
    response = Response(
        content=upstream.content if request.method != "HEAD" else b"",
        status_code=upstream.status_code,
    )
    # multi_items() keeps EVERY Set-Cookie header (a dict would drop all but one).
    for key, value in upstream.headers.multi_items():
        if key.lower() in _STRIP_RESPONSE or key.lower() == HEADER_NAME.lower():
            continue
        response.raw_headers.append((key.lower().encode("latin-1"), value.encode("latin-1")))
    return response
