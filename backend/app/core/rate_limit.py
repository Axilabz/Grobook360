"""In-memory rate limiter, keyed by caller-supplied identifier (PROMPT-002 S21,
reused by PROMPT-003 S24 for login).

Placeholder defensive control for public/high-risk endpoints (sign-up, login).
Thresholds (settings.signup_rate_limit_per_ip_per_hour,
settings.login_rate_limit_per_ip_per_hour) are explicitly NOT product/security
decisions made here — documented, configurable defaults pending real sign-off.
In-memory state is per-process only; a multi-instance deployment needs a
shared store (Redis etc.) — noted as a known limitation, not solved here.
"""

import time
from collections import defaultdict

from app.core.exceptions import RateLimitedError

_WINDOW_SECONDS = 3600
_hits: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(
    client_ip: str,
    limit_per_hour: int,
    *,
    message: str = "Too many attempts. Please try again later.",
    code: str | None = None,
) -> None:
    now = time.monotonic()
    window_start = now - _WINDOW_SECONDS

    recent = [t for t in _hits[client_ip] if t >= window_start]
    if len(recent) >= limit_per_hour:
        _hits[client_ip] = recent
        raise RateLimitedError(message, code=code)

    recent.append(now)
    _hits[client_ip] = recent


def reset_rate_limits() -> None:
    """Test-only hook: clears in-memory rate-limit state between test cases."""
    _hits.clear()
