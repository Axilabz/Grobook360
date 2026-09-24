import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

PRESENT = "PRESENT"
ABSENT = "ABSENT"
HALF_DAY = "HALF_DAY"
LEAVE = "LEAVE"
HOLIDAY = "HOLIDAY"
WEEK_OFF = "WEEK_OFF"
ATTENDANCE_STATUSES = frozenset({PRESENT, ABSENT, HALF_DAY, LEAVE, HOLIDAY, WEEK_OFF})


class Attendance(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Daily Attendance (PROMPT-029 §13/§14) — one row per employee per
    calendar date. §14's own explicit exclusion: no geo/GPS/biometric/
    face-recognition capture exists — `status` is manually recorded.

    A `status=LEAVE` row does NOT by itself say whether the leave is
    PAID or UNPAID — the payroll calculation engine cross-references the
    `leave_request` table for that date (an APPROVED row of type PAID
    counts as paid; anything else defaults conservatively to unpaid —
    see `payroll_calculation_service.py`'s own module docstring, OD-018).
    """

    __tablename__ = "attendance"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=False)
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
