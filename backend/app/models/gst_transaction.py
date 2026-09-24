import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class GstTransaction(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """GST transaction snapshot header (PROMPT-026 §17/§21/§22) — the
    authoritative, immutable GST reporting record created when a source
    business document is posted/confirmed. This is the "single
    authoritative GST calculation" (§2) output, captured for reporting;
    it NEVER recalculates tax — every value here is copied verbatim from
    the source document's own already-calculated totals (`sales_invoice.
    taxable_total`, etc.), which are themselves produced by the one
    shared `gst_calculation_service` (§2/AC-001/AC-002).

    Mirrors `JournalEntry`'s exact idempotency/reversal shape (PROMPT-025)
    on purpose — `(tenant_id, source_type, source_id, event_type)` is
    unique (§42 idempotency); a REVERSAL is a brand-new row with negated
    amounts and `reversal_of_transaction_id` set, the ORIGINAL row is
    NEVER edited (§21 "historical GST values are immutable"). `source_type`
    reuses the identical string vocabulary as `journal_entry.source_type`
    (`app.core.accounting_constants.SRC_*`) so §24 reconciliation can join
    the two tables on `(tenant_id, source_type, source_id)` directly.

    `return_period` ("YYYY-MM") and `financial_year_label` are derived
    once at snapshot time from `document_date` — the basis for GSTR-1/
    GSTR-3B period aggregation (§30). `classification` (B2B/B2C) and
    `direction` (OUTWARD/INWARD) are the two axes GSTR-1's own sections
    split on (§28).
    """

    __tablename__ = "gst_transaction"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reversal_of_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("gst_transaction.id"), nullable=True
    )
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    classification: Mapped[str] = mapped_column(String(10), nullable=False)
    party_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    party_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    party_gstin: Mapped[str | None] = mapped_column(CHAR(15), nullable=True)
    place_of_supply_state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    document_date: Mapped[date] = mapped_column(Date, nullable=False)
    financial_year_label: Mapped[str] = mapped_column(String(10), nullable=False)
    return_period: Mapped[str] = mapped_column(String(7), nullable=False)
    taxable_value: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cess_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    total_gst: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
