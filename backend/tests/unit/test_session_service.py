"""AUTH-API-017 (expired session) — unit-tested directly since waiting out a
real 60-minute token expiry isn't practical in an automated test.
"""

import uuid
from datetime import datetime, timedelta, timezone

from app.db.base import utcnow
from app.models.auth_session import AuthSession
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth.session_service import SessionService


async def _make_user(db_session) -> User:
    tenant = Tenant(business_name="Session Test Co")
    db_session.add(tenant)
    await db_session.flush()
    user = User(tenant_id=tenant.id, email="x@example.com", phone="9111111111", password_hash="hash", status="ACTIVE")
    db_session.add(user)
    await db_session.flush()
    return user


async def test_expired_session_is_not_active(db_session):
    user = await _make_user(db_session)
    jti = uuid.uuid4()
    record = AuthSession(
        tenant_id=user.tenant_id,
        user_id=user.id,
        token_jti=jti,
        issued_at=utcnow() - timedelta(hours=2),
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # already expired
    )
    db_session.add(record)
    await db_session.flush()

    service = SessionService(db_session)
    active = await service.get_active(jti)
    assert active is None


async def test_revoked_session_is_not_active(db_session):
    user = await _make_user(db_session)
    jti = uuid.uuid4()
    record = AuthSession(
        tenant_id=user.tenant_id,
        user_id=user.id,
        token_jti=jti,
        issued_at=utcnow(),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(record)
    await db_session.flush()

    service = SessionService(db_session)
    assert await service.revoke(jti) is True
    assert await service.get_active(jti) is None
    assert await service.revoke(jti) is False  # already revoked — idempotent-safe


async def test_valid_session_is_active(db_session):
    user = await _make_user(db_session)
    jti = uuid.uuid4()
    record = AuthSession(
        tenant_id=user.tenant_id,
        user_id=user.id,
        token_jti=jti,
        issued_at=utcnow(),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(record)
    await db_session.flush()

    service = SessionService(db_session)
    active = await service.get_active(jti)
    assert active is not None
    assert active.id == record.id
