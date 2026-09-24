import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class SalaryStructure(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Salary Structure header (PROMPT-029 §8/§11/§12).

    Effective-dated (`effective_from`) with NO explicit `effective_to`
    column — §12's "prevent overlapping effective periods" is resolved
    by construction rather than by managing a second date: the structure
    APPLICABLE for any given payroll date is always "the one with the
    latest `effective_from` <= that date" (identical resolution
    technique to `SalesInvoiceService`'s snapshot-at-creation-time
    discipline). A unique `(tenant_id, employee_id, effective_from)`
    constraint prevents two structures claiming the exact same start
    date; genuine overlap simply cannot occur without an end date to
    overlap against. §11: once payroll for a period has been calculated
    against a structure, a LATER structure (a later `effective_from`)
    never changes that already-calculated payroll — the payroll snapshot
    (`payroll_record`) is what's authoritative for history, never a
    live join back to this table.
    """

    __tablename__ = "salary_structure"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
