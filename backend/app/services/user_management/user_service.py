"""Tenant User Management (PROMPT-005; authorization migrated to permission
codes by PROMPT-006).

Authorization is enforced by the router (require_permission) before these
methods run; this service assumes the caller is already authorized and
focuses on tenant scoping, uniqueness, owner protection, and concurrency.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta, timezone, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import check_row_version
from app.core.config import get_settings
from app.core.error_codes import (
    USR_DUPLICATE_IDENTIFIER,
    USR_INVALID_ROLE,
    USR_NOT_FOUND,
    USR_OWNER_PROTECTION,
)
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import generate_reset_token, hash_password, hash_reset_token
from app.db.base import utcnow
from app.models.auth_session import AuthSession
from app.models.password_reset_token import PasswordResetToken
from app.models.role import Role
from app.models.user import User
from app.models.user_role import UserRole
from app.schemas.user_management import ASSIGNABLE_ROLES
from app.services.audit.audit_service import AuditService
from app.services.password_recovery.provider import get_recovery_provider
from app.services.rbac.permission_service import seed_role_permissions


@dataclass(frozen=True)
class UserPage:
    items: list[tuple[User, str | None]]  # (user, role_name)
    total_items: int


class UserManagementService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _role_name_for(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
        result = await self._session.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, UserRole.tenant_id == tenant_id)
        )
        return result.scalars().first()

    async def _get_or_create_role(self, tenant_id: uuid.UUID, name: str) -> Role:
        result = await self._session.execute(select(Role).where(Role.tenant_id == tenant_id, Role.name == name))
        role = result.scalar_one_or_none()
        if role is None:
            role = Role(tenant_id=tenant_id, name=name)
            self._session.add(role)
            await self._session.flush()
            # PROMPT-006: seed this tenant's first-ever row for this role name
            # with its default permission set (formalizing what PROMPT-005
            # already enforced via role checks).
            await seed_role_permissions(self._session, tenant_id=tenant_id, role_id=role.id, role_name=name)
        return role

    async def _active_owner_count(self, tenant_id: uuid.UUID, *, excluding_user_id: uuid.UUID | None = None) -> int:
        stmt = (
            select(func.count(User.id))
            .select_from(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(User.tenant_id == tenant_id, User.status == "ACTIVE", Role.name == "OWNER")
        )
        if excluding_user_id is not None:
            stmt = stmt.where(User.id != excluding_user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def list_users(
        self,
        *,
        tenant_id: uuid.UUID,
        page: int,
        page_size: int,
        search: str | None,
        role_filter: str | None,
        status_filter: str | None,
    ) -> UserPage:
        base = select(User, Role.name).outerjoin(UserRole, UserRole.user_id == User.id).outerjoin(
            Role, Role.id == UserRole.role_id
        ).where(User.tenant_id == tenant_id)

        if search:
            like = f"%{search}%"
            base = base.where(or_(User.name.ilike(like), User.email.ilike(like), User.phone.ilike(like)))
        if status_filter:
            base = base.where(User.status == status_filter)
        if role_filter:
            base = base.where(Role.name == role_filter)

        count_stmt = select(func.count()).select_from(base.subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        return UserPage(items=[(row[0], row[1]) for row in rows], total_items=total_items)

    async def get_user(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> tuple[User, str | None]:
        result = await self._session.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
        user = result.scalar_one_or_none()
        if user is None:
            # Same message whether the user_id doesn't exist at all or belongs
            # to another tenant — cross-tenant lookups must not be
            # distinguishable from "not found" (PROMPT-005 S26/S42.6-9).
            raise NotFoundError("User not found", code=USR_NOT_FOUND)
        role_name = await self._role_name_for(tenant_id, user.id)
        return user, role_name

    async def _check_duplicate_phone(self, tenant_id: uuid.UUID, phone: str, *, exclude_user_id: uuid.UUID | None = None) -> None:
        settings = get_settings()
        stmt = select(User).where(User.phone == phone)
        if settings.phone_uniqueness_scope == "tenant":
            stmt = stmt.where(User.tenant_id == tenant_id)
        if exclude_user_id is not None:
            stmt = stmt.where(User.id != exclude_user_id)
        existing = (await self._session.execute(stmt)).scalars().first()
        if existing is not None:
            raise ConflictError("A user with this login identifier already exists.", code=USR_DUPLICATE_IDENTIFIER)

    async def create_user(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        name: str,
        phone: str,
        email: str,
        role: str,
        ip_address: str | None,
    ) -> tuple[User, str | None]:
        if role not in ASSIGNABLE_ROLES:
            raise ConflictError("Invalid role", code=USR_INVALID_ROLE)

        await self._check_duplicate_phone(tenant_id, phone)

        # PROMPT-005 S11/S23: no admin-known password. A random, never-revealed
        # value is hashed and stored; the new user must set their own password
        # via the existing PROMPT-004 reset flow before they can ever log in —
        # reusing established infrastructure rather than inventing a new one.
        unusable_password = generate_reset_token()
        new_user = User(
            tenant_id=tenant_id,
            name=name,
            phone=phone,
            email=email,
            password_hash=hash_password(unusable_password),
            status="ACTIVE",
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(new_user)
        await self._session.flush()

        role_row = await self._get_or_create_role(tenant_id, role)
        self._session.add(
            UserRole(tenant_id=tenant_id, user_id=new_user.id, role_id=role_row.id, created_by=actor_user_id, updated_by=actor_user_id)
        )

        # Issue an initial password-reset token (same mechanism as PROMPT-004).
        settings = get_settings()
        raw_token = generate_reset_token()
        self._session.add(
            PasswordResetToken(
                tenant_id=tenant_id,
                user_id=new_user.id,
                token_hash=hash_reset_token(raw_token),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.password_reset_token_expire_minutes),
                created_by=actor_user_id,
                updated_by=actor_user_id,
            )
        )
        await self._session.flush()

        reset_link = f"{settings.frontend_base_url}/reset-password?token={raw_token}"
        provider = get_recovery_provider(is_production=settings.is_production)
        try:
            await provider.send_reset_link(to_email=email, reset_link=reset_link)
        except Exception:
            pass  # delivery failure must not block user creation (PROMPT-004 S29 precedent)

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="USER_CREATED",
            entity_type="user",
            entity_id=new_user.id,
            after={"name": name, "phone": phone, "email": email, "role": role},
            ip_address=ip_address,
        )

        return new_user, role

    async def update_user(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str | None,
        email: str | None,
        role: str | None,
        expected_row_version: int,
        ip_address: str | None,
    ) -> tuple[User, str | None]:
        user, current_role = await self.get_user(tenant_id=tenant_id, user_id=user_id)
        check_row_version(user, expected_row_version)

        before: dict = {"name": user.name, "email": user.email, "role": current_role}

        if role is not None and role != current_role:
            if role not in ASSIGNABLE_ROLES:
                raise ConflictError("Invalid role", code=USR_INVALID_ROLE)
            # Owner protection (PROMPT-005 S16/S24 recommended baseline, followed
            # verbatim since no other approved source defines it): moving the
            # last active Owner away from OWNER is rejected.
            if current_role == "OWNER" and user.status == "ACTIVE":
                remaining = await self._active_owner_count(tenant_id, excluding_user_id=user.id)
                if remaining == 0:
                    raise ConflictError(
                        "This tenant must always have at least one active Owner.", code=USR_OWNER_PROTECTION
                    )
            await self._session.execute(
                UserRole.__table__.delete().where(UserRole.user_id == user.id, UserRole.tenant_id == tenant_id)
            )
            new_role_row = await self._get_or_create_role(tenant_id, role)
            self._session.add(
                UserRole(tenant_id=tenant_id, user_id=user.id, role_id=new_role_row.id, created_by=actor_user_id, updated_by=actor_user_id)
            )
            current_role = role

        if name is not None:
            user.name = name
        if email is not None:
            user.email = email

        user.updated_by = actor_user_id
        user.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="USER_UPDATED",
            entity_type="user",
            entity_id=user.id,
            before=before,
            after={"name": user.name, "email": user.email, "role": current_role},
            ip_address=ip_address,
        )

        return user, current_role

    async def _set_status(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        user_id: uuid.UUID,
        new_status: str,
        expected_row_version: int,
        ip_address: str | None,
    ) -> tuple[User, str | None]:
        user, role_name = await self.get_user(tenant_id=tenant_id, user_id=user_id)
        check_row_version(user, expected_row_version)

        if new_status == "INACTIVE" and role_name == "OWNER" and user.status == "ACTIVE":
            remaining = await self._active_owner_count(tenant_id, excluding_user_id=user.id)
            if remaining == 0:
                raise ConflictError(
                    "This tenant must always have at least one active Owner.", code=USR_OWNER_PROTECTION
                )

        previous_status = user.status
        user.status = new_status
        user.updated_by = actor_user_id
        user.row_version += 1
        await self._session.flush()

        if new_status == "INACTIVE":
            # PROMPT-005 S18/S22: deactivation must not let an existing session
            # keep working — revoke every active session for this user.
            sessions = await self._session.execute(
                select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            )
            for session_row in sessions.scalars().all():
                session_row.revoked_at = utcnow()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="USER_ACTIVATED" if new_status == "ACTIVE" else "USER_DEACTIVATED",
            entity_type="user",
            entity_id=user.id,
            before={"status": previous_status},
            after={"status": new_status},
            ip_address=ip_address,
        )

        return user, role_name

    async def activate_user(self, **kwargs) -> tuple[User, str | None]:
        return await self._set_status(new_status="ACTIVE", **kwargs)

    async def deactivate_user(self, **kwargs) -> tuple[User, str | None]:
        return await self._set_status(new_status="INACTIVE", **kwargs)
