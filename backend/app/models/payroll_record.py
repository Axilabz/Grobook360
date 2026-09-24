import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class PayrollRecord(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Payroll Record (PROMPT-029 §28/§30) — the per-employee, per-run
    IMMUTABLE snapshot. This IS the "payslip" (§30/§31) — `payslip_
    number` lives directly on this row rather than a separate `payslip`
    table, since a payslip has no independent lifecycle of its own; it
    is always exactly this snapshot rendered for display.

    §28's own explicit list is captured here as snapshot columns
    (never a live join back to `Employee`/`SalaryStructure` for
    historical display — those can change after the fact; this row
    never does, §29 immutability): `employee_code_snapshot`, `employee_
    name_snapshot`, `designation_snapshot` freeze what the payslip shows
    even if the employee's own master record changes later.
    """

    __tablename__ = "payroll_record"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    payroll_run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_run.id"), nullable=False, index=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=False)
    employee_code_snapshot: Mapped[str] = mapped_column(String(20), nullable=False)
    employee_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    designation_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    salary_structure_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("salary_structure.id"), nullable=True)
    calendar_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    working_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    present_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    paid_leave_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    unpaid_leave_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    payable_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    gross_earnings: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    net_salary: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    payslip_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    reversal_of_payroll_record_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payroll_record.id"), nullable=True
    )
