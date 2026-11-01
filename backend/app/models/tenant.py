import uuid

from sqlalchemy import CHAR, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, RowVersionMixin, UUIDPKMixin, utcnow
from sqlalchemy import DateTime


class Tenant(UUIDPKMixin, Base, RowVersionMixin):
    """Tenant / organization root (Data Dictionary: tenant, domain TENANCY).

    NOTE on created_by/updated_by: the Data Dictionary marks these NOT NULL with an
    FK to user.id, but that is circular for the very first tenant (no user exists
    yet to create it). ERD v2.0 S3 footnote explicitly carves out this exact case
    ("created_by/updated_by may be nullable only where creation can occur before a
    user exists, e.g. initial Tenant bootstrap"). Resolved here as NULLABLE per the
    ERD's explicit bootstrap exception, not silently — see PROMPT-001 response notes.
    """

    __tablename__ = "tenant"

    # System-generated, platform-wide, never reuses a number — see
    # migration 0036's docstring. Display-only; the UUID `id` remains the
    # real foreign-key/tenant-isolation identifier everywhere.
    # The random `default=` below is only a fallback for the many existing
    # test fixtures that construct `Tenant(business_name=...)` directly
    # without a code; the real sign-up flow (SignUpService) always passes
    # an explicit clean sequential "TEN-0001"-style code, overriding this.
    tenant_code: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, default=lambda: f"TEN-{uuid.uuid4().hex[:8].upper()}"
    )
    business_name: Mapped[str] = mapped_column(String(200), nullable=False)
    gstin: Mapped[str | None] = mapped_column(CHAR(15), nullable=True)
    state_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    financial_year_start_month: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=4)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")

    # Proposed schema addition (PROMPT-002 — see PROMPT-002-NOTES.md): the Data
    # Dictionary v3.0 tenant table has no address columns at all, but PROMPT-002 S7
    # explicitly requires capturing organization Address/City/PIN Code at sign-up.
    # Rather than silently collecting and discarding that data, these three
    # nullable columns are added, documented, and migrated (0003).
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pin_code: Mapped[str | None] = mapped_column(CHAR(6), nullable=True)

    # Company Profile fields (migration 0033 — see that migration's own
    # docstring for the "propose, document, implement" rationale). All
    # nullable: no sign-up flow captures any of these today.
    pan: Mapped[str | None] = mapped_column(CHAR(10), nullable=True)
    business_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column(CHAR(10), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    bank_account_holder_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bank_ifsc: Mapped[str | None] = mapped_column(CHAR(11), nullable=True)
    bank_branch_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bank_upi_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
