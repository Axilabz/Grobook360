import uuid
from decimal import Decimal

from sqlalchemy import CHAR, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class Supplier(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Supplier master (Data Dictionary: supplier, domain MASTER; PROMPT-008).

    Columns beyond id/tenant_id/supplier_code/name/gstin/state_code/address/
    phone/credit_terms_days/balance/status are proposed schema additions for
    FR-SUPP-01 not yet reflected in Data Dictionary v3.0 — see migration
    0009's docstring and PROMPT-008-NOTES.md.

    Deliberately has NO region/gps_location/credit_limit columns (FR-SUPP-02
    explicitly excludes them for Supplier) and NO bank-account fields
    (ERD-DEC-04 leaves the BankAccount master unresolved upstream).

    `balance` is a reconciliation cache column, not a create/update input of
    this module — see app/services/suppliers/supplier_service.py.
    """

    __tablename__ = "supplier"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    supplier_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_person: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    gstin: Mapped[str | None] = mapped_column(CHAR(15), nullable=True)
    state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(6), nullable=True)
    credit_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
