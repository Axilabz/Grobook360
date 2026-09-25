import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

CLASSIC = "CLASSIC"
MODERN = "MODERN"
COMPACT = "COMPACT"
TEMPLATE_IDS = frozenset({CLASSIC, MODERN, COMPACT})


class InvoiceTemplateConfiguration(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Tenant-scoped Sales Invoice print/preview appearance configuration
    (Configuration Center prompt) — ONE ROW PER TENANT, lazily
    provisioned the first time it's requested (mirrors
    `IntegrationConfiguration`'s own identical pattern).

    `template_id` selects from a small, fixed, code-level set of layouts
    (see migration 0032's own module docstring for why this is not an
    extensible DB-driven template catalog). Colors are always validated
    `#RRGGBB` hex (DB CHECK constraint + schema-level validation).

    `logo_data_uri` stores the business logo inline as a data URI rather
    than a filesystem/object-storage path — no upload/static-serving
    infrastructure exists elsewhere in this codebase; size is capped by
    `ConfigurationService` before it ever reaches this column.

    This configuration is read live by the Sales Invoice print view —
    an already-issued invoice re-renders with whatever this row
    currently holds, NOT a snapshot from when it was issued. That is a
    known, documented gap against a "historical invoices must never
    change" requirement — flagged, not silently resolved (no template-
    versioning/document-snapshot table exists in this pass).
    """

    __tablename__ = "invoice_template_configuration"

    tenant_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True)

    template_id: Mapped[str] = mapped_column(String(20), nullable=False, default=CLASSIC)
    primary_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#2563EB")
    secondary_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#0F172A")
    accent_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#10B981")
    text_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#111827")
    table_header_color: Mapped[str] = mapped_column(String(7), nullable=False, default="#E5E7EB")

    logo_data_uri: Mapped[str | None] = mapped_column(Text, nullable=True)

    show_logo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_business_address: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_gstin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_customer_gstin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_hsn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_discount: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_tax_breakup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_bank_details: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    show_terms: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_amount_in_words: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_round_off: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    terms_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bank_account_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bank_account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_ifsc: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bank_upi_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
