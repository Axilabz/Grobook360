from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables / .env file.

    No default is provided for secrets — missing required configuration must fail
    application startup rather than silently fall back to an insecure default.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "testing", "production"] = "development"

    api_v1_prefix: str = "/api/v1"
    project_name: str = "SaaS MVP Platform"

    database_url: PostgresDsn = Field(..., description="postgresql+asyncpg://user:pass@host:port/db")
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_echo: bool = False

    jwt_secret_key: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    cors_allow_origins: list[str] = Field(default_factory=list)

    log_level: str = "INFO"

    # --- PROMPT-002 open decisions, implemented as configuration rather than
    # silently hard-coded (see PROMPT-002-NOTES.md for the full rationale) ---

    # API-OD-03 (open): platform-wide vs tenant-scoped phone uniqueness.
    # Defaults to the less restrictive option (tenant-scoped) until decided.
    phone_uniqueness_scope: Literal["tenant", "platform"] = "tenant"

    # Exact password complexity policy is not specified in any baseline document
    # available to this codebase (the "legacy FRD Complete Edition v1.0" it
    # references is not present). Minimum-length-only placeholder pending a
    # BA/product decision.
    password_min_length: int = 8

    # Placeholder abuse-protection threshold for the public sign-up endpoint
    # (PROMPT-002 S21: "do not invent a specific rate limit without documenting
    # it as a security configuration decision"). Documented here, not silent.
    signup_rate_limit_per_ip_per_hour: int = 10

    # --- PROMPT-003 open decisions (see PROMPT-003-NOTES.md) ---

    # FRD FR-SI-09 ("5 attempts / 15 minutes") is explicitly marked "Legacy FRD;
    # product confirmation required" — NOT an approved value. Same numbers used
    # here only as a documented placeholder pending that confirmation.
    login_lockout_threshold: int = 5
    login_lockout_duration_minutes: int = 15
    login_rate_limit_per_ip_per_hour: int = 30

    # Session/token architecture (PROMPT-003 S12 decision — see notes file):
    # PROMPT-001's single 60-min JWT access token is kept as-is; no refresh
    # token is introduced. The browser transport is an httpOnly cookie rather
    # than JS-readable storage, to remove the XSS token-theft surface S12 flags.
    auth_cookie_name: str = "access_token"
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # --- PROMPT-004 open decisions (see PROMPT-004-NOTES.md) ---

    # No email delivery provider is approved/available yet (S4/S28). Token
    # lifecycle/API/DB are fully real; only the outbound send is a dev-only
    # console stub pending a real provider decision.
    password_reset_token_expire_minutes: int = 30
    password_reset_rate_limit_per_ip_per_hour: int = 10
    password_reset_identifier_rate_limit_per_hour: int = 5

    # Used only to build the reset link the (dev-stub) recovery provider
    # "sends" — matches the Vite dev server's configured port (see vite.config.ts).
    frontend_base_url: str = "http://localhost:3000"

    # --- PROMPT-018 open decisions (see PROMPT-018-NOTES.md) ---

    # No GST/NIC integration provider is approved/selected yet (§43 open
    # decision #1). Only a deterministic sandbox/test simulator exists
    # (app.services.gst_integration.provider.SandboxSimulatorProvider);
    # it must never run when is_production is true — get_einvoice_
    # provider()/get_eway_bill_provider() raise in that case, the same
    # fail-loudly-not-silently pattern as get_recovery_provider().
    gst_integration_default_timeout_seconds: int = 30
    gst_integration_default_max_retry_attempts: int = 3
    gst_integration_default_retry_backoff_seconds: int = 5

    # Fernet key encrypting `integration_configuration.credentials_
    # encrypted` (§6/§31 — never plaintext). No key-management/rotation
    # strategy is approved yet (§43 open decision #11, "integration
    # credential storage mechanism"); a dev-only deterministic fallback
    # (derived from jwt_secret_key) is used when this is unset so local/
    # test environments work without extra setup — production MUST set
    # its own independent key. See get_credential_encryption_key().
    gst_integration_credential_key: str | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
