"""GST verification provider abstraction (PROMPT-002 S8; FRD OQ-003, still open).

No production GST/GSP verification provider is selected yet. This interface lets
a real provider be plugged in later without redesigning the sign-up flow.
NullGSTProvider (the only implementation here) never calls out to any external
service — it always reports "not available", so sign-up falls back to
format-only validation, matching S8's requirement to never silently invent an
external contract.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class GSTLookupResult:
    available: bool
    verified: bool
    legal_name: str | None = None
    trade_name: str | None = None
    state_code: str | None = None
    error_message: str | None = None


class GSTVerificationProvider(ABC):
    @abstractmethod
    async def lookup(self, gstin: str) -> GSTLookupResult: ...


class NullGSTProvider(GSTVerificationProvider):
    """No provider configured. Always reports unavailable, never fabricates data."""

    async def lookup(self, gstin: str) -> GSTLookupResult:
        return GSTLookupResult(available=False, verified=False)


def get_gst_provider() -> GSTVerificationProvider:
    return NullGSTProvider()
