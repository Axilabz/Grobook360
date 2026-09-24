import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class UUIDPKMixin:
    """Immutable UUID primary key. Never reused."""

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class AuditColumnsMixin:
    """Standard audit columns mandated on every persistent table (ERD v2.0 S3).

    created_by / updated_by are nullable at the ORM level because tenant bootstrap
    and system-generated rows may not yet have an actor user (ERD v2.0 S3 footnote).
    Ordinary tenant business tables should enforce NOT NULL at the table level once
    that business table is implemented.
    """

    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class RowVersionMixin:
    """Optimistic concurrency column. Starts at 1; increments on mutable update."""

    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
