"""Correlation-ID propagation (same header/contract as app.core.correlation).

Pure-ASGI (not BaseHTTPMiddleware) so it adds no per-request task overhead and
works for streaming responses. Accepts a valid UUID from X-Correlation-Id,
otherwise generates one, and always echoes it on the response.
"""

import uuid
from contextvars import ContextVar

HEADER_NAME = "X-Correlation-Id"
_HEADER_BYTES = HEADER_NAME.lower().encode()

_correlation_id: ContextVar[str | None] = ContextVar("shared_correlation_id", default=None)


def get_correlation_id() -> str:
    current = _correlation_id.get()
    if current is None:
        current = str(uuid.uuid4())
        _correlation_id.set(current)
    return current


def _parse_or_generate(raw: bytes | None) -> str:
    if raw:
        try:
            return str(uuid.UUID(raw.decode("latin-1")))
        except ValueError:
            pass
    return str(uuid.uuid4())


class CorrelationIdMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(_HEADER_BYTES)
        correlation_id = _parse_or_generate(incoming)
        token = _correlation_id.set(correlation_id)
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        async def send_with_header(message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != _HEADER_BYTES]
                headers.append((_HEADER_BYTES, correlation_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _correlation_id.reset(token)
