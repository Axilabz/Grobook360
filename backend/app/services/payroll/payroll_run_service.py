"""Payroll Run service (PROMPT-029 §18-§27/§36-§39/§63) — the
orchestrator that ties `payroll_calculation_service.py` (pure
calculation) together with `AccountingPostingService` (journal
creation, PROMPT-025) without duplicating either.

§37/OD-023: "duplicate payroll run" is prevented at the SERVICE layer —
before creating a DRAFT run, any existing NON-REVERSED run for the same
period is returned/blocked rather than a second one created; this is
what also makes the "REVERSE then re-run" correction workflow possible
without a blind DB constraint.

§63: `finalize_run` is the one atomic, all-or-nothing transaction —
validate -> lock every payroll_record -> post the accounting journal ->
mark FINALIZED -> audit. A failure at the accounting-posting step rolls
back the whole finalize (nothing partially finalized).
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import (
    PAYROLL_ALREADY_FINALIZED,
    PAYROLL_CORRECTION_NOT_ALLOWED,
    PAYROLL_DUPLICATE_RUN,
    PAYROLL_PERIOD_INVALID,
    PAYROLL_RUN_NOT_FOUND,
    PAYROLL_SALARY_STRUCTURE_MISSING,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.employee import ACTIVE, INACTIVE, ON_NOTICE, Employee
from app.models.payroll_period import FINALIZED as PERIOD_FINALIZED
from app.models.payroll_period import OPEN as PERIOD_OPEN
from app.models.payroll_period import PROCESSED as PERIOD_PROCESSED
from app.models.payroll_period import PayrollPeriod
from app.models.payroll_record import PayrollRecord
from app.models.payroll_record_line import PayrollRecordLine
from app.models.payroll_run import CALCULATED, DRAFT, FINALIZED, REVERSED, PayrollRun
from app.models.tenant import Tenant
from app.services.accounting.accounting_posting_service import AccountingPostingService
from app.services.audit.audit_service import AuditService
from app.services.payroll.attendance_service import AttendanceService
from app.services.payroll.leave_service import LeaveService
from app.services.payroll.payroll_calculation_service import (
    AttendanceInput,
    LeaveInput,
    calculate_attendance_summary,
    calculate_payroll,
)
from app.services.payroll.salary_service import SalaryStructureService
from app.services.sales.document_numbering_service import DocumentNumberingService

PAYSLIP = "PAYSLIP"
PAYROLL_ELIGIBLE_STATUSES = frozenset({ACTIVE, ON_NOTICE})

_ZERO = Decimal("0")


class PayrollRunService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Payroll Period (§18/§56) -------------------------------------------

    async def get_or_create_period(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, period_label: str, start_date: date, end_date: date,
    ) -> PayrollPeriod:
        if end_date < start_date:
            raise ValidationAppError("end_date must not be before start_date.", code=PAYROLL_PERIOD_INVALID)
        existing = await self._session.execute(select(PayrollPeriod).where(PayrollPeriod.tenant_id == tenant_id, PayrollPeriod.period_label == period_label))
        period = existing.scalar_one_or_none()
        if period is not None:
            return period

        # §56: prevent overlapping payroll periods.
        overlap = await self._session.execute(
            select(PayrollPeriod).where(
                PayrollPeriod.tenant_id == tenant_id, PayrollPeriod.start_date <= end_date, PayrollPeriod.end_date >= start_date,
            )
        )
        if overlap.scalar_one_or_none() is not None:
            raise ValidationAppError(f"Payroll period {period_label} overlaps with an existing period.", code=PAYROLL_PERIOD_INVALID)

        period = PayrollPeriod(tenant_id=tenant_id, period_label=period_label, start_date=start_date, end_date=end_date, created_by=actor_user_id, updated_by=actor_user_id)
        self._session.add(period)
        await self._session.flush()
        return period

    async def list_periods(self, tenant_id: uuid.UUID) -> list[PayrollPeriod]:
        result = await self._session.execute(select(PayrollPeriod).where(PayrollPeriod.tenant_id == tenant_id).order_by(PayrollPeriod.start_date.desc()))
        return list(result.scalars().all())

    # --- Payroll Run creation (§37 duplicate prevention) --------------------

    async def create_run(self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, payroll_period_id: uuid.UUID) -> PayrollRun:
        period_result = await self._session.execute(select(PayrollPeriod).where(PayrollPeriod.id == payroll_period_id, PayrollPeriod.tenant_id == tenant_id))
        period = period_result.scalar_one_or_none()
        if period is None:
            raise NotFoundError("Payroll period not found", code=PAYROLL_PERIOD_INVALID)

        existing = await self._session.execute(
            select(PayrollRun).where(PayrollRun.tenant_id == tenant_id, PayrollRun.payroll_period_id == payroll_period_id, PayrollRun.status != REVERSED)
        )
        active_run = existing.scalar_one_or_none()
        if active_run is not None:
            raise ConflictError("A payroll run already exists for this period. Reverse it before creating a new one.", code=PAYROLL_DUPLICATE_RUN)

        run = PayrollRun(tenant_id=tenant_id, payroll_period_id=payroll_period_id, status=DRAFT, created_by=actor_user_id, updated_by=actor_user_id)
        self._session.add(run)
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PAYROLL_RUN_CREATED", entity_type="payroll_run",
            entity_id=run.id, after={"payroll_period_id": str(payroll_period_id)}, ip_address=None,
        )
        return run

    async def get_run_locked(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> PayrollRun:
        result = await self._session.execute(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.tenant_id == tenant_id).with_for_update())
        run = result.scalar_one_or_none()
        if run is None:
            raise NotFoundError("Payroll run not found", code=PAYROLL_RUN_NOT_FOUND)
        return run

    async def get_run(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> PayrollRun:
        result = await self._session.execute(select(PayrollRun).where(PayrollRun.id == run_id, PayrollRun.tenant_id == tenant_id))
        run = result.scalar_one_or_none()
        if run is None:
            raise NotFoundError("Payroll run not found", code=PAYROLL_RUN_NOT_FOUND)
        return run

    async def list_runs(self, tenant_id: uuid.UUID) -> list[PayrollRun]:
        result = await self._session.execute(select(PayrollRun).where(PayrollRun.tenant_id == tenant_id).order_by(PayrollRun.created_at.desc()))
        return list(result.scalars().all())

    # --- Calculate (§19/§20/§21/§22/§23/§24/§36/§45 idempotent recalculation)

    async def calculate_run(self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, run_id: uuid.UUID, ip_address: str | None) -> PayrollRun:
        run = await self.get_run_locked(tenant_id, run_id)
        if run.status == FINALIZED:
            raise ValidationAppError("Cannot recalculate a FINALIZED payroll run.", code=PAYROLL_ALREADY_FINALIZED)
        if run.status == REVERSED:
            raise ValidationAppError("Cannot recalculate a REVERSED payroll run.", code=PAYROLL_ALREADY_FINALIZED)

        period_result = await self._session.execute(select(PayrollPeriod).where(PayrollPeriod.id == run.payroll_period_id))
        period = period_result.scalar_one()

        # §20: eligible employees — active/on-notice, whose employment
        # window overlaps this period at all.
        employees_result = await self._session.execute(
            select(Employee).where(
                Employee.tenant_id == tenant_id, Employee.status != INACTIVE,
                Employee.date_of_joining <= period.end_date,
                (Employee.exit_date.is_(None)) | (Employee.exit_date >= period.start_date),
            )
        )
        employees = list(employees_result.scalars().all())

        # Recalculation is idempotent: wipe any previously-calculated
        # (non-finalized) records for this run and rebuild — a run can
        # only reach here while DRAFT/CALCULATED, never FINALIZED.
        old_records = await self._session.execute(select(PayrollRecord).where(PayrollRecord.payroll_run_id == run.id))
        for old in old_records.scalars().all():
            await self._session.execute(PayrollRecordLine.__table__.delete().where(PayrollRecordLine.payroll_record_id == old.id))
            await self._session.delete(old)
        await self._session.flush()

        structure_service = SalaryStructureService(self._session)
        attendance_service = AttendanceService(self._session)
        leave_service = LeaveService(self._session)

        total_gross = _ZERO
        total_deductions = _ZERO
        total_net = _ZERO
        eligible_count = 0

        for employee in employees:
            structure = await structure_service.get_effective_structure(tenant_id, employee.id, period.end_date)
            if structure is None:
                continue  # §20: "do not process employees without a valid salary structure" — skipped, not errored
            structure_lines = await structure_service.to_calculation_inputs(structure.id)

            attendance_rows = await attendance_service.get_for_employee_period(tenant_id, employee.id, period.start_date, period.end_date)
            leave_rows = await leave_service.get_for_employee_period(tenant_id, employee.id, period.start_date, period.end_date)

            summary = calculate_attendance_summary(
                period_start=period.start_date, period_end=period.end_date, date_of_joining=employee.date_of_joining,
                exit_date=employee.exit_date,
                attendance=[AttendanceInput(attendance_date=a.attendance_date, status=a.status) for a in attendance_rows],
                leaves=[LeaveInput(from_date=leave_.from_date, to_date=leave_.to_date, leave_type=leave_.leave_type, status=leave_.status) for leave_ in leave_rows],
            )
            result = calculate_payroll(structure_lines=structure_lines, attendance_summary=summary)

            record = PayrollRecord(
                tenant_id=tenant_id, payroll_run_id=run.id, employee_id=employee.id, employee_code_snapshot=employee.employee_code,
                employee_name_snapshot=employee.full_name, designation_snapshot=employee.designation, salary_structure_id=structure.id,
                calendar_days=result.calendar_days, working_days=result.working_days, present_days=result.present_days,
                paid_leave_days=result.paid_leave_days, unpaid_leave_days=result.unpaid_leave_days, payable_days=result.payable_days,
                gross_earnings=result.gross_earnings, total_deductions=result.total_deductions, net_salary=result.net_salary,
                status=CALCULATED, created_by=actor_user_id, updated_by=actor_user_id,
            )
            self._session.add(record)
            await self._session.flush()

            for line in result.earnings + result.deductions:
                self._session.add(
                    PayrollRecordLine(
                        tenant_id=tenant_id, payroll_record_id=record.id, component_type=line.component_type,
                        component_code=line.code, component_name=line.name, amount=line.amount,
                        created_by=actor_user_id, updated_by=actor_user_id,
                    )
                )

            total_gross += result.gross_earnings
            total_deductions += result.total_deductions
            total_net += result.net_salary
            eligible_count += 1

        run.status = CALCULATED
        run.employee_count = eligible_count
        run.total_gross = total_gross
        run.total_deductions = total_deductions
        run.total_net = total_net
        run.calculated_at = datetime.now(timezone.utc)
        run.updated_by = actor_user_id
        run.row_version += 1
        await self._session.flush()

        if period.status == PERIOD_OPEN:
            period.status = PERIOD_PROCESSED
            period.updated_by = actor_user_id
            await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PAYROLL_CALCULATED", entity_type="payroll_run",
            entity_id=run.id, after={"employee_count": eligible_count, "total_gross": str(total_gross), "total_net": str(total_net)},
            ip_address=ip_address,
        )
        return run

    # --- Finalize (§29/§32/§35/§63 atomic) -----------------------------------

    async def finalize_run(self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, run_id: uuid.UUID, ip_address: str | None) -> PayrollRun:
        run = await self.get_run_locked(tenant_id, run_id)
        if run.status == FINALIZED:
            return run  # §38 idempotent: finalize is safe to retry
        if run.status != CALCULATED:
            raise ValidationAppError("A payroll run must be CALCULATED before it can be finalized.", code=PAYROLL_ALREADY_FINALIZED)
        if run.employee_count == 0:
            raise ValidationAppError("Cannot finalize a payroll run with zero eligible employees.", code=PAYROLL_SALARY_STRUCTURE_MISSING)

        period_result = await self._session.execute(select(PayrollPeriod).where(PayrollPeriod.id == run.payroll_period_id))
        period = period_result.scalar_one()

        tenant_result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = tenant_result.scalar_one()
        numbering = DocumentNumberingService(self._session)

        records_result = await self._session.execute(select(PayrollRecord).where(PayrollRecord.payroll_run_id == run.id))
        records = list(records_result.scalars().all())
        for record in records:
            payslip_number = await numbering.next_number(tenant=tenant, document_type=PAYSLIP, prefix="PAYSLIP", as_of=period.end_date)
            record.payslip_number = payslip_number
            record.status = FINALIZED
            record.updated_by = actor_user_id
        await self._session.flush()

        accounting_reference = await AccountingPostingService(self._session).post_payroll_run(
            tenant_id=tenant_id, actor_user_id=actor_user_id, payroll_run_id=run.id, run_date=period.end_date,
            total_gross=run.total_gross, total_deductions=run.total_deductions, total_net=run.total_net,
            run_label=period.period_label, ip_address=ip_address,
        )

        run.status = FINALIZED
        run.finalized_at = datetime.now(timezone.utc)
        run.accounting_posting_reference = accounting_reference
        run.updated_by = actor_user_id
        run.row_version += 1

        period.status = PERIOD_FINALIZED
        period.updated_by = actor_user_id
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PAYROLL_FINALIZED", entity_type="payroll_run",
            entity_id=run.id, after={"accounting_posting_reference": accounting_reference, "total_net": str(run.total_net)},
            ip_address=ip_address,
        )
        return run

    # --- Reverse / correction (§34/OD-023) -----------------------------------

    async def reverse_run(self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, run_id: uuid.UUID, ip_address: str | None) -> PayrollRun:
        run = await self.get_run_locked(tenant_id, run_id)
        if run.status != FINALIZED:
            raise ValidationAppError("Only a FINALIZED payroll run can be reversed.", code=PAYROLL_CORRECTION_NOT_ALLOWED)

        accounting_reference = await AccountingPostingService(self._session).reverse_payroll_run(
            tenant_id=tenant_id, actor_user_id=actor_user_id, payroll_run_id=run.id, ip_address=ip_address,
        )

        previous_status = run.status
        run.status = REVERSED
        run.updated_by = actor_user_id
        run.row_version += 1

        period_result = await self._session.execute(select(PayrollPeriod).where(PayrollPeriod.id == run.payroll_period_id))
        period = period_result.scalar_one()
        period.status = PERIOD_OPEN
        period.updated_by = actor_user_id
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PAYROLL_REVERSED", entity_type="payroll_run",
            entity_id=run.id, before={"status": previous_status}, after={"status": REVERSED, "accounting_reversal_reference": accounting_reference},
            ip_address=ip_address,
        )
        return run

    # --- Payroll Record / Payslip queries ------------------------------------

    async def get_record(self, tenant_id: uuid.UUID, record_id: uuid.UUID) -> PayrollRecord:
        result = await self._session.execute(select(PayrollRecord).where(PayrollRecord.id == record_id, PayrollRecord.tenant_id == tenant_id))
        record = result.scalar_one_or_none()
        if record is None:
            raise NotFoundError("Payroll record not found", code=PAYROLL_RUN_NOT_FOUND)
        return record

    async def get_record_lines(self, record_id: uuid.UUID) -> list[PayrollRecordLine]:
        result = await self._session.execute(select(PayrollRecordLine).where(PayrollRecordLine.payroll_record_id == record_id))
        return list(result.scalars().all())

    async def list_records_for_run(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> list[PayrollRecord]:
        result = await self._session.execute(select(PayrollRecord).where(PayrollRecord.tenant_id == tenant_id, PayrollRecord.payroll_run_id == run_id))
        return list(result.scalars().all())

    async def list_records_for_employee(self, tenant_id: uuid.UUID, employee_id: uuid.UUID) -> list[PayrollRecord]:
        result = await self._session.execute(
            select(PayrollRecord).where(PayrollRecord.tenant_id == tenant_id, PayrollRecord.employee_id == employee_id).order_by(PayrollRecord.created_at.desc())
        )
        return list(result.scalars().all())
