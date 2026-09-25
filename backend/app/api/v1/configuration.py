"""Configuration Center — Invoice Template Configuration endpoints.

Deliberately narrow: `GET/PUT invoice-template-config` and
`POST/DELETE business-logo`. `tenant_id` always comes from the
authenticated session context, never from a client-supplied field
(§1's own explicit requirement) — every endpoint below reads it via
`_require_tenant`, the same pattern every other router in this
codebase uses.
"""

import uuid

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.exceptions import AuthorizationError
from app.core.permissions import CONFIGURATION_MANAGE, CONFIGURATION_VIEW
from app.db.session import get_db_session
from app.models.invoice_template_configuration import InvoiceTemplateConfiguration
from app.schemas.configuration import InvoiceTemplateConfigRequest
from app.services.configuration.configuration_service import ConfigurationService

router = APIRouter(prefix="/configuration", tags=["configuration"])


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


def _to_response(config: InvoiceTemplateConfiguration) -> dict:
    return {
        "id": str(config.id),
        "template_id": config.template_id,
        "primary_color": config.primary_color,
        "secondary_color": config.secondary_color,
        "accent_color": config.accent_color,
        "text_color": config.text_color,
        "table_header_color": config.table_header_color,
        "logo_data_uri": config.logo_data_uri,
        "show_logo": config.show_logo,
        "show_business_address": config.show_business_address,
        "show_gstin": config.show_gstin,
        "show_customer_gstin": config.show_customer_gstin,
        "show_hsn": config.show_hsn,
        "show_discount": config.show_discount,
        "show_tax_breakup": config.show_tax_breakup,
        "show_bank_details": config.show_bank_details,
        "show_terms": config.show_terms,
        "show_amount_in_words": config.show_amount_in_words,
        "show_round_off": config.show_round_off,
        "terms_text": config.terms_text,
        "bank_name": config.bank_name,
        "bank_account_name": config.bank_account_name,
        "bank_account_number": config.bank_account_number,
        "bank_ifsc": config.bank_ifsc,
        "bank_upi_id": config.bank_upi_id,
        "row_version": config.row_version,
    }


def _meta() -> dict:
    return {"correlation_id": get_correlation_id()}


@router.get("/invoice-template-config")
async def get_invoice_template_config(
    context: AuthenticatedContext = Depends(require_permission(CONFIGURATION_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    config = await ConfigurationService(session).get_or_create(tenant_id=tenant_id, actor_user_id=context.user_id)
    await session.commit()
    return {"data": _to_response(config), "meta": _meta()}


@router.put("/invoice-template-config")
async def update_invoice_template_config(
    request: Request, payload: InvoiceTemplateConfigRequest,
    context: AuthenticatedContext = Depends(require_permission(CONFIGURATION_MANAGE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"
    config = await ConfigurationService(session).update(
        tenant_id=tenant_id, actor_user_id=context.user_id, payload=payload, ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_response(config), "meta": _meta()}


@router.post("/business-logo")
async def upload_business_logo(
    request: Request, file: UploadFile = File(...),
    context: AuthenticatedContext = Depends(require_permission(CONFIGURATION_MANAGE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"
    raw_bytes = await file.read()
    config = await ConfigurationService(session).upload_logo(
        tenant_id=tenant_id, actor_user_id=context.user_id, content_type=file.content_type or "",
        raw_bytes=raw_bytes, ip_address=client_ip,
    )
    await session.commit()
    return {"data": _to_response(config), "meta": _meta()}


@router.delete("/business-logo")
async def remove_business_logo(
    request: Request,
    context: AuthenticatedContext = Depends(require_permission(CONFIGURATION_MANAGE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    client_ip = request.client.host if request.client else "unknown"
    config = await ConfigurationService(session).remove_logo(tenant_id=tenant_id, actor_user_id=context.user_id, ip_address=client_ip)
    await session.commit()
    return {"data": _to_response(config), "meta": _meta()}
