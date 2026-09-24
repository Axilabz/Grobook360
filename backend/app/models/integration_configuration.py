import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

SANDBOX = "SANDBOX"
PRODUCTION = "PRODUCTION"

ENVIRONMENTS = frozenset({SANDBOX, PRODUCTION})


class IntegrationConfiguration(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """GST/NIC integration configuration (PROMPT-018 §6/§7) — ONE ROW PER
    TENANT (M1: one tenant = one business = one GSTIN, per §7). GSTIN
    itself is never duplicated here — always read live from `tenant.gstin`
    at request time.

    `credentials_encrypted`: a Fernet-encrypted JSON blob (client secret /
    API key / whatever the eventually-selected provider needs) — see
    `app/services/gst_integration/crypto.py`. NEVER plaintext, NEVER
    logged, NEVER returned by any API response (§6/§31 explicit
    requirement). The exact provider/credential shape is an Open
    Decision (#1/#2/#3, see PROMPT-018-NOTES.md) — this column's shape
    is provider-agnostic (opaque encrypted JSON) precisely so a real
    provider can be wired in later without a schema change.

    `einvoice_enabled`/`eway_bill_enabled`: the HONEST resolution of
    §8/§18's "applicability" requirement — no approved legal turnover
    threshold or transaction-type rule exists in any source document
    available to this codebase, so applicability is a tenant-level
    opt-in toggle plus a data-completeness readiness check, not an
    invented legal rule (§53 Open Decision #4/#5).
    """

    __tablename__ = "integration_configuration"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="SANDBOX_SIMULATOR")
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default=SANDBOX)
    api_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    max_retry_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    retry_backoff_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    einvoice_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    eway_bill_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
