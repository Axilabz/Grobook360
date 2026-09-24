import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin
from app.core.accounting_constants import JNL_DRAFT, JOURNAL_STATUSES  # noqa: F401 (re-exported for callers)


class JournalEntry(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Journal header (PROMPT-025 §6) — the double-entry accounting
    record generated from an authoritative business transaction. The
    business transaction (Sales Invoice, Payment, ...) remains the
    source of truth (§3); this table is the accounting CONSEQUENCE of
    that transaction, never the other way round.

    `source_type`/`source_id`/`source_number` give the mandatory
    journal->source traceability (§50). `posting_event_type`
    ('ORIGINAL' or 'REVERSAL', see `app.core.accounting_constants`)
    together with `source_type`/`source_id` forms the idempotency key
    (§32) enforced by a unique DB constraint — a given source document
    can have at most one ORIGINAL journal and at most one REVERSAL
    journal.

    `reversal_of_journal_id` (self-FK, nullable): set only on a REVERSAL
    journal, pointing at the journal it reverses (§33). The ORIGINAL
    journal is NEVER edited when reversed — only its own `status`
    transitions POSTED -> REVERSED (§5/§39); amounts/lines stay exactly
    as first posted.

    `journal_date` is the source document's own date; `posting_date` is
    when this journal was actually created — §36 explicitly requires
    keeping these separate (in this MVP they are always equal at
    creation time, since accounting posts synchronously with the source
    transaction, but the columns are independent so a future backdated-
    posting scenario needs no schema change).

    `currency` is a fixed 'INR' for now — no multi-currency support
    exists anywhere in this codebase's baseline.
    """

    __tablename__ = "journal_entry"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    journal_number: Mapped[str] = mapped_column(String(50), nullable=False)
    journal_date: Mapped[date] = mapped_column(Date, nullable=False)
    posting_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    posting_event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=JNL_DRAFT)
    reversal_of_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("journal_entry.id"), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
