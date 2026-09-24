"""Per-login-identifier lockout tracker (PROMPT-003 S24; FRD FR-SI-09).

FR-SI-09 ("5 attempts / 15 minutes") is explicitly marked "Legacy FRD; product
confirmation required" in the FRD — NOT an approved value. This module
implements the mechanism with configurable threshold/duration
(settings.login_lockout_threshold / login_lockout_duration_minutes), using
those same numbers only as a documented placeholder default, per S24's
explicit instruction not to hardcode an unapproved value.

In-memory/per-process only, same known limitation as app.core.rate_limit —
needs a shared store (Redis etc.) for a real multi-instance deployment.
"""

import time
from collections import defaultdict

_failures: dict[str, list[float]] = defaultdict(list)


def record_failure(identifier: str) -> None:
    _failures[identifier].append(time.monotonic())


def clear(identifier: str) -> None:
    _failures.pop(identifier, None)


def is_locked(identifier: str, *, threshold: int, duration_minutes: int) -> bool:
    window_start = time.monotonic() - (duration_minutes * 60)
    recent = [t for t in _failures[identifier] if t >= window_start]
    _failures[identifier] = recent
    return len(recent) >= threshold


def reset_all() -> None:
    """Test-only hook."""
    _failures.clear()
