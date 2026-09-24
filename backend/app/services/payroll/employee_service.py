"""Employee Master service (PROMPT-029 §4-§7).

Mirrors `CustomerService`'s own shape. `employee_code` is server-
authoritative via `DocumentNumberingService.next_number_no_fy` (§6 —
never a client-generated code, and unlike every GST/financial document
number, it must NEVER reset across financial years).
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import check_row_version
from app.core.error_codes import PAYROLL_EMPLOYEE_NOT_FOUND
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.employee import ACTIVE, EMPLOYEE_STATUSES, EMPLOYMENT_TYPES, INACTIVE, Employee
from app.models.tenant import Tenant
from app.services.audit.audit_service import AuditService
from app.services.sales.document_numbering_service import DocumentNumberingService

EMPLOYEE = "EMPLOYEE"


@dataclass(frozen=True)
class EmployeePage:
    items: list[Employee]
    total_items: int


def _snapshot(employee: Employee) -> dict:
    return {
        "employee_code": employee.employee_code, "full_name": employee.full_name, "mobile": employee.mobile,
        "email": employee.email, "date_of_joining": employee.date_of_joining.isoformat(),
        "exit_date": employee.exit_date.isoformat() if employee.exit_date else None,
        "department": employee.department, "designation": employee.designation,
        "employment_type": employee.employment_type, "status": employee.status,
    }


class EmployeeService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_employees(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, search: str | None, status_filter: str | None,
        department: str | None, designation: str | None, employment_type: str | None,
    ) -> EmployeePage:
        conditions = [Employee.tenant_id == tenant_id]
        if search:
            like = f"%{search}%"
            conditions.append(or_(Employee.full_name.ilike(like), Employee.employee_code.ilike(like)))
        if status_filter:
            conditions.append(Employee.status == status_filter)
        if department:
            conditions.append(Employee.department == department)
        if designation:
            conditions.append(Employee.designation == designation)
        if employment_type:
            conditions.append(Employee.employment_type == employment_type)

        count_stmt = select(func.count()).select_from(select(Employee.id).where(*conditions).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = select(Employee).where(*conditions).order_by(Employee.full_name).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).scalars().all()
        return EmployeePage(items=list(rows), total_items=total_items)

    async def get_employee(self, tenant_id: uuid.UUID, employee_id: uuid.UUID) -> Employee:
        result = await self._session.execute(select(Employee).where(Employee.id == employee_id, Employee.tenant_id == tenant_id))
        employee = result.scalar_one_or_none()
        if employee is None:
            raise NotFoundError("Employee not found", code=PAYROLL_EMPLOYEE_NOT_FOUND)
        return employee

    async def get_employee_locked(self, tenant_id: uuid.UUID, employee_id: uuid.UUID) -> Employee:
        result = await self._session.execute(
            select(Employee).where(Employee.id == employee_id, Employee.tenant_id == tenant_id).with_for_update()
        )
        employee = result.scalar_one_or_none()
        if employee is None:
            raise NotFoundError("Employee not found", code=PAYROLL_EMPLOYEE_NOT_FOUND)
        return employee

    async def create_employee(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, full_name: str, mobile: str | None, email: str | None,
        date_of_joining: date, department: str | None, designation: str | None, employment_type: str,
        reporting_manager_id: uuid.UUID | None, address: str | None, bank_account_number: str | None,
        bank_ifsc: str | None, bank_name: str | None, ip_address: str | None,
    ) -> Employee:
        if employment_type not in EMPLOYMENT_TYPES:
            raise ValidationAppError(f"Invalid employment_type '{employment_type}'.", code=PAYROLL_EMPLOYEE_NOT_FOUND)

        tenant_result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = tenant_result.scalar_one()
        numbering = DocumentNumberingService(self._session)
        employee_code = await numbering.next_number_no_fy(tenant=tenant, document_type=EMPLOYEE, prefix="EMP")

        employee = Employee(
            tenant_id=tenant_id, employee_code=employee_code, full_name=full_name, mobile=mobile, email=email,
            date_of_joining=date_of_joining, department=department, designation=designation, employment_type=employment_type,
            status=ACTIVE, reporting_manager_id=reporting_manager_id, address=address,
            bank_account_number=bank_account_number, bank_ifsc=bank_ifsc, bank_name=bank_name,
            created_by=actor_user_id, updated_by=actor_user_id,
        )
        self._session.add(employee)
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="EMPLOYEE_CREATED",
            entity_type="employee", entity_id=employee.id, after=_snapshot(employee), ip_address=ip_address,
        )
        return employee

    async def update_employee(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, employee_id: uuid.UUID, expected_row_version: int,
        ip_address: str | None, **fields,
    ) -> Employee:
        employee = await self.get_employee_locked(tenant_id, employee_id)
        check_row_version(employee, expected_row_version)
        before = _snapshot(employee)

        for key, value in fields.items():
            if value is not None and hasattr(employee, key):
                setattr(employee, key, value)
        employee.updated_by = actor_user_id
        employee.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="EMPLOYEE_UPDATED",
            entity_type="employee", entity_id=employee.id, before=before, after=_snapshot(employee), ip_address=ip_address,
        )
        return employee

    async def set_status(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, employee_id: uuid.UUID, expected_row_version: int,
        new_status: str, exit_date: date | None, ip_address: str | None,
    ) -> Employee:
        if new_status not in EMPLOYEE_STATUSES:
            raise ValidationAppError(f"Invalid employee status '{new_status}'.", code=PAYROLL_EMPLOYEE_NOT_FOUND)
        employee = await self.get_employee_locked(tenant_id, employee_id)
        check_row_version(employee, expected_row_version)
        previous_status = employee.status

        employee.status = new_status
        if exit_date is not None:
            employee.exit_date = exit_date
        employee.updated_by = actor_user_id
        employee.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id,
            action="EMPLOYEE_DEACTIVATED" if new_status in (INACTIVE, "EXITED") else "EMPLOYEE_STATUS_CHANGED",
            entity_type="employee", entity_id=employee.id, before={"status": previous_status},
            after={"status": new_status, "exit_date": employee.exit_date.isoformat() if employee.exit_date else None},
            ip_address=ip_address,
        )
        return employee
