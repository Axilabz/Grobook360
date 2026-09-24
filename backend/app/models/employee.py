import uuid
from datetime import date

from sqlalchemy import CHAR, Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

# §5: baseline lifecycle statuses (kept deliberately small — OD-005 stays
# open on whether this is the final/complete set).
ACTIVE = "ACTIVE"
INACTIVE = "INACTIVE"
ON_NOTICE = "ON_NOTICE"
EXITED = "EXITED"
EMPLOYEE_STATUSES = frozenset({ACTIVE, INACTIVE, ON_NOTICE, EXITED})

# §4/OD-004: a proposed, non-final employment type taxonomy — no approved
# source defines the exact list.
FULL_TIME = "FULL_TIME"
PART_TIME = "PART_TIME"
CONTRACT = "CONTRACT"
EMPLOYMENT_TYPES = frozenset({FULL_TIME, PART_TIME, CONTRACT})


class Employee(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Employee Master (PROMPT-029 §4) — a "propose, document, implement"
    addition, no equivalent table exists in the Data Dictionary baseline.

    §7/OD-002: `user_id` is an OPTIONAL, nullable link to `user.id` — an
    Employee is NOT assumed to be an application login user. §6/OD-003:
    `employee_code` is server-authoritative (`DocumentNumberingService.
    next_number_no_fy`, format `EMP-000001`, never resets — unlike every
    GST/financial document number, an employee code must never repeat
    even across financial years). §8/OD-006: `department`/`designation`
    are free-text fields, not separate master tables (no approved
    Department/Designation master exists — OD-006/OD-007 stay open).
    §40/OD-009: bank fields are optional, plain columns — no automated
    bank transfer exists anywhere in this codebase (§40's own explicit
    prohibition), they exist only for payslip/manual-payment reference.
    """

    __tablename__ = "employee"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    employee_code: Mapped[str] = mapped_column(String(20), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    mobile: Mapped[str | None] = mapped_column(String(15), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_of_joining: Mapped[date] = mapped_column(Date, nullable=False)
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    designation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employment_type: Mapped[str] = mapped_column(String(20), nullable=False, default=FULL_TIME)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ACTIVE)
    reporting_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user.id"), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bank_account_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    bank_ifsc: Mapped[str | None] = mapped_column(CHAR(11), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
