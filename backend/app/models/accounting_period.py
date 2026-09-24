import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

OPEN = "OPEN"
CLOSED = "CLOSED"
PERIOD_STATUSES = frozenset({OPEN, CLOSED})


class AccountingPeriod(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Accounting period guard (PROMPT-025 §35) — one row per tenant per
    financial year (`financial_year_label`, same "{start}-{end}" format
    `DocumentNumberingService.get_financial_year_label` already
    produces). Lazily created OPEN the first time a journal is posted
    into that year. §56 OD-018/OD-019: no close/reopen workflow or API
    exists in this prompt — this table only supports the POSTING GUARD
    ("reject posting into a closed period"), not a full period-close
    business process. A period can currently never become CLOSED through
    any implemented code path; the column exists so the guard is real
    and a future prompt can add the close workflow without a schema
    change.
    """

    __tablename__ = "accounting_period"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    financial_year_label: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=OPEN)
