import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

DRAFT = "DRAFT"
CALCULATED = "CALCULATED"
FINALIZED = "FINALIZED"
REVERSED = "REVERSED"
PAYROLL_RUN_STATUSES = frozenset({DRAFT, CALCULATED, FINALIZED, REVERSED})


class PayrollRun(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Payroll Run (PROMPT-029 §19/§35) — one run per payroll period.

    §35/OD-021: the approval workflow is collapsed to THREE states
    (DRAFT -> CALCULATED -> FINALIZED), not the prompt's own suggested
    5-stage DRAFT/CALCULATED/REVIEWED/APPROVED/FINALIZED chain — no
    approved source defines a separate reviewer/approver role distinct
    from whoever finalizes, so a dedicated REVIEWED/APPROVED stage would
    invent an unapproved workflow. This mirrors the established
    "DRAFT -> POSTED (+ optional CANCELLED)" 2-3 stage pattern used by
    every other document type in this codebase. `FINALIZE_PAYROLL` is
    its own separate permission from `RUN_PAYROLL`/`REVIEW_PAYROLL`
    (§48), so a tenant COULD still enforce "different person finalizes"
    via role assignment even without a hard-coded review gate.

    §37/OD-023: uniqueness for "one active run per period" is enforced
    at the SERVICE layer (checking for an existing non-REVERSED run
    before creating a new one), not a blind DB unique constraint —
    `REVERSED` runs must coexist with the NEW run that supersedes them
    for the same period (the correction workflow).
    """

    __tablename__ = "payroll_run"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    payroll_period_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_period.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=DRAFT)
    employee_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_gross: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    total_net: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accounting_posting_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reversal_of_payroll_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payroll_run.id"), nullable=True
    )
