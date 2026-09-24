"""Structured application logging (PROMPT-001 S13).

Emits one JSON object per log line with timestamp, level, logger/module name,
correlation ID, and tenant/user context where available. Never logs passwords,
tokens, secrets or credentials — callers must not pass them as log fields.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.correlation import get_correlation_id

_REDACTED_KEYS = {"password", "password_hash", "token", "access_token", "secret", "authorization"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        try:
            payload["correlation_id"] = str(get_correlation_id())
        except LookupError:
            pass

        for key in ("tenant_id", "user_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = str(value)

        if record.exc_info:
            payload["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None

        extra = getattr(record, "extra_fields", None)
        if extra:
            for key, value in extra.items():
                if key.lower() not in _REDACTED_KEYS:
                    payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
