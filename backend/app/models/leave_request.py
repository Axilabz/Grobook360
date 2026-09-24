import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

PAID = "PAID"
UNPAID = "UNPAID"
LEAVE_TYPES = frozenset({PAID, UNPAID})

PENDING = "PENDING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
LEAVE_STATUSES = frozenset({PENDING, APPROVED, REJECTED})


class LeaveRequest(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Leave record (PROMPT-029 §15/§16) — deliberately basic, NOT a
    full HRMS leave system (§15's own explicit instruction). §16/OD-020:
    the approval workflow is a single PENDING->APPROVED/REJECTED step,
    gated by the `leave.approve` permission — no multi-level approval
    chain exists.
    """

    __tablename__ = "leave_request"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=False)
    leave_type: Mapped[str] = mapped_column(String(10), nullable=False)
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PENDING)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
