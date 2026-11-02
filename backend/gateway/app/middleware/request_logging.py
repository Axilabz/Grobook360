"""Structured access log: method, path, status, duration, correlation id.

Never logs headers, cookies, query strings or bodies (they can carry tokens,
phone numbers and passwords).
"""

import logging
import time

logger = logging.getLogger("gateway.access")


class RequestLoggingMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status = {"code": 500}

        async def capture(message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            logger.info(
                "request",
                extra={
                    "extra_fields": {
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status["code"],
                        "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    }
                },
            )
