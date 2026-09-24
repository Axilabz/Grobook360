import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class AccountMapping(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Posting-rule -> account resolution (PROMPT-025 §10) — the ONLY
    mechanism posting logic uses to find an account; a `posting_rule_code`
    (see `app.core.accounting_constants.POSTING_RULE_CODES`) is never a
    hard-coded account id. One row per tenant+code (unique constraint),
    lazily seeded alongside `ChartOfAccount` with the same documented
    "default, not approved final" caveat (§56 OD-003/OD-004/OD-011/
    OD-012/OD-013).
    """

    __tablename__ = "account_mapping"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    posting_rule_code: Mapped[str] = mapped_column(String(50), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("chart_of_account.id"), nullable=False)
