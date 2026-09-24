import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin


class ChartOfAccount(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Chart of Accounts (PROMPT-025 §9) — a tenant-scoped, EDITABLE
    default FMCG-oriented account list (§56 OD-001/OD-002: not an
    approved final COA, a documented starting point). Lazily seeded per
    tenant on first accounting posting attempt, the same "ensure
    default X exists" pattern `InventoryService.ensure_default_location()`
    already established.

    `is_system_default` marks the seeded rows so a future "reset to
    defaults" or "prevent deleting a mapped account" UI affordance can
    distinguish them from tenant-added accounts — no such affordance is
    built in this prompt (accounts are read-only via the API here).
    """

    __tablename__ = "chart_of_account"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
