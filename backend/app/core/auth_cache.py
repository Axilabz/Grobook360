"""Short-lived in-process cache of the per-request auth lookups (session still
active + role permissions).

Why: with a remote hosted database every query costs a full network round
trip, and authentication alone used 4-5 sequential queries on EVERY request.
Disabled by default (`auth_cache_ttl_seconds = 0`); enable per environment.

Trade-offs (deliberate): a role/permission edit may take up to the TTL to
reach an already-cached session; every session-revocation path (logout,
password reset, user deactivation) clears the whole cache immediately. The
cache is per-process, so with several workers a revocation handled by one
worker is seen by the others after at most the TTL.
"""

import time
import uuid

_cache: dict[uuid.UUID, tuple[float, frozenset[str]]] = {}


def get(jti: uuid.UUID, ttl: float) -> frozenset[str] | None:
    if ttl <= 0:
        return None
    hit = _cache.get(jti)
    if hit is None:
        return None
    if hit[0] < time.monotonic():
        _cache.pop(jti, None)
        return None
    return hit[1]


def put(jti: uuid.UUID, permissions: frozenset[str], ttl: float) -> None:
    if ttl <= 0:
        return
    if len(_cache) > 5000:
        _cache.clear()
    _cache[jti] = (time.monotonic() + ttl, permissions)


def invalidate_all() -> None:
    _cache.clear()
