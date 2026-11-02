import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from jose import jwt

from shared.exceptions import ServiceError, register_exception_handlers
from shared.logging import JsonFormatter
from shared.middleware import CorrelationIdMiddleware
from shared.security import extract_token, verify_access_token
from shared.utilities import ServiceCallError, ServiceClient

SECRET = "s" * 40


def _tok(**extra):
    claims = {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) + timedelta(minutes=5), **extra}
    return jwt.encode(claims, SECRET, algorithm="HS256")


def test_verify_access_token_reads_tenant_and_rejects_bad_tokens():
    tenant = uuid.uuid4()
    claims = verify_access_token(_tok(tenant_id=str(tenant), role="Manager", jti=str(uuid.uuid4())), SECRET)
    assert claims and claims.tenant_id == tenant and claims.role == "Manager"
    assert verify_access_token("garbage", SECRET) is None
    assert verify_access_token(_tok(), "w" * 40) is None
    assert verify_access_token(jwt.encode({"sub": "not-a-uuid"}, SECRET, algorithm="HS256"), SECRET) is None


def test_extract_token_prefers_cookie_then_bearer():
    assert extract_token({"access_token": "c"}, "Bearer b", "access_token") == "c"
    assert extract_token({}, "Bearer b", "access_token") == "b"
    assert extract_token({}, "Basic zzz", "access_token") is None


async def test_error_envelope_matches_monolith_shape():
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)

    @app.get("/e")
    async def e():
        raise ServiceError(409, "X-001", "conflict", [{"field": "a"}])

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret internals")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
        r = await c.get("/e")
        assert r.status_code == 409
        body = r.json()
        assert body["error"] == {"code": "X-001", "message": "conflict", "details": [{"field": "a"}]}
        assert body["meta"]["correlation_id"] == r.headers["x-correlation-id"]
        b = await c.get("/boom")
        assert b.status_code == 500 and "secret internals" not in b.text
        assert (await c.get("/missing")).json()["error"]["code"] == "NOT_FOUND"


def test_json_logs_redact_secrets_and_url_credentials():
    rec = logging.LogRecord("t", logging.INFO, "f", 1, "connect postgresql://u:hunter2@host/db", (), None)
    rec.extra_fields = {"password": "hunter2", "nested": {"api_key": "k", "ok": "fine"}, "note": "x"}
    out = JsonFormatter("svc").format(rec)
    assert "hunter2" not in out and '"ok": "fine"' in out
    assert json.loads(out)["service"] == "svc"


class Flaky:
    def __init__(self, fail_times, status=None):
        self.calls, self.fail_times, self.status = [], fail_times, status

    def __call__(self, request):
        self.calls.append(request)
        if len(self.calls) <= self.fail_times:
            if self.status:
                return httpx.Response(self.status)
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"ok": 1})


def _client(handler, **kw):
    return ServiceClient("svc", "http://svc", transport=httpx.MockTransport(handler), backoff_seconds=0, **kw)


async def test_service_client_retries_get_and_propagates_correlation():
    h = Flaky(fail_times=2)
    r = await _client(h).request("GET", "/x")
    assert r.status_code == 200 and len(h.calls) == 3
    assert all("x-correlation-id" in c.headers for c in h.calls)


async def test_service_client_never_retries_bare_post_but_retries_with_idempotency_key():
    h = Flaky(fail_times=1)
    with pytest.raises(ServiceCallError) as e:
        await _client(h).request("POST", "/pay")
    assert e.value.kind == "unavailable" and len(h.calls) == 1

    h2 = Flaky(fail_times=1)
    r = await _client(h2).request("POST", "/pay", headers={"Idempotency-Key": "k1"})
    assert r.status_code == 200 and len(h2.calls) == 2


async def test_service_client_retries_503_but_not_4xx_and_reports_timeout():
    h = Flaky(fail_times=1, status=503)
    assert (await _client(h).request("GET", "/x")).status_code == 200

    h4 = Flaky(fail_times=5, status=422)
    assert (await _client(h4).request("GET", "/x")).status_code == 422 and len(h4.calls) == 1

    def slow(req):
        raise httpx.ReadTimeout("t")

    with pytest.raises(ServiceCallError) as e:
        await _client(slow, max_retries=0).request("GET", "/x")
    assert e.value.kind == "timeout"
