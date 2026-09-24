"""Employee, Payroll & Basic Salary Management schemas (PROMPT-029)."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class CreateEmployeeRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    mobile: str | None = None
    email: str | None = None
    date_of_joining: date
    department: str | None = None
    designation: str | None = None
    employment_type: str = "FULL_TIME"
    reporting_manager_id: str | None = None
    address: str | None = None
    bank_account_number: str | None = None
    bank_ifsc: str | None = None
    bank_name: str | None = None


class UpdateEmployeeRequest(BaseModel):
    full_name: str | None = None
    mobile: str | None = None
    email: str | None = None
    department: str | None = None
    designation: str | None = None
    employment_type: str | None = None
    reporting_manager_id: str | None = None
    address: str | None = None
    bank_account_number: str | None = None
    bank_ifsc: str | None = None
    bank_name: str | None = None
    expected_row_version: int


class SetEmployeeStatusRequest(BaseModel):
    status: str
    exit_date: date | None = None
    expected_row_version: int


class EmployeeListItem(BaseModel):
    id: str
    employee_code: str
    full_name: str
    designation: str | None
    department: str | None
    date_of_joining: str
    exit_date: str | None
    employment_type: str
    status: str
    row_version: int


class EmployeeDetail(EmployeeListItem):
    mobile: str | None
    email: str | None
    reporting_manager_id: str | None
    address: str | None
    bank_account_number: str | None
    bank_ifsc: str | None
    bank_name: str | None


class SalaryStructureLineRequest(BaseModel):
    component_id: str
    calculation_type: str
    amount: Decimal | None = None
    percentage: Decimal | None = None
    percentage_of_component_code: str | None = None


class CreateSalaryStructureRequest(BaseModel):
    effective_from: date
    lines: list[SalaryStructureLineRequest]


class SalaryStructureLineItem(BaseModel):
    id: str
    component_id: str
    component_code: str
    component_name: str
    component_type: str
    calculation_type: str
    amount: str
    percentage: str | None
    percentage_of_component_code: str | None


class SalaryStructureDetail(BaseModel):
    id: str
    employee_id: str
    effective_from: str
    row_version: int
    lines: list[SalaryStructureLineItem]


class SalaryComponentItem(BaseModel):
    id: str
    code: str
    name: str
    component_type: str
    default_calculation_type: str
    is_active: bool


class RecordAttendanceRequest(BaseModel):
    employee_id: str
    attendance_date: date
    status: str
    notes: str | None = None


class UpdateAttendanceRequest(BaseModel):
    status: str
    notes: str | None = None
    expected_row_version: int


class AttendanceItem(BaseModel):
    id: str
    employee_id: str
    attendance_date: str
    status: str
    notes: str | None
    row_version: int


class CreateLeaveRequest(BaseModel):
    employee_id: str
    leave_type: str
    from_date: date
    to_date: date
    reason: str | None = None


class LeaveItem(BaseModel):
    id: str
    employee_id: str
    leave_type: str
    from_date: str
    to_date: str
    days: str
    status: str
    reason: str | None
    approved_by: str | None
    row_version: int


class CreatePayrollPeriodRequest(BaseModel):
    period_label: str
    start_date: date
    end_date: date


class PayrollPeriodItem(BaseModel):
    id: str
    period_label: str
    start_date: str
    end_date: str
    status: str


class CreatePayrollRunRequest(BaseModel):
    payroll_period_id: str


class PayrollRunItem(BaseModel):
    id: str
    payroll_period_id: str
    period_label: str
    status: str
    employee_count: int
    total_gross: str
    total_deductions: str
    total_net: str
    calculated_at: str | None
    finalized_at: str | None
    accounting_posting_reference: str | None
    row_version: int


class PayrollRecordLineItem(BaseModel):
    component_type: str
    component_code: str
    component_name: str
    amount: str


class PayrollRecordItem(BaseModel):
    id: str
    payroll_run_id: str
    employee_id: str
    employee_code_snapshot: str
    employee_name_snapshot: str
    designation_snapshot: str | None
    calendar_days: int
    working_days: str
    present_days: str
    paid_leave_days: str
    unpaid_leave_days: str
    payable_days: str
    gross_earnings: str
    total_deductions: str
    net_salary: str
    payslip_number: str | None
    status: str


class PayslipDetail(PayrollRecordItem):
    period_label: str
    period_start: str
    period_end: str
    lines: list[PayrollRecordLineItem]
