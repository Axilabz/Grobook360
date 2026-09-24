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

    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
