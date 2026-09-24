"""Forgot-password / reset-password endpoints (PROMPT-004).

Not in API Contract Specification v1.0's catalogue (written before password
recovery was scoped) — added per this prompt's own instruction, matching how
PROMPT-002 added /auth/sign-up. See PROMPT-004-NOTES.md.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.correlation import get_correlation_id
from app.core.error_codes import RESET_RATE_LIMITED
from app.core.rate_limit import check_rate_limit
from app.db.session import get_db_session
from app.schemas.password_reset import ForgotPasswordRequest, ResetPasswordRequest, ValidateResetTokenRequest
from app.services.auth.password_reset_service import PasswordResetService, ResetTokenError
from app.services.password_recovery.provider import get_recovery_provider

router = APIRouter(tags=["auth"])

_GENERIC_FORGOT_PASSWORD_MESSAGE = (
    "If an account matches the information provided, recovery instructions will be sent."
)


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/auth/forgot-password")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"

    # Two independent limiters (S20): per-IP (blunt abuse) and per-identifier
    # (targeted spam against one account), same documented-placeholder pattern
    # as PROMPT-002/003's rate limits — thresholds are configuration, not
    # silently invented. Both use the SAME generic message (S8): the
    # rate-limit response must not distinguish real vs. unknown accounts.
    check_rate_limit(
        f"forgot-password-ip:{client_ip}",
        settings.password_reset_rate_limit_per_ip_per_hour,
        message=_GENERIC_FORGOT_PASSWORD_MESSAGE,
        code=RESET_RATE_LIMITED,
    )
    check_rate_limit(
        f"forgot-password-id:{payload.recovery_identifier}",
        settings.password_reset_identifier_rate_limit_per_hour,
        message=_GENERIC_FORGOT_PASSWORD_MESSAGE,
        code=RESET_RATE_LIMITED,
    )

    reset_service = PasswordResetService(session)
    pending = await reset_service.request_reset(email=payload.recovery_identifier, ip_address=client_ip)

    if pending is not None:
        reset_link = f"{settings.frontend_base_url}/reset-password?token={pending.raw_token}"
        provider = get_recovery_provider(is_production=settings.is_production)
        try:
            await provider.send_reset_link(to_email=pending.user.email, reset_link=reset_link)
        except Exception:
            # S29: delivery failure must never surface provider details, and
            # must not change the anti-enumeration response shape.
            pass

    await session.commit()

    return {"data": {"message": _GENERIC_FORGOT_PASSWORD_MESSAGE}, "meta": _meta()}


@router.post("/auth/reset-password/validate")
async def validate_reset_token(
    payload: ValidateResetTokenRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    reset_service = PasswordResetService(session)
    is_valid = await reset_service.validate_token(payload.token)
    return {"data": {"valid": is_valid}, "meta": _meta()}


@router.post("/auth/reset-password")
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(f"reset-password-ip:{client_ip}", settings.password_reset_rate_limit_per_ip_per_hour)

    reset_service = PasswordResetService(session)
    try:
        await reset_service.reset_password(
            raw_token=payload.token, new_password=payload.new_password, ip_address=client_ip
        )
    except ResetTokenError:
        await session.commit()  # persist the AUTH_PASSWORD_RESET_TOKEN_* audit record
        raise

    await session.commit()

    return {"data": {"status": "PASSWORD_RESET"}, "meta": _meta()}
