# Deployment approach (Cloudflare-compatible)

## What exists today (inspected)
| Layer | Runtime |
|---|---|
| Frontend | Cloudflare Pages (static Vite build) at `grobook360np.axilabz.com` |
| `/api/*` | Pages Function `functions/api/[[path]].ts` → proxies to env `BACKEND_ORIGIN` |
| Backend | FastAPI container (`backend/Dockerfile`) reached over a Cloudflare Tunnel (`api-np.axilabz.com` → `localhost:8000`) |
| Database | Supabase PostgreSQL (eu-west-1 session pooler) |

## Constraint
Cloudflare Pages/Workers cannot run FastAPI + asyncpg (native driver). Python containers need a container runtime: **Cloudflare Containers** (beta; unverified for this project) or any Docker host (VPS, Render, Railway, Fly) fronted by a Cloudflare Tunnel or its own URL. The hosting provider and DNS are **not changed** by Phase 1A.

## Target (Phase 1A) — one extra hop, no other change
```
Pages Function  →  BACKEND_ORIGIN = gateway  →  monolith (internal URL)
```
1. Run two containers: `monolith` (existing image, **not publicly exposed**) and `gateway` (`backend/gateway/Dockerfile`, build context `backend/`).
2. Point the tunnel / `BACKEND_ORIGIN` at the **gateway** (port 8080); the monolith becomes reachable only by the gateway over the private network.
3. Gateway env: `MONOLITH_URL`, `JWT_SECRET_KEY` (same as backend), `CORS_ALLOW_ORIGINS`, `TRUST_PROXY_HEADERS=true` (it sits behind Cloudflare), `AUTH_MODE=passthrough`.
4. Monolith keeps running with `--proxy-headers`; the gateway appends the real peer to `X-Forwarded-For`, so the monolith's per-IP login/sign-up limits still see client addresses. **Verify this on staging** before relying on it.

Rollback is one setting: point `BACKEND_ORIGIN`/tunnel back to the monolith.

## Independent deployment of services (Phase 1B+)
Each service = its own image + its own container + its own `SERVICE_URLS` entry in the gateway. Deploying one does not rebuild the others. Migrations (Alembic, owner role) are run once per release as a separate step, never at container start.

## Not done / needs approval
- Nothing was deployed; DNS, tunnel and Pages settings untouched.
- `docker build` could not be executed on the development machine (Docker not installed) — images are **unverified** until CI or a Docker host builds them.
