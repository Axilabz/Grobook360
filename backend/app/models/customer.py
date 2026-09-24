import uuid
from decimal import Decimal

from sqlalchemy import CHAR, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class Customer(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Customer master (Data Dictionary: customer, domain MASTER; PROMPT-007).

    Columns beyond id/tenant_id/customer_code/name/gstin/state_code/address/
    phone/credit_limit/payment_terms_days/balance/status are proposed schema
    additions for FR-CUST-01/02 not yet reflected in Data Dictionary v3.0 —
    see migration 0008's docstring and PROMPT-007-NOTES.md.

    `balance` is a reconciliation cache column, not a create/update input of
    this module — see app/services/customers/customer_service.py.
    """

    __tablename__ = "customer"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    customer_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    gstin: Mapped[str | None] = mapped_column(CHAR(15), nullable=True)
    state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(6), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gps_location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
