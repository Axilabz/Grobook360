# API Gateway

Single public entry point for `/api/v1/*`. A thin reverse proxy: it never
parses business payloads and contains no business logic.

| Concern | Behaviour |
|---|---|
| Routing | `app/core/routing.py` maps URL prefixes to service names; `SERVICE_URLS` maps names to URLs; anything without a URL goes to `MONOLITH_URL`. **Phase 1A: everything goes to the monolith.** Existing paths (`/api/v1/auth/login`, ...) are unchanged. |
| Auth | `AUTH_MODE=passthrough` (default): no behaviour change, the backend decides. `verify`: signature/expiry checked here, `X-Tenant-Id` / `X-User-Id` / `X-User-Role` derived **from the token**. Revocation (`auth_session`) is still enforced by the backend. |
| Identity headers | Client-supplied `X-Tenant-Id`, `X-User-Id`, `X-User-Role`, `X-Internal-Auth` are always stripped. |
| Correlation | `X-Correlation-Id` accepted if a UUID, else generated; forwarded upstream and echoed. |
| Errors | Same `{error, meta}` envelope as the monolith. Upstream errors are relayed untouched; gateway-originated: 401, 429, 502 `UPSTREAM_UNAVAILABLE`, 504 `UPSTREAM_TIMEOUT`. |
| Retries | Only GET/HEAD/OPTIONS, only on connect errors, once. Mutating requests are never retried. |
| Rate limit | `RATE_LIMIT_PER_MINUTE` per client IP, in-memory per instance (0 = off). |
| Logging | JSON access log: method, path, status, duration, correlation id. No query strings, headers or bodies. |
| Health | `GET /gateway/health` (liveness), `GET /gateway/health/ready` (all upstreams), `GET /gateway/routes`. `/api/v1/health` is still relayed to the monolith. |

## Run

```bash
cd backend
pip install -r gateway/requirements.txt
cd gateway
PYTHONPATH=.. MONOLITH_URL=http://localhost:8000 uvicorn app.main:app --port 8080
```

## Test

Run in its own process (the monolith also has a top-level `app` package):

```bash
cd backend/gateway && pip install -r requirements-test.txt && pytest
```

## Known limits
- Rate limiter is per-process (not shared across instances).
- Request/response bodies are buffered, not streamed (fine for JSON APIs; revisit for large file exports).
- WebSockets are not proxied (none exist in the API today).
