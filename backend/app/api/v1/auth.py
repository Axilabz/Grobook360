"""Sign-up (PROMPT-002) and Sign-In/session endpoints (PROMPT-003).

Sign-up: not in API Contract Specification v1.0's endpoint catalogue (S5.3
lists only login/logout/refresh/me/session-status) — added per PROMPT-002's
own instruction. See PROMPT-002-NOTES.md.

Login/logout/me/session-status ARE in the approved API Contract catalogue
(API-AUTH-001/002/004/005). /auth/refresh (API-AUTH-003) is deliberately NOT
implemented — PROMPT-003's session/token architecture decision keeps
PROMPT-001's single 60-minute JWT with no refresh token; see
PROMPT-003-NOTES.md.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, get_current_user
from app.core.error_codes import AUTH_ACCOUNT_LOCKED, REG_MISSING_FIELD, REG_TENANT_CREATION_FAILURE
from app.core.exceptions import AppError, AuthenticationError, BadRequestError, ConflictError, RateLimitedError
from app.core.login_lockout import clear as clear_lockout
from app.core.login_lockout import is_locked, record_failure
from app.core.rate_limit import check_rate_limit
from app.core.security import decode_access_token
from app.db.session import get_db_session
from app.models.tenant import Tenant
from app.schemas.auth import LoginRequest, LoginResponseData, MeResponseData, TenantSummary, UserSummary
from app.schemas.signup import SignUpRequest, SignUpResult
from app.services.auth.auth_service import AuthService
from app.services.auth.session_service import SessionService
from app.services.gst.provider import get_gst_provider
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.signup.signup_service import SignUpService

router = APIRouter(tags=["auth"])

_ENDPOINT_NAME = "POST /api/v1/auth/sign-up"


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/auth/sign-up", status_code=201)
async def sign_up(
    request: Request,
    payload: SignUpRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    settings = get_settings()

    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(client_ip, settings.signup_rate_limit_per_ip_per_hour)

    if not idempotency_key:
        raise BadRequestError(
            "Idempotency-Key header is required for sign-up", code=REG_MISSING_FIELD
        )

    request_payload = payload.model_dump(mode="json")
    idempotency = IdempotencyService(session)

    check_result = await idempotency.check_signup(idempotency_key=idempotency_key, payload=request_payload)
    if check_result.existing_response is not None:
        _, body = check_result.existing_response
        return body

    signup_service = SignUpService(session, get_gst_provider())

    try:
        tenant, owner_user = await signup_service.create_tenant_and_owner(
            payload, phone_uniqueness_scope=settings.phone_uniqueness_scope
        )
    except ConflictError:
        await session.rollback()
        raise
    except Exception as exc:
        await session.rollback()
        raise ConflictError(
            "Tenant registration could not be completed", code=REG_TENANT_CREATION_FAILURE
        ) from exc

    result = SignUpResult(tenant_id=str(tenant.id), owner_user_id=str(owner_user.id), status="CREATED")
    response_body = {"data": result.model_dump(), "meta": _meta()}

    await idempotency.store(
        idempotency_key=idempotency_key,
        endpoint=_ENDPOINT_NAME,
        payload=request_payload,
        tenant_id=tenant.id,
        response_status=201,
        response_body=response_body,
    )

    await session.commit()

    return response_body


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite=settings.auth_cookie_samesite,
        max_age=settings.jwt_access_token_expire_minutes * 60,
        path="/",
    )


@router.post("/auth/login")
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"

    check_rate_limit(f"login:{client_ip}", settings.login_rate_limit_per_ip_per_hour)

    if is_locked(
        payload.login_identifier,
        threshold=settings.login_lockout_threshold,
        duration_minutes=settings.login_lockout_duration_minutes,
    ):
        raise RateLimitedError(
            "Too many failed attempts. Please try again later.", code=AUTH_ACCOUNT_LOCKED
        )

    auth_service = AuthService(session)
    device_info = request.headers.get("user-agent")

    try:
        result = await auth_service.authenticate(
            phone=payload.login_identifier,
            password=payload.password,
            ip_address=client_ip,
            device_info=device_info,
        )
    except AuthenticationError:
        record_failure(payload.login_identifier)
        await session.commit()  # persist the LOGIN_FAILED audit record
        raise
    except AppError:
        await session.commit()  # persist the LOGIN_FAILED (inactive account) audit record
        raise

    clear_lockout(payload.login_identifier)
    _set_session_cookie(response, result.token)
    await session.commit()

    data = LoginResponseData(
        user=UserSummary(
            id=str(result.user.id), phone=result.user.phone, email=result.user.email, role=result.role_name
        ),
        tenant=TenantSummary(
            id=str(result.tenant.id), tenant_code=result.tenant.tenant_code, business_name=result.tenant.business_name
        )
        if result.tenant
        else None,
        permissions=result.permissions,
    )
    return {"data": data.model_dump(), "meta": _meta()}


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    context: AuthenticatedContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    settings = get_settings()
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1]

    if token:
        claims = decode_access_token(token)
        if claims and claims.get("jti"):
            await SessionService(session).revoke(uuid.UUID(claims["jti"]))

    response.delete_cookie(key=settings.auth_cookie_name, path="/")
    await session.commit()
    return Response(status_code=204)


@router.get("/auth/me")
async def me(
    context: AuthenticatedContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_summary = None
    if context.tenant_id is not None:
        tenant = await session.get(Tenant, context.tenant_id)
        if tenant is not None:
            tenant_summary = TenantSummary(id=str(tenant.id), tenant_code=tenant.tenant_code, business_name=tenant.business_name)

    data = MeResponseData(
        user_id=str(context.user_id),
        tenant_id=str(context.tenant_id) if context.tenant_id else None,
        tenant=tenant_summary,
        role=context.role,
        permissions=list(context.permissions),
    )
    return {"data": data.model_dump(), "meta": _meta()}


@router.get("/auth/session-status")
async def session_status(context: AuthenticatedContext = Depends(get_current_user)) -> dict:
    return {
        "data": {"authenticated": True, "role": context.role},
        "meta": _meta(),
    }
