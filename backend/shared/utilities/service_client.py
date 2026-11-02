"""Internal service-to-service HTTP client (HTTPX).

Rules enforced here so no caller can get them wrong:
  * explicit connect/read timeouts (no unbounded waits);
  * X-Correlation-Id propagated on every call;
  * retries ONLY when repeating the call cannot duplicate a side effect:
    GET/HEAD/OPTIONS, or any method carrying an Idempotency-Key header.
    A bare POST/PUT/PATCH/DELETE is never auto-retried (financial safety);
  * only connection-level failures and 502/503/504 are retried, never 4xx.
"""

import asyncio
import logging

import httpx

from shared.middleware.correlation import HEADER_NAME, get_correlation_id

logger = logging.getLogger("shared.service_client")

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_RETRYABLE_STATUS = {502, 503, 504}


class ServiceCallError(Exception):
    def __init__(self, service: str, kind: str, detail: str = "") -> None:
        super().__init__(f"{service}: {kind} {detail}".strip())
        self.service = service
        self.kind = kind  # "unavailable" | "timeout"


class ServiceClient:
    def __init__(
        self,
        service_name: str,
        base_url: str,
        *,
        connect_timeout: float = 3.0,
        read_timeout: float = 30.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.service_name = service_name
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _may_retry(method: str, headers: dict[str, str]) -> bool:
        return method.upper() in _SAFE_METHODS or any(k.lower() == "idempotency-key" for k in headers)

    async def request(
        self, method: str, path: str, *, headers: dict[str, str] | None = None, **kwargs
    ) -> httpx.Response:
        headers = dict(headers or {})
        headers.setdefault(HEADER_NAME, get_correlation_id())
        attempts = 1 + (self._max_retries if self._may_retry(method, headers) else 0)

        for attempt in range(1, attempts + 1):
            last = attempt == attempts
            try:
                response = await self._client.request(method, path, headers=headers, **kwargs)
            except httpx.TimeoutException as exc:
                if last:
                    raise ServiceCallError(self.service_name, "timeout", type(exc).__name__) from exc
            except httpx.TransportError as exc:
                if last:
                    raise ServiceCallError(self.service_name, "unavailable", type(exc).__name__) from exc
            else:
                if response.status_code not in _RETRYABLE_STATUS or last:
                    return response
            logger.warning("Retrying %s %s (attempt %d/%d)", method, path, attempt, attempts)
            await asyncio.sleep(self._backoff * attempt)
        raise AssertionError("unreachable")  # pragma: no cover
