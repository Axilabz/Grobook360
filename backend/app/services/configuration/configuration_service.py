"""Invoice Template Configuration service (Configuration Center prompt).

`get_or_create` lazily provisions the tenant's single configuration row
on first access — the same pattern `IntegrationConfiguration`/
`InventoryService.ensure_default_location()` already use elsewhere in
this codebase, rather than a separate signup-time provisioning step.
"""

import base64
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import check_row_version
from app.core.error_codes import CONFIG_INVALID_LOGO, CONFIG_LOGO_TOO_LARGE
from app.core.exceptions import ValidationAppError
from app.models.invoice_template_configuration import InvoiceTemplateConfiguration
from app.schemas.configuration import InvoiceTemplateConfigRequest
from app.services.audit.audit_service import AuditService

_ALLOWED_LOGO_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_MAX_LOGO_BYTES = 500 * 1024  # 500KB — stored inline as a data URI, see model's own docstring.

_CONFIG_FIELDS = (
    "template_id", "primary_color", "secondary_color", "accent_color", "text_color", "table_header_color",
    "show_logo", "show_business_address", "show_gstin", "show_customer_gstin", "show_hsn", "show_discount",
    "show_tax_breakup", "show_bank_details", "show_terms", "show_amount_in_words", "show_round_off",
    "terms_text", "bank_name", "bank_account_name", "bank_account_number", "bank_ifsc", "bank_upi_id",
)


def _snapshot(config: InvoiceTemplateConfiguration) -> dict:
    # Never include logo_data_uri in an audit snapshot — it's large and
    # not secret, but it's also not meaningful audit content; presence
    # is enough (§30 "never store secrets", applied conservatively to
    # "never store large binary blobs" too).
    return {field: getattr(config, field) for field in _CONFIG_FIELDS} | {"has_logo": config.logo_data_uri is not None}


class ConfigurationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID | None) -> InvoiceTemplateConfiguration:
        result = await self._session.execute(
            select(InvoiceTemplateConfiguration).where(InvoiceTemplateConfiguration.tenant_id == tenant_id)
        )
        config = result.scalar_one_or_none()
        if config is not None:
            return config

        config = InvoiceTemplateConfiguration(tenant_id=tenant_id, created_by=actor_user_id, updated_by=actor_user_id)
        self._session.add(config)
        await self._session.flush()
        return config

    async def update(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, payload: InvoiceTemplateConfigRequest, ip_address: str | None,
    ) -> InvoiceTemplateConfiguration:
        config = await self.get_or_create(tenant_id=tenant_id, actor_user_id=actor_user_id)
        check_row_version(config, payload.expected_row_version)

        before = _snapshot(config)

        for field in _CONFIG_FIELDS:
            setattr(config, field, getattr(payload, field))
        config.updated_by = actor_user_id
        config.row_version += 1

        after = _snapshot(config)
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="INVOICE_TEMPLATE_CONFIG_UPDATED",
            entity_type="invoice_template_configuration", entity_id=config.id, before=before, after=after, ip_address=ip_address,
        )
        return config

    async def upload_logo(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, content_type: str, raw_bytes: bytes, ip_address: str | None,
    ) -> InvoiceTemplateConfiguration:
        if content_type not in _ALLOWED_LOGO_TYPES:
            raise ValidationAppError(
                f"Unsupported logo file type '{content_type}'. Use PNG, JPEG, or WebP.", code=CONFIG_INVALID_LOGO,
            )
        if len(raw_bytes) > _MAX_LOGO_BYTES:
            raise ValidationAppError(f"Logo file exceeds the {_MAX_LOGO_BYTES // 1024}KB limit.", code=CONFIG_LOGO_TOO_LARGE)
        if len(raw_bytes) == 0:
            raise ValidationAppError("Logo file is empty.", code=CONFIG_INVALID_LOGO)

        config = await self.get_or_create(tenant_id=tenant_id, actor_user_id=actor_user_id)
        had_logo_before = config.logo_data_uri is not None

        encoded = base64.b64encode(raw_bytes).decode("ascii")
        config.logo_data_uri = f"data:{content_type};base64,{encoded}"
        config.updated_by = actor_user_id
        config.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id,
            action="INVOICE_TEMPLATE_LOGO_REPLACED" if had_logo_before else "INVOICE_TEMPLATE_LOGO_UPLOADED",
            entity_type="invoice_template_configuration", entity_id=config.id,
            before={"has_logo": had_logo_before}, after={"has_logo": True}, ip_address=ip_address,
        )
        return config

    async def remove_logo(self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, ip_address: str | None) -> InvoiceTemplateConfiguration:
        config = await self.get_or_create(tenant_id=tenant_id, actor_user_id=actor_user_id)
        had_logo_before = config.logo_data_uri is not None
        config.logo_data_uri = None
        config.updated_by = actor_user_id
        config.row_version += 1
        await self._session.flush()

        if had_logo_before:
            await AuditService(self._session).record(
                tenant_id=tenant_id, actor_user_id=actor_user_id, action="INVOICE_TEMPLATE_LOGO_REMOVED",
                entity_type="invoice_template_configuration", entity_id=config.id,
                before={"has_logo": True}, after={"has_logo": False}, ip_address=ip_address,
            )
        return config
