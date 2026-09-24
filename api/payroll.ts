import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';

function buildQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// --- Employees -------------------------------------------------------------

export interface EmployeeListItem {
  id: string;
  employee_code: string;
  full_name: string;
  designation: string | null;
  department: string | null;
  date_of_joining: string;
  exit_date: string | null;
  employment_type: string;
  status: string;
  row_version: number;
}

export interface EmployeeDetail extends EmployeeListItem {
  mobile: string | null;
  email: string | null;
  reporting_manager_id: string | null;
  address: string | null;
  bank_account_number: string | null;
  bank_ifsc: string | null;
  bank_name: string | null;
}

export interface CreateEmployeePayload {
  full_name: string;
  mobile?: string | null;
  email?: string | null;
  date_of_joining: string;
  department?: string | null;
  designation?: string | null;
  employment_type?: string;
  reporting_manager_id?: string | null;
  address?: string | null;
  bank_account_number?: string | null;
  bank_ifsc?: string | null;
  bank_name?: string | null;
}

export interface ListEmployeesParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  department?: string;
  designation?: string;
  employment_type?: string;
  [key: string]: string | number | undefined;
}

export async function listEmployees(params: ListEmployeesParams = {}): Promise<ApiList<EmployeeListItem>> {
  return apiRequestList<EmployeeListItem>(`/employees${buildQuery(params)}`);
}
export async function getEmployee(id: string): Promise<EmployeeDetail> {
  return apiRequest<EmployeeDetail>(`/employees/${id}`);
}
export async function createEmployee(payload: CreateEmployeePayload): Promise<EmployeeDetail> {
  return apiRequest<EmployeeDetail>('/employees', { method: 'POST', body: payload });
}
export async function updateEmployee(id: string, payload: Partial<CreateEmployeePayload> & { expected_row_version: number }): Promise<EmployeeDetail> {
  return apiRequest<EmployeeDetail>(`/employees/${id}`, { method: 'PUT', body: payload });
}
export async function setEmployeeStatus(id: string, status: string, exitDate: string | null, expectedRowVersion: number): Promise<EmployeeDetail> {
  return apiRequest<EmployeeDetail>(`/employees/${id}/deactivate`, { method: 'POST', body: { status, exit_date: exitDate, expected_row_version: expectedRowVersion } });
}
export async function getEmployeePayrollHistory(id: string): Promise<PayrollRecordItem[]> {
  return apiRequest<PayrollRecordItem[]>(`/employees/${id}/payroll-history`);
}

// --- Salary ------------------------------------------------------------------

export interface SalaryComponentItem {
  id: string;
  code: string;
  name: string;
  component_type: 'EARNING' | 'DEDUCTION';
  default_calculation_type: string;
  is_active: boolean;
}

export interface SalaryStructureLineItem {
  id: string;
  component_id: string;
  component_code: string;
  component_name: string;
  component_type: string;
  calculation_type: string;
  amount: string;
  percentage: string | null;
  percentage_of_component_code: string | null;
}

export interface SalaryStructureDetail {
  id: string;
  employee_id: string;
  effective_from: string;
  row_version: number;
  lines: SalaryStructureLineItem[];
}

export interface SalaryStructureLineInput {
  component_id: string;
  calculation_type: string;
  amount?: string;
  percentage?: string;
  percentage_of_component_code?: string;
}

export async function listSalaryComponents(): Promise<SalaryComponentItem[]> {
  return apiRequest<SalaryComponentItem[]>('/salary-components');
}
export async function listSalaryStructures(employeeId: string): Promise<SalaryStructureDetail[]> {
  return apiRequest<SalaryStructureDetail[]>(`/employees/${employeeId}/salary-structures`);
}
export async function createSalaryStructure(employeeId: string, effectiveFrom: string, lines: SalaryStructureLineInput[]): Promise<SalaryStructureDetail> {
  return apiRequest<SalaryStructureDetail>(`/employees/${employeeId}/salary-structures`, { method: 'POST', body: { effective_from: effectiveFrom, lines } });
}

// --- Attendance -----------------------------------------------------------

export interface AttendanceItem {
  id: string;
  employee_id: string;
  attendance_date: string;
  status: string;
  notes: string | null;
  row_version: number;
}

export async function listAttendance(params: { employee_id?: string; date_from?: string; date_to?: string; status?: string } = {}): Promise<AttendanceItem[]> {
  return apiRequest<AttendanceItem[]>(`/attendance${buildQuery(params)}`);
}
export async function recordAttendance(employeeId: string, attendanceDate: string, status: string, notes?: string): Promise<AttendanceItem> {
  return apiRequest<AttendanceItem>('/attendance', { method: 'POST', body: { employee_id: employeeId, attendance_date: attendanceDate, status, notes } });
}

// --- Leave -----------------------------------------------------------------

export interface LeaveItem {
  id: string;
  employee_id: string;
  leave_type: string;
  from_date: string;
  to_date: string;
  days: string;
  status: string;
  reason: string | null;
  approved_by: string | null;
  row_version: number;
}

export async function listLeave(params: { employee_id?: string; status?: string } = {}): Promise<LeaveItem[]> {
  return apiRequest<LeaveItem[]>(`/leave${buildQuery(params)}`);
}
export async function createLeave(employeeId: string, leaveType: string, fromDate: string, toDate: string, reason?: string): Promise<LeaveItem> {
  return apiRequest<LeaveItem>('/leave', { method: 'POST', body: { employee_id: employeeId, leave_type: leaveType, from_date: fromDate, to_date: toDate, reason } });
}
export async function approveLeave(id: string): Promise<LeaveItem> {
  return apiRequest<LeaveItem>(`/leave/${id}/approve`, { method: 'POST', body: {} });
}
export async function rejectLeave(id: string): Promise<LeaveItem> {
  return apiRequest<LeaveItem>(`/leave/${id}/reject`, { method: 'POST', body: {} });
}

// --- Payroll Periods / Runs --------------------------------------------------

export interface PayrollPeriodItem {
  id: string;
  period_label: string;
  start_date: string;
  end_date: string;
  status: string;
}

export interface PayrollRunItem {
  id: string;
  payroll_period_id: string;
  period_label: string;
  status: string;
  employee_count: number;
  total_gross: string;
  total_deductions: string;
  total_net: string;
  calculated_at: string | null;
  finalized_at: string | null;
  accounting_posting_reference: string | null;
  row_version: number;
}

export interface PayrollRecordItem {
  id: string;
  payroll_run_id: string;
  employee_id: string;
  employee_code_snapshot: string;
  employee_name_snapshot: string;
  designation_snapshot: string | null;
  calendar_days: number;
  working_days: string;
  present_days: string;
  paid_leave_days: string;
  unpaid_leave_days: string;
  payable_days: string;
  gross_earnings: string;
  total_deductions: string;
  net_salary: string;
  payslip_number: string | null;
  status: string;
}

export interface PayrollRecordLineItem {
  component_type: string;
  component_code: string;
  component_name: string;
  amount: string;
}

export interface PayslipDetail extends PayrollRecordItem {
  period_label: string;
  period_start: string;
  period_end: string;
  lines: PayrollRecordLineItem[];
}

export async function listPayrollPeriods(): Promise<PayrollPeriodItem[]> {
  return apiRequest<PayrollPeriodItem[]>('/payroll/periods');
}
export async function createPayrollPeriod(periodLabel: string, startDate: string, endDate: string): Promise<PayrollPeriodItem> {
  return apiRequest<PayrollPeriodItem>('/payroll/periods', { method: 'POST', body: { period_label: periodLabel, start_date: startDate, end_date: endDate } });
}
export async function listPayrollRuns(): Promise<PayrollRunItem[]> {
  return apiRequest<PayrollRunItem[]>('/payroll/runs');
}
export async function getPayrollRun(id: string): Promise<PayrollRunItem> {
  return apiRequest<PayrollRunItem>(`/payroll/runs/${id}`);
}
export async function createPayrollRun(periodId: string): Promise<PayrollRunItem> {
  return apiRequest<PayrollRunItem>('/payroll/runs', { method: 'POST', body: { payroll_period_id: periodId }, idempotencyKey: newIdempotencyKey() });
}
export async function calculatePayrollRun(id: string): Promise<PayrollRunItem> {
  return apiRequest<PayrollRunItem>(`/payroll/runs/${id}/calculate`, { method: 'POST', body: {} });
}
export async function finalizePayrollRun(id: string): Promise<PayrollRunItem> {
  return apiRequest<PayrollRunItem>(`/payroll/runs/${id}/finalize`, { method: 'POST', body: {}, idempotencyKey: newIdempotencyKey() });
}
export async function reversePayrollRun(id: string): Promise<PayrollRunItem> {
  return apiRequest<PayrollRunItem>(`/payroll/runs/${id}/reverse`, { method: 'POST', body: {} });
}
export async function listPayrollRecords(runId: string): Promise<PayrollRecordItem[]> {
  return apiRequest<PayrollRecordItem[]>(`/payroll/runs/${runId}/records`);
}
export async function getPayslip(recordId: string): Promise<PayslipDetail> {
  return apiRequest<PayslipDetail>(`/payroll/${recordId}/payslip`);
}
