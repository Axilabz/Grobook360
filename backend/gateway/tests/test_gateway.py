import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from jose import jwt

from app.core.config import GatewaySettings
from app.core.routing import ROUTE_TABLE, resolve_service, resolve_upstream
from app.main import create_app

SECRET = "x" * 40


class Upstream:
    """In-process stand-in for the monolith; records what it was sent."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.behaviour = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.behaviour:
            return self.behaviour(request)
        return httpx.Response(200, json={"ok": True, "path": request.url.path})


def make_client(upstream: Upstream, **overrides) -> httpx.AsyncClient:
    settings = GatewaySettings(environment="testing", monolith_url="http://monolith", **overrides)
    app = create_app(settings, transport=httpx.MockTransport(upstream))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw")


def token(tenant: uuid.UUID | None = None, secret: str = SECRET, expires_in: int = 60) -> str:
    claims = {
        "sub": str(uuid.uuid4()),
        "jti": str(uuid.uuid4()),
        "role": "Owner",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_in),
    }
    if tenant:
        claims["tenant_id"] = str(tenant)
    return jwt.encode(claims, secret, algorithm="HS256")


# ---- routing ---------------------------------------------------------------

def test_routing_longest_prefix_and_default():
    assert resolve_service("auth/login") == "identity"
    assert resolve_service("products/123/units") == "master-data"
    assert resolve_service("sales/invoices/9/e-invoice") == "sales"
    assert resolve_service("purchase/orders") == "purchase"
    assert resolve_service("something-new") == "monolith"
    assert set(ROUTE_TABLE.values()) >= {"identity", "tenant", "master-data", "inventory", "sales", "purchase"}


def test_upstream_defaults_to_monolith_and_can_be_overridden():
    assert resolve_upstream("auth/login", {}, "http://m/") == ("identity", "http://m")
    assert resolve_upstream("auth/login", {"identity": "http://idp:8001"}, "http://m") == ("identity", "http://idp:8001")
    # an unrelated service override must not capture other routes
    assert resolve_upstream("products", {"identity": "http://idp"}, "http://m")[1] == "http://m"


# ---- proxy -----------------------------------------------------------------

async def test_forwards_method_path_query_and_body_with_api_prefix():
    up = Upstream()
    async with make_client(up) as c:
        r = await c.post("/api/v1/customers?x=1&y=two", content=b'{"a":1}', headers={"content-type": "application/json"})
    assert r.status_code == 200
    sent = up.requests[0]
    assert sent.method == "POST"
    assert str(sent.url) == "http://monolith/api/v1/customers?x=1&y=two"
    assert sent.content == b'{"a":1}'
    assert sent.headers["content-type"] == "application/json"


async def test_preserves_status_and_multiple_set_cookie_headers():
    up = Upstream()
    up.behaviour = lambda req: httpx.Response(
        201, json={"v": 1}, headers=[("set-cookie", "a=1; HttpOnly"), ("set-cookie", "b=2; Secure")]
    )
    async with make_client(up) as c:
        r = await c.post("/api/v1/auth/login")
    assert r.status_code == 201
    assert r.headers.get_list("set-cookie") == ["a=1; HttpOnly", "b=2; Secure"]


async def test_upstream_errors_are_relayed_unchanged():
    body = {"error": {"code": "AUTH-001", "message": "no", "details": []}, "meta": {"correlation_id": "x"}}
    up = Upstream()
    up.behaviour = lambda req: httpx.Response(401, json=body)
    async with make_client(up) as c:
        r = await c.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.json() == body


async def test_client_cannot_spoof_identity_headers():
    up = Upstream()
    async with make_client(up) as c:  # passthrough mode
        await c.get("/api/v1/customers", headers={"X-Tenant-Id": str(uuid.uuid4()), "X-User-Id": "evil", "X-Internal-Auth": "1"})
    h = up.requests[0].headers
    assert "x-tenant-id" not in h and "x-user-id" not in h and "x-internal-auth" not in h


async def test_correlation_id_generated_propagated_and_echoed():
    up = Upstream()
    cid = str(uuid.uuid4())
    async with make_client(up) as c:
        r = await c.get("/api/v1/customers", headers={"X-Correlation-Id": cid})
        r2 = await c.get("/api/v1/customers", headers={"X-Correlation-Id": "not-a-uuid"})
    assert up.requests[0].headers["x-correlation-id"] == cid
    assert r.headers["x-correlation-id"] == cid
    generated = r2.headers["x-correlation-id"]
    assert uuid.UUID(generated) and up.requests[1].headers["x-correlation-id"] == generated


async def test_forwarded_for_appends_peer():
    up = Upstream()
    async with make_client(up) as c:
        await c.get("/api/v1/customers", headers={"X-Forwarded-For": "1.2.3.4"})
    assert up.requests[0].headers["x-forwarded-for"].startswith("1.2.3.4, ")


async def test_upstream_down_returns_502_envelope():
    def boom(req):
        raise httpx.ConnectError("refused")

    up = Upstream()
    up.behaviour = boom
    async with make_client(up) as c:
        r = await c.get("/api/v1/customers")
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert r.json()["meta"]["correlation_id"]
    assert len(up.requests) == 2  # GET: one safe retry


async def test_mutating_request_is_never_retried():
    def boom(req):
        raise httpx.ConnectError("refused")

    up = Upstream()
    up.behaviour = boom
    async with make_client(up) as c:
        r = await c.post("/api/v1/sales/invoices")
    assert r.status_code == 502
    assert len(up.requests) == 1


async def test_upstream_timeout_returns_504_without_retry():
    def slow(req):
        raise httpx.ReadTimeout("slow")

    up = Upstream()
    up.behaviour = slow
    async with make_client(up) as c:
        r = await c.get("/api/v1/reports/dashboard")
    assert r.status_code == 504 and r.json()["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert len(up.requests) == 1


async def test_dedicated_service_url_is_used_only_for_its_routes():
    up = Upstream()
    async with make_client(up, service_urls={"identity": "http://identity:8001"}) as c:
        await c.post("/api/v1/auth/login")
        await c.get("/api/v1/products")
    assert str(up.requests[0].url).startswith("http://identity:8001/api/v1/auth/login")
    assert str(up.requests[1].url).startswith("http://monolith/api/v1/products")


# ---- auth (verify mode) ----------------------------------------------------

async def test_verify_mode_rejects_missing_forged_and_expired_tokens():
    up = Upstream()
    async with make_client(up, auth_mode="verify", jwt_secret_key=SECRET) as c:
        assert (await c.get("/api/v1/customers")).status_code == 401
        assert (await c.get("/api/v1/customers", cookies={"access_token": token(secret="y" * 40)})).status_code == 401
        assert (await c.get("/api/v1/customers", cookies={"access_token": token(expires_in=-5)})).status_code == 401
        assert (await c.get("/api/v1/customers", headers={"Authorization": "Bearer junk"})).status_code == 401
    assert up.requests == []  # nothing reached the backend


async def test_verify_mode_injects_tenant_from_token_not_from_client():
    up = Upstream()
    real, fake = uuid.uuid4(), uuid.uuid4()
    async with make_client(up, auth_mode="verify", jwt_secret_key=SECRET) as c:
        r = await c.get("/api/v1/customers", cookies={"access_token": token(real)}, headers={"X-Tenant-Id": str(fake)})
    assert r.status_code == 200
    assert up.requests[0].headers["x-tenant-id"] == str(real)
    assert up.requests[0].headers.get_list("x-tenant-id") == [str(real)]


async def test_verify_mode_lets_public_paths_through_and_accepts_bearer():
    up = Upstream()
    async with make_client(up, auth_mode="verify", jwt_secret_key=SECRET) as c:
        assert (await c.post("/api/v1/auth/login")).status_code == 200
        assert (await c.get("/api/v1/health")).status_code == 200
        assert (await c.get("/api/v1/customers", headers={"Authorization": f"Bearer {token()}"})).status_code == 200


async def test_verify_mode_without_secret_fails_closed():
    up = Upstream()
    async with make_client(up, auth_mode="verify") as c:
        r = await c.get("/api/v1/customers")
    assert r.status_code == 500 and r.json()["error"]["code"] == "GATEWAY_MISCONFIGURED"
    assert up.requests == []


async def test_passthrough_mode_does_not_inspect_tokens():
    up = Upstream()
    async with make_client(up) as c:
        r = await c.get("/api/v1/customers", headers={"Authorization": "Bearer junk"})
    assert r.status_code == 200 and up.requests[0].headers["authorization"] == "Bearer junk"


# ---- rate limit ------------------------------------------------------------

async def test_rate_limit_returns_429_envelope_with_retry_after():
    up = Upstream()
    async with make_client(up, rate_limit_per_minute=3) as c:
        codes = [(await c.get("/api/v1/customers")).status_code for _ in range(5)]
        last = await c.get("/api/v1/customers")
    assert codes == [200, 200, 200, 429, 429]
    assert last.json()["error"]["code"] == "RATE_LIMITED" and int(last.headers["retry-after"]) >= 1
    assert len(up.requests) == 3


# ---- gateway's own endpoints -------------------------------------------------

async def test_gateway_liveness_and_readiness():
    up = Upstream()
    async with make_client(up) as c:
        assert (await c.get("/gateway/health")).json()["data"]["status"] == "ok"
        ready = await c.get("/gateway/health/ready")
        assert ready.status_code == 200 and ready.json()["data"]["status"] == "ok"
        up.behaviour = lambda req: httpx.Response(500)
        assert (await c.get("/gateway/health/ready")).status_code == 503


async def test_gateway_routes_endpoint_hides_upstream_urls():
    up = Upstream()
    async with make_client(up, service_urls={"identity": "http://secret-host:1"}) as c:
        body = (await c.get("/gateway/routes")).text
    assert "secret-host" not in body and "identity" in body


async def test_logs_do_not_contain_query_or_tokens(capsys):
    up = Upstream()
    async with make_client(up) as c:
        await c.get("/api/v1/customers?phone=9876543210", headers={"Authorization": "Bearer SECRETTOKEN"})
    out = capsys.readouterr().out
    assert "SECRETTOKEN" not in out and "9876543210" not in out
    access = [json.loads(line) for line in out.splitlines() if '"gateway.access"' in line]
    assert access and access[0]["path"] == "/api/v1/customers" and access[0]["status"] == 200
