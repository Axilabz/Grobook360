import React, { useState, useEffect, useCallback } from 'react';
import {
  X, Plus, Users, CalendarCheck, CalendarDays, Wallet, CheckCircle2, AlertTriangle, PlusCircle,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { ApiError } from '../api/client';
import * as P from '../api/payroll';
import LoadingState from '../shared/LoadingState';

type MainTab = 'employees' | 'attendance' | 'leave' | 'payroll';

const StatCard: React.FC<{ label: string; value: string; tone?: 'default' | 'positive' | 'negative' }> = ({ label, value, tone = 'default' }) => (
  <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
    <p className="text-[12px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{label}</p>
    <p className={`text-[20px] font-semibold mt-1 ${tone === 'positive' ? 'text-green-600' : tone === 'negative' ? 'text-red-600' : 'text-gray-900 dark:text-white'}`}>{value}</p>
  </div>
);

const STATUS_BADGE: Record<string, string> = {
  ACTIVE: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  INACTIVE: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  ON_NOTICE: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  EXITED: 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400',
  DRAFT: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  CALCULATED: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  FINALIZED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  REVERSED: 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400',
  PENDING: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  APPROVED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  REJECTED: 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400',
};

const Badge: React.FC<{ status: string }> = ({ status }) => (
  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[status] || 'bg-gray-100 text-gray-600'}`}>{status}</span>
);

const PayrollManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();

  const perms = {
    employees: hasPermission('employees.view'), attendance: hasPermission('attendance.view'),
    leave: hasPermission('leave.view'), payroll: hasPermission('payroll.view'),
  };

  const availableTabs: [MainTab, string, React.ReactNode][] = [
    ...(perms.employees ? [['employees', 'Employees', <Users size={14} key="i" />] as [MainTab, string, React.ReactNode]] : []),
    ...(perms.attendance ? [['attendance', 'Attendance', <CalendarCheck size={14} key="i" />] as [MainTab, string, React.ReactNode]] : []),
    ...(perms.leave ? [['leave', 'Leave', <CalendarDays size={14} key="i" />] as [MainTab, string, React.ReactNode]] : []),
    ...(perms.payroll ? [['payroll', 'Payroll', <Wallet size={14} key="i" />] as [MainTab, string, React.ReactNode]] : []),
  ];

  const [tab, setTab] = useState<MainTab>(availableTabs[0]?.[0] || 'employees');

  if (availableTabs.length === 0) {
    return <div className="p-8 text-center text-gray-500 dark:text-gray-400">You do not have permission to view Employee/Payroll data.</div>;
  }

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 shadow-sm">
        <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight mb-3">Employees &amp; Payroll</h2>
        <div className="flex gap-2 border-b border-gray-100 dark:border-gray-800 -mb-4 overflow-x-auto">
          {availableTabs.map(([key, label, icon]) => (
            <button key={key} onClick={() => setTab(key)} className={`flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium border-b-2 whitespace-nowrap ${tab === key ? 'border-[#0066ff] text-[#0066ff]' : 'border-transparent text-gray-500 dark:text-gray-400'}`}>
              {icon} {label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'employees' && perms.employees && <EmployeesTab showToast={showToast} canManage={hasPermission('employees.create')} canManageSalary={hasPermission('salary.manage')} canViewSalary={hasPermission('salary.view')} />}
      {tab === 'attendance' && perms.attendance && <AttendanceTab showToast={showToast} canManage={hasPermission('attendance.manage')} />}
      {tab === 'leave' && perms.leave && <LeaveTab showToast={showToast} canManage={hasPermission('leave.manage')} canApprove={hasPermission('leave.approve')} />}
      {tab === 'payroll' && perms.payroll && <PayrollTab showToast={showToast} canRun={hasPermission('payroll.run')} canFinalize={hasPermission('payroll.finalize')} canViewPayslip={hasPermission('payroll.view_payslip')} />}
    </div>
  );
};

// --- Employees ---------------------------------------------------------------

const EmployeesTab: React.FC<{ showToast: (m: string, t: 'success' | 'error') => void; canManage: boolean; canManageSalary: boolean; canViewSalary: boolean }> = ({ showToast, canManage, canManageSalary, canViewSalary }) => {
  const [items, setItems] = useState<P.EmployeeListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [viewingId, setViewingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await P.listEmployees({ page_size: 100 });
      setItems(result.data);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load employees.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      {canManage && (
        <div className="mb-4">
          <button onClick={() => setShowCreate(true)} className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium">
            <Plus size={14} /> New Employee
          </button>
        </div>
      )}
      {isLoading ? <div className="flex items-center justify-center py-16"><LoadingState bare /></div> : (
        <>
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-[13px]">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>{['Code', 'Name', 'Designation', 'Department', 'Joined', 'Status', ''].map((h) => <th key={h} className="px-4 py-2.5 text-[11px] font-semibold text-gray-600 dark:text-gray-300 uppercase">{h}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {items.map((e) => (
                    <tr key={e.id} className="hover:bg-blue-50 dark:hover:bg-gray-800">
                      <td className="px-4 py-2.5 font-mono text-gray-600 dark:text-gray-300">{e.employee_code}</td>
                      <td className="px-4 py-2.5"><button onClick={() => setViewingId(e.id)} className="font-medium text-gray-900 dark:text-white hover:text-[#0066ff] hover:underline">{e.full_name}</button></td>
                      <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400">{e.designation || '—'}</td>
                      <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400">{e.department || '—'}</td>
                      <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400">{e.date_of_joining}</td>
                      <td className="px-4 py-2.5"><Badge status={e.status} /></td>
                      <td className="px-4 py-2.5 text-right"><button onClick={() => setViewingId(e.id)} className="text-[#0066ff] text-[12px] font-medium">View</button></td>
                    </tr>
                  ))}
                  {items.length === 0 && <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">No employees yet.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
          <div className="md:hidden space-y-3">
            {items.map((e) => (
              <button key={e.id} onClick={() => setViewingId(e.id)} className="w-full text-left bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-start justify-between mb-1">
                  <div><p className="font-semibold text-gray-900 dark:text-white text-[15px]">{e.full_name}</p><p className="text-[12px] text-gray-500 font-mono">{e.employee_code}</p></div>
                  <Badge status={e.status} />
                </div>
                <p className="text-[13px] text-gray-600 dark:text-gray-300">{e.designation || '—'} · Joined {e.date_of_joining}</p>
              </button>
            ))}
          </div>
        </>
      )}
      {showCreate && <CreateEmployeeModal onClose={() => setShowCreate(false)} onCreated={() => { setShowCreate(false); load(); }} showToast={showToast} />}
      {viewingId && <EmployeeDetailModal employeeId={viewingId} onClose={() => setViewingId(null)} onChanged={load} showToast={showToast} canManageSalary={canManageSalary} canViewSalary={canViewSalary} />}
    </div>
  );
};

const CreateEmployeeModal: React.FC<{ onClose: () => void; onCreated: () => void; showToast: (m: string, t: 'success' | 'error') => void }> = ({ onClose, onCreated, showToast }) => {
  const [fullName, setFullName] = useState('');
  const [dateOfJoining, setDateOfJoining] = useState('');
  const [designation, setDesignation] = useState('');
  const [department, setDepartment] = useState('');
  const [mobile, setMobile] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const handleSave = async () => {
    if (!fullName.trim() || !dateOfJoining) { showToast('Name and date of joining are required.', 'error'); return; }
    setIsSaving(true);
    try {
      await P.createEmployee({ full_name: fullName.trim(), date_of_joining: dateOfJoining, designation: designation || null, department: department || null, mobile: mobile || null });
      showToast('Employee created.', 'success');
      onCreated();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to create employee.', 'error');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4"><h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">New Employee</h3><button onClick={onClose}><X size={18} className="text-gray-400" /></button></div>
        <div className="space-y-3 text-[13px]">
          <input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Full name" className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-900" />
          <input type="date" value={dateOfJoining} onChange={(e) => setDateOfJoining(e.target.value)} className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-900" />
          <input value={designation} onChange={(e) => setDesignation(e.target.value)} placeholder="Designation" className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-900" />
          <input value={department} onChange={(e) => setDepartment(e.target.value)} placeholder="Department" className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-900" />
          <input value={mobile} onChange={(e) => setMobile(e.target.value)} placeholder="Mobile" className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 bg-white dark:bg-gray-900" />
        </div>
        <div className="grid grid-cols-2 gap-3 mt-5">
          <button onClick={onClose} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Cancel</button>
          <button onClick={handleSave} disabled={isSaving} className="py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium disabled:opacity-60">{isSaving ? 'Saving…' : 'Create'}</button>
        </div>
      </div>
    </div>
  );
};

const EmployeeDetailModal: React.FC<{ employeeId: string; onClose: () => void; onChanged: () => void; showToast: (m: string, t: 'success' | 'error') => void; canManageSalary: boolean; canViewSalary: boolean }> = ({ employeeId, onClose, onChanged, showToast, canManageSalary, canViewSalary }) => {
  const [employee, setEmployee] = useState<P.EmployeeDetail | null>(null);
  const [structures, setStructures] = useState<P.SalaryStructureDetail[]>([]);
  const [history, setHistory] = useState<P.PayrollRecordItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showAddStructure, setShowAddStructure] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const emp = await P.getEmployee(employeeId);
      setEmployee(emp);
      if (canViewSalary) setStructures(await P.listSalaryStructures(employeeId));
      setHistory(await P.getEmployeePayrollHistory(employeeId));
    } catch {
      showToast('Failed to load employee.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employeeId]);

  useEffect(() => { load(); }, [load]);

  if (isLoading || !employee) {
    return <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"><LoadingState bare /></div>;
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <div><h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{employee.full_name}</h3><p className="text-[13px] text-gray-500 font-mono">{employee.employee_code}</p></div>
          <button onClick={onClose}><X size={20} className="text-gray-400" /></button>
        </div>
        <div className="p-6 space-y-5 text-[14px]">
          <div className="flex items-center gap-2 flex-wrap"><Badge status={employee.status} /><span className="text-gray-500 dark:text-gray-400">{employee.designation || '—'} · {employee.department || '—'}</span></div>
          <div className="grid grid-cols-2 gap-3 text-[13px]">
            <div><p className="text-gray-400">Mobile</p><p className="text-gray-800 dark:text-gray-200">{employee.mobile || '—'}</p></div>
            <div><p className="text-gray-400">Email</p><p className="text-gray-800 dark:text-gray-200">{employee.email || '—'}</p></div>
            <div><p className="text-gray-400">Joined</p><p className="text-gray-800 dark:text-gray-200">{employee.date_of_joining}</p></div>
            <div><p className="text-gray-400">Employment Type</p><p className="text-gray-800 dark:text-gray-200">{employee.employment_type}</p></div>
          </div>

          {canViewSalary && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-[13px] font-semibold text-gray-800 dark:text-gray-100">Salary Structures</p>
                {canManageSalary && <button onClick={() => setShowAddStructure(true)} className="flex items-center gap-1 text-[12px] text-[#0066ff] font-medium"><PlusCircle size={14} /> Add</button>}
              </div>
              <div className="space-y-2">
                {structures.map((s) => (
                  <div key={s.id} className="border border-gray-200 dark:border-gray-700 rounded-lg p-3">
                    <p className="text-[13px] font-medium text-gray-800 dark:text-gray-100">Effective {s.effective_from}</p>
                    <div className="mt-1 space-y-0.5">
                      {s.lines.map((l) => <p key={l.id} className="text-[12px] text-gray-500 dark:text-gray-400">{l.component_name} ({l.component_type}): {l.calculation_type === 'PERCENTAGE' ? `${l.percentage}% of ${l.percentage_of_component_code}` : `₹${l.amount}`}</p>)}
                    </div>
                  </div>
                ))}
                {structures.length === 0 && <p className="text-[12px] text-gray-400">No salary structure defined yet.</p>}
              </div>
            </div>
          )}

          <div>
            <p className="text-[13px] font-semibold text-gray-800 dark:text-gray-100 mb-2">Payroll History</p>
            <div className="space-y-1">
              {history.map((h) => (
                <div key={h.id} className="flex items-center justify-between text-[13px] border-b border-gray-100 dark:border-gray-800 py-1.5">
                  <span className="text-gray-600 dark:text-gray-300">{h.payslip_number || '—'}</span>
                  <span className="text-gray-800 dark:text-gray-100 font-medium">₹{h.net_salary}</span>
                  <Badge status={h.status} />
                </div>
              ))}
              {history.length === 0 && <p className="text-[12px] text-gray-400">No payroll history yet.</p>}
            </div>
          </div>
        </div>
      </div>
      {showAddStructure && <AddSalaryStructureModal employeeId={employeeId} onClose={() => setShowAddStructure(false)} onCreated={() => { setShowAddStructure(false); load(); onChanged(); }} showToast={showToast} />}
    </div>
  );
};

const AddSalaryStructureModal: React.FC<{ employeeId: string; onClose: () => void; onCreated: () => void; showToast: (m: string, t: 'success' | 'error') => void }> = ({ employeeId, onClose, onCreated, showToast }) => {
  const [effectiveFrom, setEffectiveFrom] = useState('');
  const [components, setComponents] = useState<P.SalaryComponentItem[]>([]);
  const [lines, setLines] = useState<{ component_id: string; calculation_type: string; amount: string; percentage: string; percentage_of_component_code: string }[]>([]);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => { P.listSalaryComponents().then(setComponents).catch(() => showToast('Failed to load salary components.', 'error')); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const addLine = () => setLines((prev) => [...prev, { component_id: '', calculation_type: 'FIXED_AMOUNT', amount: '0', percentage: '0', percentage_of_component_code: 'BASIC' }]);
  const updateLine = (idx: number, patch: Partial<(typeof lines)[0]>) => setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));

  const handleSave = async () => {
    if (!effectiveFrom || lines.length === 0) { showToast('Effective date and at least one component are required.', 'error'); return; }
    setIsSaving(true);
    try {
      await P.createSalaryStructure(employeeId, effectiveFrom, lines.map((l) => ({
        component_id: l.component_id, calculation_type: l.calculation_type,
        amount: l.calculation_type === 'FIXED_AMOUNT' ? l.amount : undefined,
        percentage: l.calculation_type === 'PERCENTAGE' ? l.percentage : undefined,
        percentage_of_component_code: l.calculation_type === 'PERCENTAGE' ? l.percentage_of_component_code : undefined,
      })));
      showToast('Salary structure created.', 'success');
      onCreated();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to create salary structure.', 'error');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto">
        <h3 className="text-[16px] font-semibold text-gray-900 dark:text-white mb-3">New Salary Structure</h3>
        <input type="date" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 text-[13px] bg-white dark:bg-gray-900 mb-3" />
        <div className="space-y-2">
          {lines.map((line, idx) => (
            <div key={idx} className="grid grid-cols-12 gap-1.5 items-center">
              <select value={line.component_id} onChange={(e) => updateLine(idx, { component_id: e.target.value })} className="col-span-4 border border-gray-300 dark:border-gray-600 rounded-md px-1.5 py-1.5 text-[12px] bg-white dark:bg-gray-900">
                <option value="">Component…</option>
                {components.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <select value={line.calculation_type} onChange={(e) => updateLine(idx, { calculation_type: e.target.value })} className="col-span-3 border border-gray-300 dark:border-gray-600 rounded-md px-1.5 py-1.5 text-[12px] bg-white dark:bg-gray-900">
                <option value="FIXED_AMOUNT">Fixed</option>
                <option value="PERCENTAGE">Percentage</option>
              </select>
              {line.calculation_type === 'FIXED_AMOUNT' ? (
                <input type="number" value={line.amount} onChange={(e) => updateLine(idx, { amount: e.target.value })} placeholder="Amount" className="col-span-5 border border-gray-300 dark:border-gray-600 rounded-md px-1.5 py-1.5 text-[12px] bg-white dark:bg-gray-900" />
              ) : (
                <>
                  <input type="number" value={line.percentage} onChange={(e) => updateLine(idx, { percentage: e.target.value })} placeholder="%" className="col-span-2 border border-gray-300 dark:border-gray-600 rounded-md px-1.5 py-1.5 text-[12px] bg-white dark:bg-gray-900" />
                  <input value={line.percentage_of_component_code} onChange={(e) => updateLine(idx, { percentage_of_component_code: e.target.value })} placeholder="of BASIC" className="col-span-3 border border-gray-300 dark:border-gray-600 rounded-md px-1.5 py-1.5 text-[12px] bg-white dark:bg-gray-900" />
                </>
              )}
            </div>
          ))}
        </div>
        <button onClick={addLine} className="flex items-center gap-1 text-[12px] text-[#0066ff] font-medium mt-2"><Plus size={14} /> Add Component</button>
        <div className="grid grid-cols-2 gap-3 mt-5">
          <button onClick={onClose} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Cancel</button>
          <button onClick={handleSave} disabled={isSaving} className="py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium disabled:opacity-60">{isSaving ? 'Saving…' : 'Create'}</button>
        </div>
      </div>
    </div>
  );
};

// --- Attendance ----------------------------------------------------------------

const ATTENDANCE_STATUSES = ['PRESENT', 'ABSENT', 'HALF_DAY', 'LEAVE', 'HOLIDAY', 'WEEK_OFF'];

const AttendanceTab: React.FC<{ showToast: (m: string, t: 'success' | 'error') => void; canManage: boolean }> = ({ showToast, canManage }) => {
  const [items, setItems] = useState<P.AttendanceItem[]>([]);
  const [employees, setEmployees] = useState<P.EmployeeListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [employeeId, setEmployeeId] = useState('');
  const [attendanceDate, setAttendanceDate] = useState('');
  const [status, setStatus] = useState('PRESENT');

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const [a, e] = await Promise.all([P.listAttendance(), P.listEmployees({ page_size: 100 })]);
      setItems(a);
      setEmployees(e.data);
    } catch {
      showToast('Failed to load attendance.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleRecord = async () => {
    if (!employeeId || !attendanceDate) { showToast('Employee and date are required.', 'error'); return; }
    try {
      await P.recordAttendance(employeeId, attendanceDate, status);
      showToast('Attendance recorded.', 'success');
      load();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to record attendance.', 'error');
    }
  };

  const employeeName = (id: string) => employees.find((e) => e.id === id)?.full_name || id;

  return (
    <div>
      {canManage && (
        <div className="flex flex-wrap items-center gap-2 mb-4 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-3">
          <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-md px-2.5 py-1.5 text-[13px] bg-white dark:bg-gray-800">
            <option value="">Employee…</option>
            {employees.map((e) => <option key={e.id} value={e.id}>{e.full_name}</option>)}
          </select>
          <input type="date" value={attendanceDate} onChange={(e) => setAttendanceDate(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-md px-2.5 py-1.5 text-[13px] bg-white dark:bg-gray-800" />
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-md px-2.5 py-1.5 text-[13px] bg-white dark:bg-gray-800">
            {ATTENDANCE_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <button onClick={handleRecord} className="px-3 py-1.5 rounded-md bg-[#0066ff] text-white text-[12px] font-medium">Record</button>
        </div>
      )}
      {isLoading ? <div className="flex items-center justify-center py-16"><LoadingState bare /></div> : (
        <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-[13px]">
              <thead className="bg-gray-50 dark:bg-gray-800"><tr>{['Employee', 'Date', 'Status', 'Notes'].map((h) => <th key={h} className="px-4 py-2.5 text-[11px] font-semibold text-gray-600 uppercase">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {items.map((a) => (
                  <tr key={a.id}><td className="px-4 py-2.5">{employeeName(a.employee_id)}</td><td className="px-4 py-2.5">{a.attendance_date}</td><td className="px-4 py-2.5"><Badge status={a.status} /></td><td className="px-4 py-2.5 text-gray-500">{a.notes || '—'}</td></tr>
                ))}
                {items.length === 0 && <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-400">No attendance recorded yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

// --- Leave -----------------------------------------------------------------------

const LeaveTab: React.FC<{ showToast: (m: string, t: 'success' | 'error') => void; canManage: boolean; canApprove: boolean }> = ({ showToast, canManage, canApprove }) => {
  const [items, setItems] = useState<P.LeaveItem[]>([]);
  const [employees, setEmployees] = useState<P.EmployeeListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [employeeId, setEmployeeId] = useState('');
  const [leaveType, setLeaveType] = useState('PAID');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const [l, e] = await Promise.all([P.listLeave(), P.listEmployees({ page_size: 100 })]);
      setItems(l);
      setEmployees(e.data);
    } catch {
      showToast('Failed to load leave requests.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    if (!employeeId || !fromDate || !toDate) { showToast('Employee and date range are required.', 'error'); return; }
    try {
      await P.createLeave(employeeId, leaveType, fromDate, toDate);
      showToast('Leave request created.', 'success');
      load();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to create leave request.', 'error');
    }
  };

  const handleDecision = async (id: string, approve: boolean) => {
    try {
      await (approve ? P.approveLeave(id) : P.rejectLeave(id));
      showToast(approve ? 'Leave approved.' : 'Leave rejected.', 'success');
      load();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Action failed.', 'error');
    }
  };

  const employeeName = (id: string) => employees.find((e) => e.id === id)?.full_name || id;

  return (
    <div>
      {canManage && (
        <div className="flex flex-wrap items-center gap-2 mb-4 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-3">
          <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-md px-2.5 py-1.5 text-[13px] bg-white dark:bg-gray-800">
            <option value="">Employee…</option>
            {employees.map((e) => <option key={e.id} value={e.id}>{e.full_name}</option>)}
          </select>
          <select value={leaveType} onChange={(e) => setLeaveType(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-md px-2.5 py-1.5 text-[13px] bg-white dark:bg-gray-800">
            <option value="PAID">Paid</option><option value="UNPAID">Unpaid</option>
          </select>
          <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-md px-2.5 py-1.5 text-[13px] bg-white dark:bg-gray-800" />
          <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-md px-2.5 py-1.5 text-[13px] bg-white dark:bg-gray-800" />
          <button onClick={handleCreate} className="px-3 py-1.5 rounded-md bg-[#0066ff] text-white text-[12px] font-medium">Request</button>
        </div>
      )}
      {isLoading ? <div className="flex items-center justify-center py-16"><LoadingState bare /></div> : (
        <div className="space-y-2">
          {items.map((l) => (
            <div key={l.id} className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 flex items-center justify-between flex-wrap gap-2">
              <div>
                <p className="font-medium text-gray-900 dark:text-white text-[14px]">{employeeName(l.employee_id)} — {l.leave_type}</p>
                <p className="text-[12px] text-gray-500">{l.from_date} → {l.to_date} ({l.days} day{l.days === '1.00' ? '' : 's'})</p>
              </div>
              <div className="flex items-center gap-2">
                <Badge status={l.status} />
                {canApprove && l.status === 'PENDING' && (
                  <>
                    <button onClick={() => handleDecision(l.id, true)} className="px-2.5 py-1 rounded-md border border-green-300 text-green-700 text-[12px] font-medium">Approve</button>
                    <button onClick={() => handleDecision(l.id, false)} className="px-2.5 py-1 rounded-md border border-red-300 text-red-700 text-[12px] font-medium">Reject</button>
                  </>
                )}
              </div>
            </div>
          ))}
          {items.length === 0 && <div className="text-center py-16 text-gray-400">No leave requests yet.</div>}
        </div>
      )}
    </div>
  );
};

// --- Payroll -----------------------------------------------------------------------

const PayrollTab: React.FC<{ showToast: (m: string, t: 'success' | 'error') => void; canRun: boolean; canFinalize: boolean; canViewPayslip: boolean }> = ({ showToast, canRun, canFinalize, canViewPayslip }) => {
  const [periods, setPeriods] = useState<P.PayrollPeriodItem[]>([]);
  const [runs, setRuns] = useState<P.PayrollRunItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showNewPeriod, setShowNewPeriod] = useState(false);
  const [viewingRunId, setViewingRunId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const [p, r] = await Promise.all([P.listPayrollPeriods(), P.listPayrollRuns()]);
      setPeriods(p);
      setRuns(r);
    } catch {
      showToast('Failed to load payroll data.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleStartRun = async (periodId: string) => {
    try {
      const run = await P.createPayrollRun(periodId);
      showToast('Payroll run created.', 'success');
      await load();
      setViewingRunId(run.id);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to start payroll run.', 'error');
    }
  };

  return (
    <div>
      {canRun && (
        <div className="mb-4">
          <button onClick={() => setShowNewPeriod(true)} className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 text-[13px] font-medium">
            <Plus size={14} /> New Payroll Period
          </button>
        </div>
      )}
      {isLoading ? <div className="flex items-center justify-center py-16"><LoadingState bare /></div> : (
        <>
          <div className="mb-4">
            <p className="text-[13px] font-semibold text-gray-800 dark:text-gray-100 mb-2">Payroll Periods</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
              {periods.map((p) => {
                const existingRun = runs.find((r) => r.payroll_period_id === p.id && r.status !== 'REVERSED');
                return (
                  <div key={p.id} className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
                    <div className="flex items-center justify-between mb-1"><p className="font-semibold text-gray-900 dark:text-white text-[14px]">{p.period_label}</p><Badge status={p.status} /></div>
                    <p className="text-[12px] text-gray-500 mb-2">{p.start_date} → {p.end_date}</p>
                    {existingRun ? (
                      <button onClick={() => setViewingRunId(existingRun.id)} className="text-[12px] text-[#0066ff] font-medium">View Run →</button>
                    ) : canRun ? (
                      <button onClick={() => handleStartRun(p.id)} className="text-[12px] text-[#0066ff] font-medium">Start Payroll Run →</button>
                    ) : null}
                  </div>
                );
              })}
              {periods.length === 0 && <p className="text-[13px] text-gray-400">No payroll periods yet.</p>}
            </div>
          </div>
        </>
      )}
      {showNewPeriod && <CreatePeriodModal onClose={() => setShowNewPeriod(false)} onCreated={() => { setShowNewPeriod(false); load(); }} showToast={showToast} />}
      {viewingRunId && <PayrollRunModal runId={viewingRunId} onClose={() => setViewingRunId(null)} onChanged={load} showToast={showToast} canFinalize={canFinalize} canViewPayslip={canViewPayslip} />}
    </div>
  );
};

const CreatePeriodModal: React.FC<{ onClose: () => void; onCreated: () => void; showToast: (m: string, t: 'success' | 'error') => void }> = ({ onClose, onCreated, showToast }) => {
  const [label, setLabel] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const handleSave = async () => {
    if (!label || !startDate || !endDate) { showToast('All fields are required.', 'error'); return; }
    setIsSaving(true);
    try {
      await P.createPayrollPeriod(label, startDate, endDate);
      showToast('Payroll period created.', 'success');
      onCreated();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to create payroll period.', 'error');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
        <h3 className="text-[16px] font-semibold text-gray-900 dark:text-white mb-3">New Payroll Period</h3>
        <div className="space-y-2">
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Label, e.g. 2026-04" className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 text-[13px] bg-white dark:bg-gray-900" />
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 text-[13px] bg-white dark:bg-gray-900" />
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 text-[13px] bg-white dark:bg-gray-900" />
        </div>
        <div className="grid grid-cols-2 gap-3 mt-5">
          <button onClick={onClose} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Cancel</button>
          <button onClick={handleSave} disabled={isSaving} className="py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium disabled:opacity-60">{isSaving ? 'Saving…' : 'Create'}</button>
        </div>
      </div>
    </div>
  );
};

const PayrollRunModal: React.FC<{ runId: string; onClose: () => void; onChanged: () => void; showToast: (m: string, t: 'success' | 'error') => void; canFinalize: boolean; canViewPayslip: boolean }> = ({ runId, onClose, onChanged, showToast, canFinalize, canViewPayslip }) => {
  const [run, setRun] = useState<P.PayrollRunItem | null>(null);
  const [records, setRecords] = useState<P.PayrollRecordItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isActing, setIsActing] = useState(false);
  const [viewingPayslipId, setViewingPayslipId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const r = await P.getPayrollRun(runId);
      setRun(r);
      setRecords(await P.listPayrollRecords(runId));
    } catch {
      showToast('Failed to load payroll run.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  useEffect(() => { load(); }, [load]);

  const handleCalculate = async () => {
    setIsActing(true);
    try {
      await P.calculatePayrollRun(runId);
      showToast('Payroll calculated.', 'success');
      await load();
      onChanged();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Calculation failed.', 'error');
    } finally {
      setIsActing(false);
    }
  };

  const handleFinalize = async () => {
    setIsActing(true);
    try {
      await P.finalizePayrollRun(runId);
      showToast('Payroll finalized.', 'success');
      await load();
      onChanged();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Finalization failed.', 'error');
    } finally {
      setIsActing(false);
    }
  };

  if (isLoading || !run) {
    return <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"><LoadingState bare /></div>;
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <div><h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">Payroll Run — {run.period_label}</h3></div>
          <button onClick={onClose}><X size={20} className="text-gray-400" /></button>
        </div>
        <div className="p-6 space-y-5 text-[14px]">
          <div className="flex items-center gap-2"><Badge status={run.status} />{run.accounting_posting_reference && <span className="text-[12px] text-gray-500">Journal: {run.accounting_posting_reference}</span>}</div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="Employees" value={String(run.employee_count)} />
            <StatCard label="Gross" value={`₹${run.total_gross}`} />
            <StatCard label="Deductions" value={`₹${run.total_deductions}`} />
            <StatCard label="Net" value={`₹${run.total_net}`} />
          </div>

          <div className="flex gap-2">
            {run.status === 'DRAFT' && canFinalize && <button disabled={isActing} onClick={handleCalculate} className="px-4 py-2 rounded-lg bg-[#0066ff] text-white text-[13px] font-medium disabled:opacity-60">Calculate</button>}
            {run.status === 'CALCULATED' && canFinalize && (
              <>
                <button disabled={isActing} onClick={handleCalculate} className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[13px] font-medium disabled:opacity-60">Recalculate</button>
                <button disabled={isActing} onClick={handleFinalize} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-green-600 hover:bg-green-700 text-white text-[13px] font-medium disabled:opacity-60"><CheckCircle2 size={14} /> Finalize</button>
              </>
            )}
            {run.status === 'FINALIZED' && <span className="flex items-center gap-1.5 text-[13px] text-green-600"><CheckCircle2 size={16} /> Finalized — immutable</span>}
          </div>

          <div>
            <p className="text-[13px] font-semibold text-gray-800 dark:text-gray-100 mb-2">Payroll Records</p>
            <div className="space-y-1.5">
              {records.map((r) => (
                <div key={r.id} className="flex items-center justify-between border border-gray-200 dark:border-gray-700 rounded-lg p-3 text-[13px]">
                  <div><p className="font-medium text-gray-900 dark:text-white">{r.employee_name_snapshot}</p><p className="text-[12px] text-gray-500">{r.employee_code_snapshot} · Payable {r.payable_days}/{r.calendar_days} days</p></div>
                  <div className="flex items-center gap-3">
                    <span className="text-gray-800 dark:text-gray-200 font-medium">₹{r.net_salary}</span>
                    {canViewPayslip && r.payslip_number && <button onClick={() => setViewingPayslipId(r.id)} className="text-[12px] text-[#0066ff] font-medium">Payslip</button>}
                  </div>
                </div>
              ))}
              {records.length === 0 && <p className="text-[12px] text-gray-400">Not calculated yet.</p>}
            </div>
          </div>
        </div>
      </div>
      {viewingPayslipId && <PayslipModal recordId={viewingPayslipId} onClose={() => setViewingPayslipId(null)} showToast={showToast} />}
    </div>
  );
};

const PayslipModal: React.FC<{ recordId: string; onClose: () => void; showToast: (m: string, t: 'success' | 'error') => void }> = ({ recordId, onClose, showToast }) => {
  const [payslip, setPayslip] = useState<P.PayslipDetail | null>(null);

  useEffect(() => {
    P.getPayslip(recordId).then(setPayslip).catch(() => showToast('Failed to load payslip.', 'error'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordId]);

  if (!payslip) return <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"><LoadingState bare /></div>;

  const earnings = payslip.lines.filter((l) => l.component_type === 'EARNING');
  const deductions = payslip.lines.filter((l) => l.component_type === 'DEDUCTION');

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-3"><h3 className="text-[16px] font-semibold text-gray-900 dark:text-white">Payslip</h3><button onClick={onClose}><X size={18} className="text-gray-400" /></button></div>
        <div className="text-[13px] space-y-3">
          <div><p className="font-mono text-gray-500">{payslip.payslip_number}</p><p className="text-gray-800 dark:text-gray-100 font-medium">{payslip.employee_name_snapshot} ({payslip.employee_code_snapshot})</p><p className="text-gray-500">{payslip.designation_snapshot || '—'} · Period {payslip.period_label}</p></div>
          <div className="grid grid-cols-3 gap-2 text-[12px] bg-gray-50 dark:bg-gray-900 rounded-md p-2"><span>Calendar: {payslip.calendar_days}</span><span>Payable: {payslip.payable_days}</span><span>Unpaid: {payslip.unpaid_leave_days}</span></div>
          <div>
            <p className="font-semibold text-gray-700 dark:text-gray-200 mb-1">Earnings</p>
            {earnings.map((l, i) => <div key={i} className="flex justify-between text-gray-600 dark:text-gray-300"><span>{l.component_name}</span><span>₹{l.amount}</span></div>)}
          </div>
          {deductions.length > 0 && (
            <div>
              <p className="font-semibold text-gray-700 dark:text-gray-200 mb-1">Deductions</p>
              {deductions.map((l, i) => <div key={i} className="flex justify-between text-gray-600 dark:text-gray-300"><span>{l.component_name}</span><span>₹{l.amount}</span></div>)}
            </div>
          )}
          <div className="border-t border-gray-200 dark:border-gray-700 pt-2 space-y-1">
            <div className="flex justify-between"><span>Gross</span><span>₹{payslip.gross_earnings}</span></div>
            <div className="flex justify-between font-semibold text-gray-900 dark:text-white"><span>Net Salary</span><span>₹{payslip.net_salary}</span></div>
          </div>
          <p className="text-[11px] text-gray-400 flex items-start gap-1"><AlertTriangle size={12} className="shrink-0 mt-0.5" /> Basic Payroll — Statutory PF/ESI/TDS not included.</p>
        </div>
      </div>
    </div>
  );
};

export default PayrollManagement;
