"""Attendance service (PROMPT-029 §13/§14)."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import check_row_version
from app.core.error_codes import PAYROLL_ATTENDANCE_INVALID
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.attendance import ATTENDANCE_STATUSES, Attendance
from app.services.audit.audit_service import AuditService


class AttendanceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_attendance(
        self, *, tenant_id: uuid.UUID, employee_id: uuid.UUID | None, date_from: date | None, date_to: date | None, status_filter: str | None,
    ) -> list[Attendance]:
        conditions = [Attendance.tenant_id == tenant_id]
        if employee_id is not None:
            conditions.append(Attendance.employee_id == employee_id)
        if date_from is not None:
            conditions.append(Attendance.attendance_date >= date_from)
        if date_to is not None:
            conditions.append(Attendance.attendance_date <= date_to)
        if status_filter:
            conditions.append(Attendance.status == status_filter)
        result = await self._session.execute(select(Attendance).where(*conditions).order_by(Attendance.attendance_date.desc()))
        return list(result.scalars().all())

    async def get_for_employee_period(self, tenant_id: uuid.UUID, employee_id: uuid.UUID, date_from: date, date_to: date) -> list[Attendance]:
        result = await self._session.execute(
            select(Attendance).where(Attendance.tenant_id == tenant_id, Attendance.employee_id == employee_id, Attendance.attendance_date.between(date_from, date_to))
        )
        return list(result.scalars().all())

    async def record_attendance(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, employee_id: uuid.UUID, attendance_date: date,
        status: str, notes: str | None, ip_address: str | None,
    ) -> Attendance:
        if status not in ATTENDANCE_STATUSES:
            raise ValidationAppError(f"Invalid attendance status '{status}'.", code=PAYROLL_ATTENDANCE_INVALID)

        existing = await self._session.execute(
            select(Attendance).where(Attendance.tenant_id == tenant_id, Attendance.employee_id == employee_id, Attendance.attendance_date == attendance_date)
        )
        record = existing.scalar_one_or_none()
        if record is not None:
            record.status = status
            record.notes = notes
            record.updated_by = actor_user_id
            record.row_version += 1
            await self._session.flush()
            action = "ATTENDANCE_UPDATED"
        else:
            record = Attendance(
                tenant_id=tenant_id, employee_id=employee_id, attendance_date=attendance_date, status=status, notes=notes,
                created_by=actor_user_id, updated_by=actor_user_id,
            )
            self._session.add(record)
            try:
                await self._session.flush()
            except IntegrityError:
                raise ConflictError("Attendance for this employee/date was already recorded.", code=PAYROLL_ATTENDANCE_INVALID)
            action = "ATTENDANCE_CREATED"

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action=action, entity_type="attendance", entity_id=record.id,
            after={"employee_id": str(employee_id), "attendance_date": attendance_date.isoformat(), "status": status}, ip_address=ip_address,
        )
        return record

    async def update_attendance(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, attendance_id: uuid.UUID, expected_row_version: int,
        status: str, notes: str | None, ip_address: str | None,
    ) -> Attendance:
        if status not in ATTENDANCE_STATUSES:
            raise ValidationAppError(f"Invalid attendance status '{status}'.", code=PAYROLL_ATTENDANCE_INVALID)
        result = await self._session.execute(select(Attendance).where(Attendance.id == attendance_id, Attendance.tenant_id == tenant_id).with_for_update())
        record = result.scalar_one_or_none()
        if record is None:
            raise NotFoundError("Attendance record not found", code=PAYROLL_ATTENDANCE_INVALID)
        check_row_version(record, expected_row_version)
        before = {"status": record.status}
        record.status = status
        record.notes = notes
        record.updated_by = actor_user_id
        record.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="ATTENDANCE_UPDATED", entity_type="attendance",
            entity_id=record.id, before=before, after={"status": status}, ip_address=ip_address,
        )
        return record
