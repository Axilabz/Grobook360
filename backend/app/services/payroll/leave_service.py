"""Leave service (PROMPT-029 §15/§16) — deliberately basic, not a full
HRMS leave system."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import PAYROLL_LEAVE_INVALID
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.leave_request import APPROVED, LEAVE_STATUSES, LEAVE_TYPES, PENDING, REJECTED, LeaveRequest
from app.services.audit.audit_service import AuditService


class LeaveService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_leaves(
        self, *, tenant_id: uuid.UUID, employee_id: uuid.UUID | None, status_filter: str | None,
    ) -> list[LeaveRequest]:
        conditions = [LeaveRequest.tenant_id == tenant_id]
        if employee_id is not None:
            conditions.append(LeaveRequest.employee_id == employee_id)
        if status_filter:
            conditions.append(LeaveRequest.status == status_filter)
        result = await self._session.execute(select(LeaveRequest).where(*conditions).order_by(LeaveRequest.from_date.desc()))
        return list(result.scalars().all())

    async def get_for_employee_period(self, tenant_id: uuid.UUID, employee_id: uuid.UUID, date_from: date, date_to: date) -> list[LeaveRequest]:
        result = await self._session.execute(
            select(LeaveRequest).where(
                LeaveRequest.tenant_id == tenant_id, LeaveRequest.employee_id == employee_id,
                LeaveRequest.from_date <= date_to, LeaveRequest.to_date >= date_from,
            )
        )
        return list(result.scalars().all())

    async def create_leave(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, employee_id: uuid.UUID, leave_type: str,
        from_date: date, to_date: date, reason: str | None, ip_address: str | None,
    ) -> LeaveRequest:
        if leave_type not in LEAVE_TYPES:
            raise ValidationAppError(f"Invalid leave_type '{leave_type}'.", code=PAYROLL_LEAVE_INVALID)
        if to_date < from_date:
            raise ValidationAppError("to_date must not be before from_date.", code=PAYROLL_LEAVE_INVALID)

        days = Decimal((to_date - from_date).days + 1).quantize(Decimal("0.01"))
        leave = LeaveRequest(
            tenant_id=tenant_id, employee_id=employee_id, leave_type=leave_type, from_date=from_date, to_date=to_date,
            days=days, status=PENDING, reason=reason, created_by=actor_user_id, updated_by=actor_user_id,
        )
        self._session.add(leave)
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="LEAVE_CREATED", entity_type="leave_request", entity_id=leave.id,
            after={"employee_id": str(employee_id), "leave_type": leave_type, "from_date": from_date.isoformat(), "to_date": to_date.isoformat(), "days": str(days)},
            ip_address=ip_address,
        )
        return leave

    async def _get_locked(self, tenant_id: uuid.UUID, leave_id: uuid.UUID) -> LeaveRequest:
        result = await self._session.execute(select(LeaveRequest).where(LeaveRequest.id == leave_id, LeaveRequest.tenant_id == tenant_id).with_for_update())
        leave = result.scalar_one_or_none()
        if leave is None:
            raise NotFoundError("Leave request not found", code=PAYROLL_LEAVE_INVALID)
        return leave

    async def approve_leave(self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, leave_id: uuid.UUID, ip_address: str | None) -> LeaveRequest:
        leave = await self._get_locked(tenant_id, leave_id)
        if leave.status != PENDING:
            raise ValidationAppError(f"Cannot approve a leave request in {leave.status} status.", code=PAYROLL_LEAVE_INVALID)
        leave.status = APPROVED
        leave.approved_by = actor_user_id
        leave.approved_at = datetime.now(timezone.utc)
        leave.updated_by = actor_user_id
        leave.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="LEAVE_APPROVED", entity_type="leave_request",
            entity_id=leave.id, before={"status": PENDING}, after={"status": APPROVED}, ip_address=ip_address,
        )
        return leave

    async def reject_leave(self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, leave_id: uuid.UUID, ip_address: str | None) -> LeaveRequest:
        leave = await self._get_locked(tenant_id, leave_id)
        if leave.status != PENDING:
            raise ValidationAppError(f"Cannot reject a leave request in {leave.status} status.", code=PAYROLL_LEAVE_INVALID)
        leave.status = REJECTED
        leave.approved_by = actor_user_id
        leave.approved_at = datetime.now(timezone.utc)
        leave.updated_by = actor_user_id
        leave.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="LEAVE_REJECTED", entity_type="leave_request",
            entity_id=leave.id, before={"status": PENDING}, after={"status": REJECTED}, ip_address=ip_address,
        )
        return leave
