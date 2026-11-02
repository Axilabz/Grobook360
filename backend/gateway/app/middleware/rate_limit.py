"""Per-client-IP sliding-window rate limiter (foundation).

In-memory and per-process: with N gateway instances the effective limit is
N x the configured value. A shared limiter (Redis / Cloudflare rate limiting)
is a later step; the monolith keeps its own stricter login/sign-up limits.
"""

import time
from collections import defaultdict, deque

from shared.exceptions import ServiceError


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float | None = None) -> None:
        if self.limit <= 0:
            return
        now = time.monotonic() if now is None else now
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            retry_after = max(1, int(self.window - (now - hits[0])))
            raise ServiceError(
                429, "RATE_LIMITED", "Too many requests. Please slow down.", headers={"Retry-After": str(retry_after)}
            )
        hits.append(now)
        if len(self._hits) > 10_000:  # bound memory under address churn
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]:
                self._hits.pop(k, None)
