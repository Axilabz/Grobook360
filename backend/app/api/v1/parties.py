"""Party 360 Profile endpoint — reusable for BOTH Customer and Supplier
(§32/§47 "one architecture, not two" mandate). `party_type` in the URL
is validated against a closed allowlist and drives which existing
`customers.view`/`suppliers.view` permission is checked dynamically —
mirrors the established `credit_debit_notes.py` per-request permission
pattern (PROMPT-017), since a single static `Depends(require_permission
(...))` can't express "the required permission depends on a path
segment". `tenant_id` always comes from the authenticated session
context, never from the URL or a client-supplied field (§38).
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, get_current_user
from app.core.exceptions import AuthorizationError, ValidationAppError
from app.core.permissions import CUSTOMERS_VIEW, SUPPLIERS_VIEW
from app.db.session import get_db_session
from app.services.parties.party_profile_service import CUSTOMER, PARTY_TYPES, SUPPLIER, PartyProfileService

router = APIRouter(prefix="/parties", tags=["parties"])

_PERMISSION_BY_PARTY_TYPE = {CUSTOMER: CUSTOMERS_VIEW, SUPPLIER: SUPPLIERS_VIEW}


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


def _jsonify(value):
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonify(v) for v in value]
    if hasattr(value, "__float__") and not isinstance(value, (int, float, bool)):
        return str(value)
    return value


@router.get("/{party_type}/{party_id}")
async def get_party_profile(
    party_type: str, party_id: uuid.UUID,
    context: AuthenticatedContext = Depends(get_current_user), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    if party_type not in PARTY_TYPES:
        raise ValidationAppError(f"Unknown party type '{party_type}'. Must be one of: {', '.join(sorted(PARTY_TYPES))}.")

    required_permission = _PERMISSION_BY_PARTY_TYPE[party_type]
    if required_permission not in context.permissions:
        raise AuthorizationError(f"Missing required permission: {required_permission}")

    data = await PartyProfileService(session).get_profile(tenant_id=tenant_id, party_type=party_type, party_id=party_id)
    return {"data": _jsonify(data), "meta": {"correlation_id": get_correlation_id()}}
