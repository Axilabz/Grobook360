"""Structured JSON logging with correlation id and secret redaction."""

import json
import logging
import re
import sys
from datetime import datetime, timezone

from shared.middleware.correlation import get_correlation_id

# Values for these keys (in `extra_fields`) are never written to logs.
_SENSITIVE_KEYS = re.compile(
    r"(password|secret|token|authorization|cookie|api[_-]?key|credential|database_url)", re.I
)
# Defensive: scrub credentials embedded in URLs inside free-text messages.
_URL_CREDENTIALS = re.compile(r"(://[^/\s:@]+:)[^@\s/]+@")


def _redact(value):
    if isinstance(value, dict):
        return {k: "***" if _SENSITIVE_KEYS.search(str(k)) else _redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        return _URL_CREDENTIALS.sub(r"\1***@", value)
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": _URL_CREDENTIALS.sub(r"\1***@", record.getMessage()),
            "correlation_id": get_correlation_id(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(_redact(extra))
        if record.exc_info:
            payload["exception"] = _URL_CREDENTIALS.sub(r"\1***@", self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(service_name: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # httpx/httpcore log every request URL INCLUDING the query string (phone
    # numbers, search terms) at INFO. Keep them at WARNING; the gateway's own
    # access log records method/path/status only.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))
