import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class DocumentNumberSequence(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Server-authoritative document numbering counter (PROMPT-011).

    Proposed schema addition — not in Data Dictionary v3.0 (no generic
    Sales document table exists there either; each future document-type
    prompt owns its own header table, but they all need the SAME
    numbering mechanism). §34/§35: final GST/financial document numbers
    must be server-authoritative, never client-generated — this table is
    what makes that possible, scoped per tenant + document type +
    financial year, matching the FY-specific numbering pattern common to
    Indian GST document sequences.
    """

    __tablename__ = "document_number_sequence"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(String(20), nullable=False)
    financial_year_label: Mapped[str] = mapped_column(String(10), nullable=False)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
