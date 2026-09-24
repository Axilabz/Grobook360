import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class JournalLine(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Journal line (PROMPT-025 §7) — one debit OR credit leg of a
    Journal Entry. A DB CHECK constraint (migration 0026) enforces
    exactly one of `debit_amount`/`credit_amount` is > 0 and the other
    is exactly 0 — never both positive, never both zero (§7's own
    explicit rule).

    `reference_type`/`reference_id` optionally point at a finer-grained
    source (e.g. a specific invoice line) — unused by this prompt's own
    posting rules (which post at document-header granularity only) but
    kept per §7's own conceptual field list for a future line-level
    posting need.
    """

    __tablename__ = "journal_line"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    journal_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("journal_entry.id"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("chart_of_account.id"), nullable=False)
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
