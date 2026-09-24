import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class SalaryStructureLine(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Salary Structure line (PROMPT-029 §9/§10/§12) — one component
    within a `SalaryStructure`.

    §10/§12 (OD-011/OD-012): `calculation_type` is either `FIXED_AMOUNT`
    (`amount` used verbatim) or `PERCENTAGE` (`percentage` applied to
    ANOTHER line's resolved amount within the SAME structure, named by
    `percentage_of_component_code` — e.g. HRA at 40% of Basic resolves
    `percentage_of_component_code='BASIC'`). No arbitrary formula/
    scripting engine exists (§10's own explicit prohibition, OD-013
    stays open) — percentage-of-another-component is the only supported
    non-fixed calculation.
    """

    __tablename__ = "salary_structure_line"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    salary_structure_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("salary_structure.id"), nullable=False, index=True
    )
    component_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("salary_component.id"), nullable=False)
    calculation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    percentage_of_component_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
