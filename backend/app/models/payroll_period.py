import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

OPEN = "OPEN"
PROCESSING = "PROCESSING"
PROCESSED = "PROCESSED"
FINALIZED = "FINALIZED"
CLOSED = "CLOSED"
PAYROLL_PERIOD_STATUSES = frozenset({OPEN, PROCESSING, PROCESSED, FINALIZED, CLOSED})


class PayrollPeriod(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Payroll Period (PROMPT-029 §18/§56) — e.g. "2026-04" / 01-Apr-2026
    to 30-Apr-2026. §56/OD-022: no automatic period-close workflow
    exists (mirrors `accounting_period`'s own PROMPT-025 precedent — a
    guard/label only); `status` is advanced by `PayrollRunService` as
    its own run progresses (OPEN when created, PROCESSING while a run is
    being calculated, FINALIZED once a run finalizes) rather than by any
    separate period-management endpoint.
    """

    __tablename__ = "payroll_period"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    period_label: Mapped[str] = mapped_column(String(10), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=OPEN)
