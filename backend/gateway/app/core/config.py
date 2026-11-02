from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """Gateway configuration (env / .env). Preserves the monolith's variable
    names where the meaning is the same (JWT_SECRET_KEY, CORS_ALLOW_ORIGINS,
    LOG_LEVEL, ENVIRONMENT, AUTH_COOKIE_NAME)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    service_name: str = "gateway"
    environment: Literal["development", "testing", "production"] = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    # Where requests go unless SERVICE_URLS overrides the owning service.
    # Phase 1A: the whole API is still served by the monolith.
    monolith_url: str = "http://localhost:8000"
    # JSON object, e.g. {"identity": "http://identity-service:8001"}. Keys are
    # the service names in core/routing.py. Absent key -> monolith_url.
    service_urls: dict[str, str] = Field(default_factory=dict)

    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 60.0
    # GET/HEAD only (never mutating requests): extra attempts on connect errors.
    safe_retry_attempts: int = 1

    cors_allow_origins: list[str] = Field(default_factory=list)

    # passthrough: the backend remains the only authority (default, zero
    #   behaviour change). verify: gateway rejects missing/forged/expired
    #   tokens early and injects X-Tenant-Id/X-User-Id derived from the token.
    auth_mode: Literal["passthrough", "verify"] = "passthrough"
    jwt_secret_key: str | None = Field(default=None, min_length=32)
    jwt_algorithm: str = "HS256"
    auth_cookie_name: str = "access_token"

    # Requests per client IP per minute across /api/v1 (0 = disabled).
    # In-memory, per-instance: a foundation, not a distributed limiter.
    rate_limit_per_minute: int = 0
    # Only honour X-Forwarded-For for rate limiting when running behind a
    # proxy you control (Cloudflare/tunnel); otherwise it is client-spoofable.
    trust_proxy_headers: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> GatewaySettings:
    return GatewaySettings()
