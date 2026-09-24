import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class PayrollRecordLine(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Payroll Record line (PROMPT-029 §28) — one earning or deduction
    component within a `PayrollRecord` snapshot. `component_code`/
    `component_name` are copied verbatim from `SalaryComponent` at
    calculation time (never a live FK join for historical display,
    mirroring `PayrollRecord`'s own snapshot discipline) so a later
    rename/deactivation of the component never alters a historical
    payslip.
    """

    __tablename__ = "payroll_record_line"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    payroll_record_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payroll_record.id"), nullable=False, index=True)
    component_type: Mapped[str] = mapped_column(String(20), nullable=False)
    component_code: Mapped[str] = mapped_column(String(30), nullable=False)
    component_name: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
