"""Payroll calculation engine (PROMPT-029 §17/§21-§27/§57/§58) — pure,
deterministic, side-effect-free functions (§57's own explicit mandate:
"the same input must produce the same result... do not embed
calculations directly inside UI components"). No DB access here; callers
pass in already-fetched rows.

**Resolved Open Decisions (documented here since this is where they
apply, not silently assumed):**

- **OD-014/OD-015 (working-day vs calendar-day basis)**: resolved to
  CALENDAR DAYS. `calendar_days` = the payroll period's own total day
  count (e.g. 30 for April), never a separate working-day calendar (no
  approved holiday/weekly-off master exists in this codebase's
  baseline). This directly matches §23's own formula: "Gross Salary ÷
  Applicable Salary Days × Payable Days" — "Applicable Salary Days" IS
  the period's calendar days here.
- **OD-016/OD-017 (mid-period joining/exit proration) + OD-018 (unpaid
  leave deduction)**: resolved to ONE UNIFIED formula rather than three
  separate rules. `payable_days` only ever counts days within the
  employee's actual employment window inside the period (`date_of_
  joining`..`exit_date`, clipped to the period) that are PRESENT/
  HALF_DAY/paid-LEAVE/HOLIDAY/WEEK_OFF. Every other day in the period
  (before joining, after exit, ABSENT, or unpaid LEAVE) simply doesn't
  contribute to `payable_days`. `proration_factor = payable_days /
  calendar_days` then applies identically whether the shortfall came
  from joining mid-month, exiting mid-month, or taking unpaid leave —
  there is no need for three different formulas because all three are
  the same underlying question: "what fraction of the full period was
  this person payable for?"
- **Unmarked-day default**: a day within the employee's employment
  window that has NO attendance record and NO matching leave record
  defaults to PRESENT (payable) — small-business "exception-based"
  attendance marking (mark absences/leave; everything else assumes the
  person showed up), not the alternative of defaulting to unpaid, which
  would penalize a tenant that doesn't bother marking attendance for
  every single present day. Documented, not silently chosen.
- **`status=LEAVE` with no matching APPROVED leave_request row for that
  date** defaults conservatively to UNPAID (same rationale as PROMPT-
  026's own "default conservatively when ambiguous" precedent).
- **Deductions are prorated by the identical factor as earnings** — no
  separate deduction-proration rule is approved, so the same, uniform
  formula is used for both (an explicit, reasonable default, easily
  revisited later without a schema change).
- **Percentage-of-component bases only resolve against FIXED_AMOUNT
  lines within the same structure** (§10/§12, OD-012) — no percentage-
  of-percentage chaining exists, avoiding an unapproved formula engine
  (§10's own explicit "do not implement arbitrary payroll scripting").
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.models.attendance import ABSENT, HALF_DAY, HOLIDAY, LEAVE, PRESENT, WEEK_OFF
from app.models.leave_request import APPROVED as LEAVE_APPROVED
from app.models.leave_request import PAID as LEAVE_PAID
from app.models.leave_request import UNPAID as LEAVE_UNPAID
from app.models.salary_component import EARNING, FIXED_AMOUNT

_ZERO = Decimal("0")


def _round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ResolvedComponent:
    component_id: uuid.UUID
    code: str
    name: str
    component_type: str
    amount: Decimal  # full, unprorated monthly amount


@dataclass(frozen=True)
class StructureLineInput:
    component_id: uuid.UUID
    code: str
    name: str
    component_type: str
    calculation_type: str
    amount: Decimal
    percentage: Decimal | None
    percentage_of_component_code: str | None


def resolve_structure_components(lines: list[StructureLineInput]) -> list[ResolvedComponent]:
    """§9/§10/§12: resolves every line's own (unprorated) monthly amount
    — FIXED_AMOUNT verbatim, PERCENTAGE against a named FIXED_AMOUNT
    line's own amount within the SAME list."""
    fixed_amounts_by_code: dict[str, Decimal] = {
        line.code: line.amount for line in lines if line.calculation_type == FIXED_AMOUNT
    }
    resolved: list[ResolvedComponent] = []
    for line in lines:
        if line.calculation_type == FIXED_AMOUNT:
            amount = line.amount
        else:
            base = fixed_amounts_by_code.get(line.percentage_of_component_code or "", _ZERO)
            amount = _round2(base * (line.percentage or _ZERO) / Decimal("100"))
        resolved.append(ResolvedComponent(component_id=line.component_id, code=line.code, name=line.name, component_type=line.component_type, amount=amount))
    return resolved


@dataclass(frozen=True)
class AttendanceInput:
    attendance_date: date
    status: str


@dataclass(frozen=True)
class LeaveInput:
    from_date: date
    to_date: date
    leave_type: str
    status: str


@dataclass(frozen=True)
class AttendanceSummary:
    calendar_days: int
    present_days: Decimal
    paid_leave_days: Decimal
    unpaid_leave_days: Decimal
    payable_days: Decimal


def _expand_leave_dates(leaves: list[LeaveInput], leave_type: str, period_start: date, period_end: date) -> set[date]:
    dates: set[date] = set()
    for leave in leaves:
        if leave.status != LEAVE_APPROVED or leave.leave_type != leave_type:
            continue
        start = max(leave.from_date, period_start)
        end = min(leave.to_date, period_end)
        current = start
        while current <= end:
            dates.add(current)
            current += timedelta(days=1)
    return dates


def calculate_attendance_summary(
    *, period_start: date, period_end: date, date_of_joining: date, exit_date: date | None,
    attendance: list[AttendanceInput], leaves: list[LeaveInput],
) -> AttendanceSummary:
    calendar_days = (period_end - period_start).days + 1

    window_start = max(period_start, date_of_joining)
    window_end = min(period_end, exit_date) if exit_date else period_end

    if window_start > window_end:
        return AttendanceSummary(calendar_days=calendar_days, present_days=_ZERO, paid_leave_days=_ZERO, unpaid_leave_days=_ZERO, payable_days=_ZERO)

    paid_leave_dates = _expand_leave_dates(leaves, LEAVE_PAID, window_start, window_end)
    unpaid_leave_dates = _expand_leave_dates(leaves, LEAVE_UNPAID, window_start, window_end)
    attendance_by_date = {a.attendance_date: a.status for a in attendance if window_start <= a.attendance_date <= window_end}

    present = _ZERO
    paid_leave = _ZERO
    unpaid_leave = _ZERO
    holiday_or_week_off = _ZERO

    current = window_start
    while current <= window_end:
        status = attendance_by_date.get(current)
        if status == PRESENT:
            present += 1
        elif status == HALF_DAY:
            present += Decimal("0.5")
        elif status in (HOLIDAY, WEEK_OFF):
            holiday_or_week_off += 1
        elif status == LEAVE:
            if current in paid_leave_dates:
                paid_leave += 1
            else:
                unpaid_leave += 1
        elif status == ABSENT:
            unpaid_leave += 1
        else:
            # No attendance record for this date: exception-based
            # marking default — see module docstring.
            if current in paid_leave_dates:
                paid_leave += 1
            elif current in unpaid_leave_dates:
                unpaid_leave += 1
            else:
                present += 1
        current += timedelta(days=1)

    payable_days = present + paid_leave + holiday_or_week_off
    return AttendanceSummary(calendar_days=calendar_days, present_days=present, paid_leave_days=paid_leave, unpaid_leave_days=unpaid_leave, payable_days=payable_days)


@dataclass(frozen=True)
class PayrollCalculationResult:
    calendar_days: int
    working_days: Decimal
    present_days: Decimal
    paid_leave_days: Decimal
    unpaid_leave_days: Decimal
    payable_days: Decimal
    earnings: list[ResolvedComponent]
    deductions: list[ResolvedComponent]
    gross_earnings: Decimal
    total_deductions: Decimal
    net_salary: Decimal


def calculate_payroll(
    *, structure_lines: list[StructureLineInput], attendance_summary: AttendanceSummary,
) -> PayrollCalculationResult:
    """§25/§26/§27/§58: the authoritative gross/deduction/net
    calculation. Server-side only (§52) — never trusts a client-
    submitted total."""
    resolved = resolve_structure_components(structure_lines)

    proration_factor = (
        (attendance_summary.payable_days / Decimal(attendance_summary.calendar_days))
        if attendance_summary.calendar_days > 0
        else _ZERO
    )

    earning_lines = [
        ResolvedComponent(component_id=c.component_id, code=c.code, name=c.name, component_type=c.component_type, amount=_round2(c.amount * proration_factor))
        for c in resolved if c.component_type == EARNING
    ]
    deduction_lines = [
        ResolvedComponent(component_id=c.component_id, code=c.code, name=c.name, component_type=c.component_type, amount=_round2(c.amount * proration_factor))
        for c in resolved if c.component_type != EARNING
    ]

    gross = sum((c.amount for c in earning_lines), _ZERO)
    total_deductions = sum((c.amount for c in deduction_lines), _ZERO)
    net = gross - total_deductions

    return PayrollCalculationResult(
        calendar_days=attendance_summary.calendar_days, working_days=Decimal(attendance_summary.calendar_days),
        present_days=attendance_summary.present_days, paid_leave_days=attendance_summary.paid_leave_days,
        unpaid_leave_days=attendance_summary.unpaid_leave_days, payable_days=attendance_summary.payable_days,
        earnings=earning_lines, deductions=deduction_lines, gross_earnings=gross, total_deductions=total_deductions, net_salary=net,
    )
