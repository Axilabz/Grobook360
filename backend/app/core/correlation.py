"""Request correlation ID: accepted from X-Correlation-Id, generated when absent,
propagated into response metadata and logs (PROMPT-001 S7)."""

import uuid
from contextvars import ContextVar

_correlation_id_ctx: ContextVar[uuid.UUID | None] = ContextVar("correlation_id", default=None)

HEADER_NAME = "X-Correlation-Id"


def get_correlation_id() -> uuid.UUID:
    current = _correlation_id_ctx.get()
    if current is None:
        current = uuid.uuid4()
        _correlation_id_ctx.set(current)
    return current


def set_correlation_id(value: uuid.UUID) -> None:
    _correlation_id_ctx.set(value)


def parse_or_generate(header_value: str | None) -> uuid.UUID:
    if header_value:
        try:
            return uuid.UUID(header_value)
        except ValueError:
            return uuid.uuid4()
    return uuid.uuid4()
