"""Employee, Payroll & Basic Salary Management endpoints (PROMPT-029
§51). Payroll Run creation and finalization are the duplicate-
submission-sensitive operations (mirrors `sales_invoices.py`'s own
`_idempotent_post` pattern) and require an `Idempotency-Key`.
"""

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.error_codes import REG_MISSING_FIELD
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import (
    ATTENDANCE_MANAGE,
    ATTENDANCE_VIEW,
    EMPLOYEES_CREATE,
    EMPLOYEES_DEACTIVATE,
    EMPLOYEES_EDIT,
    EMPLOYEES_VIEW,
    LEAVE_APPROVE,
    LEAVE_MANAGE,
    LEAVE_VIEW,
    PAYROLL_FINALIZE,
    PAYROLL_RUN,
    PAYROLL_VIEW,
    PAYROLL_VIEW_PAYSLIP,
    SALARY_MANAGE,
    SALARY_VIEW,
)
from app.db.session import get_db_session
from app.models.attendance import Attendance
from app.models.employee import Employee
from app.models.leave_request import LeaveRequest
from app.models.payroll_period import PayrollPeriod
from app.models.payroll_record import PayrollRecord
from app.models.payroll_run import PayrollRun
from app.models.salary_component import SalaryComponent
from app.models.salary_structure import SalaryStructure
from app.models.salary_structure_line import SalaryStructureLine
from app.schemas.envelopes import Pagination
from app.schemas.payroll import (
    AttendanceItem,
    CreateEmployeeRequest,
    CreateLeaveRequest,
    CreatePayrollPeriodRequest,
    CreatePayrollRunRequest,
    CreateSalaryStructureRequest,
    EmployeeDetail,
    EmployeeListItem,
    LeaveItem,
    PayrollPeriodItem,
    PayrollRecordItem,
    PayrollRecordLineItem,
    PayrollRunItem,
    PayslipDetail,
    RecordAttendanceRequest,
    SalaryComponentItem,
    SalaryStructureDetail,
    SalaryStructureLineItem,
    SetEmployeeStatusRequest,
    UpdateAttendanceRequest,
    UpdateEmployeeRequest,
)
from app.services.idempotency.idempotency_service import IdempotencyService
from app.services.payroll.attendance_service import AttendanceService
from app.services.payroll.employee_service import EmployeeService
from app.services.payroll.leave_service import LeaveService
from app.services.payroll.payroll_run_service import PayrollRunService
from app.services.payroll.salary_service import SalaryComponentService, SalaryStructureLineInputDTO, SalaryStructureService

router = APIRouter(tags=["payroll"])


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


async def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise BadRequestError("Idempotency-Key header is required for this operation", code=REG_MISSING_FIELD)
    return idempotency_key


async def _idempotent_post(*, session, idempotency_key: str, endpoint: str, tenant_id: uuid.UUID, request_payload: dict, execute, response_status: int = 201) -> dict:
    idempotency = IdempotencyService(session)
    check_result = await idempotency.check(idempotency_key=idempotency_key, endpoint=endpoint, payload=request_payload)
    if check_result.existing_response is not None:
        _, body = check_result.existing_response
        return body
    response_body = await execute()
    await idempotency.store(idempotency_key=idempotency_key, endpoint=endpoint, payload=request_payload, tenant_id=tenant_id, response_status=response_status, response_body=response_body)
    return response_body


def _employee_list_item(e: Employee) -> EmployeeListItem:
    return EmployeeListItem(
        id=str(e.id), employee_code=e.employee_code, full_name=e.full_name, designation=e.designation, department=e.department,
        date_of_joining=e.date_of_joining.isoformat(), exit_date=e.exit_date.isoformat() if e.exit_date else None,
        employment_type=e.employment_type, status=e.status, row_version=e.row_version,
    )


def _employee_detail(e: Employee) -> EmployeeDetail:
    return EmployeeDetail(**_employee_list_item(e).model_dump(), mobile=e.mobile, email=e.email, reporting_manager_id=str(e.reporting_manager_id) if e.reporting_manager_id else None,
                           address=e.address, bank_account_number=e.bank_account_number, bank_ifsc=e.bank_ifsc, bank_name=e.bank_name)


# --- Employees --------------------------------------------------------------


@router.get("/employees")
async def list_employees(
    page: int = 1, page_size: int = 25, search: str | None = None, status: str | None = None, department: str | None = None,
    designation: str | None = None, employment_type: str | None = None,
    context: AuthenticatedContext = Depends(require_permission(EMPLOYEES_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)
    result = await EmployeeService(session).list_employees(
        tenant_id=tenant_id, page=page, page_size=page_size, search=search, status_filter=status, department=department, designation=designation, employment_type=employment_type,
    )
    total_pages = (result.total_items + page_size - 1) // page_size if result.total_items else 0
    return {
        "data": [_employee_list_item(e).model_dump() for e in result.items],
        "pagination": Pagination(page=page, page_size=page_size, total_items=result.total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/employees/{employee_id}")
async def get_employee(employee_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(EMPLOYEES_VIEW)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    employee = await EmployeeService(session).get_employee(tenant_id, employee_id)
    return {"data": _employee_detail(employee).model_dump(), "meta": _meta()}


@router.post("/employees", status_code=201)
async def create_employee(
    request: Request, payload: CreateEmployeeRequest,
    context: AuthenticatedContext = Depends(require_permission(EMPLOYEES_CREATE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    employee = await EmployeeService(session).create_employee(
        tenant_id=tenant_id, actor_user_id=context.user_id, full_name=payload.full_name, mobile=payload.mobile, email=payload.email,
        date_of_joining=payload.date_of_joining, department=payload.department, designation=payload.designation, employment_type=payload.employment_type,
        reporting_manager_id=uuid.UUID(payload.reporting_manager_id) if payload.reporting_manager_id else None, address=payload.address,
        bank_account_number=payload.bank_account_number, bank_ifsc=payload.bank_ifsc, bank_name=payload.bank_name,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    return {"data": _employee_detail(employee).model_dump(), "meta": _meta()}


@router.put("/employees/{employee_id}")
async def update_employee(
    request: Request, employee_id: uuid.UUID, payload: UpdateEmployeeRequest,
    context: AuthenticatedContext = Depends(require_permission(EMPLOYEES_EDIT)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    fields = payload.model_dump(exclude={"expected_row_version", "reporting_manager_id"}, exclude_unset=True)
    if payload.reporting_manager_id is not None:
        fields["reporting_manager_id"] = uuid.UUID(payload.reporting_manager_id)
    employee = await EmployeeService(session).update_employee(
        tenant_id=tenant_id, actor_user_id=context.user_id, employee_id=employee_id, expected_row_version=payload.expected_row_version,
        ip_address=request.client.host if request.client else "unknown", **fields,
    )
    await session.commit()
    return {"data": _employee_detail(employee).model_dump(), "meta": _meta()}


@router.post("/employees/{employee_id}/deactivate")
async def deactivate_employee(
    request: Request, employee_id: uuid.UUID, payload: SetEmployeeStatusRequest,
    context: AuthenticatedContext = Depends(require_permission(EMPLOYEES_DEACTIVATE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    employee = await EmployeeService(session).set_status(
        tenant_id=tenant_id, actor_user_id=context.user_id, employee_id=employee_id, expected_row_version=payload.expected_row_version,
        new_status=payload.status, exit_date=payload.exit_date, ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    return {"data": _employee_detail(employee).model_dump(), "meta": _meta()}


# --- Salary -------------------------------------------------------------------


@router.get("/salary-components")
async def list_salary_components(context: AuthenticatedContext = Depends(require_permission(SALARY_VIEW)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    components = await SalaryComponentService(session).list_components(tenant_id)
    await session.commit()
    items = [SalaryComponentItem(id=str(c.id), code=c.code, name=c.name, component_type=c.component_type, default_calculation_type=c.default_calculation_type, is_active=c.is_active).model_dump() for c in components]
    return {"data": items, "meta": _meta()}


def _structure_detail(structure: SalaryStructure, lines: list[tuple[SalaryStructureLine, SalaryComponent]]) -> SalaryStructureDetail:
    return SalaryStructureDetail(
        id=str(structure.id), employee_id=str(structure.employee_id), effective_from=structure.effective_from.isoformat(), row_version=structure.row_version,
        lines=[
            SalaryStructureLineItem(
                id=str(line.id), component_id=str(component.id), component_code=component.code, component_name=component.name,
                component_type=component.component_type, calculation_type=line.calculation_type, amount=str(line.amount),
                percentage=str(line.percentage) if line.percentage is not None else None, percentage_of_component_code=line.percentage_of_component_code,
            )
            for line, component in lines
        ],
    )


@router.post("/employees/{employee_id}/salary-structures", status_code=201)
async def create_salary_structure(
    request: Request, employee_id: uuid.UUID, payload: CreateSalaryStructureRequest,
    context: AuthenticatedContext = Depends(require_permission(SALARY_MANAGE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = SalaryStructureService(session)
    line_inputs = [
        SalaryStructureLineInputDTO(component_id=uuid.UUID(line.component_id), calculation_type=line.calculation_type, amount=line.amount, percentage=line.percentage, percentage_of_component_code=line.percentage_of_component_code)
        for line in payload.lines
    ]
    structure = await service.create_structure(
        tenant_id=tenant_id, actor_user_id=context.user_id, employee_id=employee_id, effective_from=payload.effective_from, lines=line_inputs,
        ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    lines = await service.get_lines(structure.id)
    return {"data": _structure_detail(structure, lines).model_dump(), "meta": _meta()}


@router.get("/employees/{employee_id}/salary-structures")
async def list_salary_structures(employee_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(SALARY_VIEW)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    service = SalaryStructureService(session)
    structures = await service.list_structures(tenant_id, employee_id)
    items = []
    for structure in structures:
        lines = await service.get_lines(structure.id)
        items.append(_structure_detail(structure, lines).model_dump())
    return {"data": items, "meta": _meta()}


@router.get("/salary-structures/{structure_id}")
async def get_salary_structure(structure_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(SALARY_VIEW)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    service = SalaryStructureService(session)
    structure = await service.get_structure(tenant_id, structure_id)
    lines = await service.get_lines(structure.id)
    return {"data": _structure_detail(structure, lines).model_dump(), "meta": _meta()}


# --- Attendance -----------------------------------------------------------------


def _attendance_item(a: Attendance) -> AttendanceItem:
    return AttendanceItem(id=str(a.id), employee_id=str(a.employee_id), attendance_date=a.attendance_date.isoformat(), status=a.status, notes=a.notes, row_version=a.row_version)


@router.post("/attendance", status_code=201)
async def record_attendance(
    request: Request, payload: RecordAttendanceRequest,
    context: AuthenticatedContext = Depends(require_permission(ATTENDANCE_MANAGE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    record = await AttendanceService(session).record_attendance(
        tenant_id=tenant_id, actor_user_id=context.user_id, employee_id=uuid.UUID(payload.employee_id), attendance_date=payload.attendance_date,
        status=payload.status, notes=payload.notes, ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    return {"data": _attendance_item(record).model_dump(), "meta": _meta()}


@router.get("/attendance")
async def list_attendance(
    employee_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None, status: str | None = None,
    context: AuthenticatedContext = Depends(require_permission(ATTENDANCE_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    rows = await AttendanceService(session).list_attendance(tenant_id=tenant_id, employee_id=employee_id, date_from=date_from, date_to=date_to, status_filter=status)
    return {"data": [_attendance_item(a).model_dump() for a in rows], "meta": _meta()}


@router.put("/attendance/{attendance_id}")
async def update_attendance(
    request: Request, attendance_id: uuid.UUID, payload: UpdateAttendanceRequest,
    context: AuthenticatedContext = Depends(require_permission(ATTENDANCE_MANAGE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    record = await AttendanceService(session).update_attendance(
        tenant_id=tenant_id, actor_user_id=context.user_id, attendance_id=attendance_id, expected_row_version=payload.expected_row_version,
        status=payload.status, notes=payload.notes, ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    return {"data": _attendance_item(record).model_dump(), "meta": _meta()}


# --- Leave -----------------------------------------------------------------------


def _leave_item(leave_: LeaveRequest) -> LeaveItem:
    return LeaveItem(
        id=str(leave_.id), employee_id=str(leave_.employee_id), leave_type=leave_.leave_type, from_date=leave_.from_date.isoformat(),
        to_date=leave_.to_date.isoformat(), days=str(leave_.days), status=leave_.status, reason=leave_.reason,
        approved_by=str(leave_.approved_by) if leave_.approved_by else None, row_version=leave_.row_version,
    )


@router.post("/leave", status_code=201)
async def create_leave(
    request: Request, payload: CreateLeaveRequest,
    context: AuthenticatedContext = Depends(require_permission(LEAVE_MANAGE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    leave_ = await LeaveService(session).create_leave(
        tenant_id=tenant_id, actor_user_id=context.user_id, employee_id=uuid.UUID(payload.employee_id), leave_type=payload.leave_type,
        from_date=payload.from_date, to_date=payload.to_date, reason=payload.reason, ip_address=request.client.host if request.client else "unknown",
    )
    await session.commit()
    return {"data": _leave_item(leave_).model_dump(), "meta": _meta()}


@router.get("/leave")
async def list_leave(
    employee_id: uuid.UUID | None = None, status: str | None = None,
    context: AuthenticatedContext = Depends(require_permission(LEAVE_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    rows = await LeaveService(session).list_leaves(tenant_id=tenant_id, employee_id=employee_id, status_filter=status)
    return {"data": [_leave_item(l).model_dump() for l in rows], "meta": _meta()}


@router.post("/leave/{leave_id}/approve")
async def approve_leave(request: Request, leave_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(LEAVE_APPROVE)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    leave_ = await LeaveService(session).approve_leave(tenant_id=tenant_id, actor_user_id=context.user_id, leave_id=leave_id, ip_address=request.client.host if request.client else "unknown")
    await session.commit()
    return {"data": _leave_item(leave_).model_dump(), "meta": _meta()}


@router.post("/leave/{leave_id}/reject")
async def reject_leave(request: Request, leave_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(LEAVE_APPROVE)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    leave_ = await LeaveService(session).reject_leave(tenant_id=tenant_id, actor_user_id=context.user_id, leave_id=leave_id, ip_address=request.client.host if request.client else "unknown")
    await session.commit()
    return {"data": _leave_item(leave_).model_dump(), "meta": _meta()}


# --- Payroll Periods / Runs ----------------------------------------------------


def _period_item(p: PayrollPeriod) -> PayrollPeriodItem:
    return PayrollPeriodItem(id=str(p.id), period_label=p.period_label, start_date=p.start_date.isoformat(), end_date=p.end_date.isoformat(), status=p.status)


@router.post("/payroll/periods", status_code=201)
async def create_payroll_period(
    payload: CreatePayrollPeriodRequest, context: AuthenticatedContext = Depends(require_permission(PAYROLL_RUN)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    period = await PayrollRunService(session).get_or_create_period(
        tenant_id=tenant_id, actor_user_id=context.user_id, period_label=payload.period_label, start_date=payload.start_date, end_date=payload.end_date,
    )
    await session.commit()
    return {"data": _period_item(period).model_dump(), "meta": _meta()}


@router.get("/payroll/periods")
async def list_payroll_periods(context: AuthenticatedContext = Depends(require_permission(PAYROLL_VIEW)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    periods = await PayrollRunService(session).list_periods(tenant_id)
    return {"data": [_period_item(p).model_dump() for p in periods], "meta": _meta()}


def _run_item(run: PayrollRun, period_label: str) -> PayrollRunItem:
    return PayrollRunItem(
        id=str(run.id), payroll_period_id=str(run.payroll_period_id), period_label=period_label, status=run.status, employee_count=run.employee_count,
        total_gross=str(run.total_gross), total_deductions=str(run.total_deductions), total_net=str(run.total_net),
        calculated_at=run.calculated_at.isoformat() if run.calculated_at else None, finalized_at=run.finalized_at.isoformat() if run.finalized_at else None,
        accounting_posting_reference=run.accounting_posting_reference, row_version=run.row_version,
    )


async def _period_label_for(session: AsyncSession, period_id: uuid.UUID) -> str:
    from sqlalchemy import select
    result = await session.execute(select(PayrollPeriod.period_label).where(PayrollPeriod.id == period_id))
    return result.scalar_one()


@router.post("/payroll/runs", status_code=201)
async def create_payroll_run(
    payload: CreatePayrollRunRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(PAYROLL_RUN)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    key = await _require_idempotency_key(idempotency_key)

    async def _execute() -> dict:
        run = await PayrollRunService(session).create_run(tenant_id=tenant_id, actor_user_id=context.user_id, payroll_period_id=uuid.UUID(payload.payroll_period_id))
        label = await _period_label_for(session, run.payroll_period_id)
        return {"data": _run_item(run, label).model_dump(), "meta": _meta()}

    response_body = await _idempotent_post(session=session, idempotency_key=key, endpoint="POST /api/v1/payroll/runs", tenant_id=tenant_id, request_payload=payload.model_dump(mode="json"), execute=_execute)
    await session.commit()
    return response_body


@router.get("/payroll/runs")
async def list_payroll_runs(context: AuthenticatedContext = Depends(require_permission(PAYROLL_VIEW)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    runs = await PayrollRunService(session).list_runs(tenant_id)
    items = [_run_item(r, await _period_label_for(session, r.payroll_period_id)).model_dump() for r in runs]
    return {"data": items, "meta": _meta()}


@router.get("/payroll/runs/{run_id}")
async def get_payroll_run(run_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PAYROLL_VIEW)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    run = await PayrollRunService(session).get_run(tenant_id, run_id)
    label = await _period_label_for(session, run.payroll_period_id)
    return {"data": _run_item(run, label).model_dump(), "meta": _meta()}


@router.post("/payroll/runs/{run_id}/calculate")
async def calculate_payroll_run(request: Request, run_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PAYROLL_RUN)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    run = await PayrollRunService(session).calculate_run(tenant_id=tenant_id, actor_user_id=context.user_id, run_id=run_id, ip_address=request.client.host if request.client else "unknown")
    await session.commit()
    label = await _period_label_for(session, run.payroll_period_id)
    return {"data": _run_item(run, label).model_dump(), "meta": _meta()}


@router.post("/payroll/runs/{run_id}/finalize")
async def finalize_payroll_run(
    request: Request, run_id: uuid.UUID, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_permission(PAYROLL_FINALIZE)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    await _require_idempotency_key(idempotency_key)
    run = await PayrollRunService(session).finalize_run(tenant_id=tenant_id, actor_user_id=context.user_id, run_id=run_id, ip_address=request.client.host if request.client else "unknown")
    await session.commit()
    label = await _period_label_for(session, run.payroll_period_id)
    return {"data": _run_item(run, label).model_dump(), "meta": _meta()}


@router.post("/payroll/runs/{run_id}/reverse")
async def reverse_payroll_run(request: Request, run_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PAYROLL_FINALIZE)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    run = await PayrollRunService(session).reverse_run(tenant_id=tenant_id, actor_user_id=context.user_id, run_id=run_id, ip_address=request.client.host if request.client else "unknown")
    await session.commit()
    label = await _period_label_for(session, run.payroll_period_id)
    return {"data": _run_item(run, label).model_dump(), "meta": _meta()}


@router.get("/payroll/runs/{run_id}/records")
async def list_payroll_records(run_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PAYROLL_VIEW)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    records = await PayrollRunService(session).list_records_for_run(tenant_id, run_id)
    return {"data": [_record_item(r).model_dump() for r in records], "meta": _meta()}


def _record_item(r: PayrollRecord) -> PayrollRecordItem:
    return PayrollRecordItem(
        id=str(r.id), payroll_run_id=str(r.payroll_run_id), employee_id=str(r.employee_id), employee_code_snapshot=r.employee_code_snapshot,
        employee_name_snapshot=r.employee_name_snapshot, designation_snapshot=r.designation_snapshot, calendar_days=r.calendar_days,
        working_days=str(r.working_days), present_days=str(r.present_days), paid_leave_days=str(r.paid_leave_days), unpaid_leave_days=str(r.unpaid_leave_days),
        payable_days=str(r.payable_days), gross_earnings=str(r.gross_earnings), total_deductions=str(r.total_deductions), net_salary=str(r.net_salary),
        payslip_number=r.payslip_number, status=r.status,
    )


@router.get("/payroll/{record_id}")
async def get_payroll_record(record_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PAYROLL_VIEW)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    record = await PayrollRunService(session).get_record(tenant_id, record_id)
    return {"data": _record_item(record).model_dump(), "meta": _meta()}


@router.get("/payroll/{record_id}/payslip")
async def get_payslip(record_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PAYROLL_VIEW_PAYSLIP)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    service = PayrollRunService(session)
    record = await service.get_record(tenant_id, record_id)
    lines = await service.get_record_lines(record.id)
    run = await service.get_run(tenant_id, record.payroll_run_id)
    from sqlalchemy import select
    period_result = await session.execute(select(PayrollPeriod).where(PayrollPeriod.id == run.payroll_period_id))
    period = period_result.scalar_one()

    detail = PayslipDetail(
        **_record_item(record).model_dump(), period_label=period.period_label, period_start=period.start_date.isoformat(), period_end=period.end_date.isoformat(),
        lines=[PayrollRecordLineItem(component_type=l.component_type, component_code=l.component_code, component_name=l.component_name, amount=str(l.amount)) for l in lines],
    )
    return {"data": detail.model_dump(), "meta": _meta()}


@router.get("/employees/{employee_id}/payroll-history")
async def get_employee_payroll_history(employee_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(PAYROLL_VIEW)), session: AsyncSession = Depends(get_db_session)) -> dict:
    tenant_id = _require_tenant(context)
    records = await PayrollRunService(session).list_records_for_employee(tenant_id, employee_id)
    return {"data": [_record_item(r).model_dump() for r in records], "meta": _meta()}
