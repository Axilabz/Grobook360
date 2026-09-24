import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

EARNING = "EARNING"
DEDUCTION = "DEDUCTION"
COMPONENT_TYPES = frozenset({EARNING, DEDUCTION})

FIXED_AMOUNT = "FIXED_AMOUNT"
PERCENTAGE = "PERCENTAGE"
CALCULATION_TYPES = frozenset({FIXED_AMOUNT, PERCENTAGE})


class SalaryComponent(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Salary Component catalogue (PROMPT-029 §9/§10, §56 OD-010/OD-011)
    — a tenant-editable master, mirroring `ChartOfAccount`'s own
    lazily-seeded, per-tenant-editable pattern (PROMPT-025) rather than a
    fixed global enum. NO statutory component type exists (§9's own
    explicit "do not introduce statutory component types" — PF/ESI/TDS
    are never valid `code` values here by policy, not by a DB
    constraint, since the catalogue is free-text/tenant-editable).
    """

    __tablename__ = "salary_component"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    component_type: Mapped[str] = mapped_column(String(20), nullable=False)
    default_calculation_type: Mapped[str] = mapped_column(String(20), nullable=False, default=FIXED_AMOUNT)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
