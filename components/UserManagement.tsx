import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Search, Plus, Pencil, UserCheck, UserX, ChevronLeft, ChevronRight, X, Loader2, AlertTriangle } from 'lucide-react';
import Input from './Input';
import Select from './Select';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import MobileFilterToggle from '../shared/MobileFilterToggle';
import MobileAccordionCard from '../shared/MobileAccordionCard';
import { ApiError, ConcurrencyConflictError } from '../api/client';
import {
  TenantUser,
  listUsers,
  createUser,
  updateUser,
  activateUser,
  deactivateUser,
} from '../api/users';

const ROLE_OPTIONS = ['OWNER', 'MANAGER', 'SALESPERSON'];
const STATUS_BADGE: Record<string, string> = {
  ACTIVE: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  INACTIVE: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};

const UserManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  // PROMPT-006 S27/S28: UI gating follows effective permissions, not a
  // hardcoded role string — the backend independently re-checks every call
  // regardless of what this UI shows.
  const canCreate = hasPermission('users.create');
  const canEdit = hasPermission('users.update');
  const canActivate = hasPermission('users.activate');
  const canDeactivate = hasPermission('users.deactivate');

  const [users, setUsers] = useState<TenantUser[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showMobileFilters, setShowMobileFilters] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const [showAddModal, setShowAddModal] = useState(false);
  const [editingUser, setEditingUser] = useState<TenantUser | null>(null);
  const [confirmAction, setConfirmAction] = useState<{ user: TenantUser; type: 'activate' | 'deactivate' } | null>(null);

  const fetchUsers = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listUsers({
        page,
        page_size: 10,
        search: search || undefined,
        role: roleFilter || undefined,
        status: statusFilter || undefined,
      });
      setUsers(result.data);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load users.', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [page, search, roleFilter, statusFilter, showToast]);

  useEffect(() => {
    fetchUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, roleFilter, statusFilter]);

  // Skip the first run: the page/status effect already loads the initial list,
  // so debouncing on mount would fire a duplicate request.
  const searchMountedRef = useRef(false);
  useEffect(() => {
    if (!searchMountedRef.current) {
      searchMountedRef.current = true;
      return;
    }
    const timer = setTimeout(() => {
      setPage(1);
      fetchUsers();
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const handleConfirmStatusChange = async () => {
    if (!confirmAction) return;
    const { user, type } = confirmAction;
    try {
      if (type === 'activate') {
        await activateUser(user.id, user.row_version!);
      } else {
        await deactivateUser(user.id, user.row_version!);
      }
      showToast(`User ${type === 'activate' ? 'activated' : 'deactivated'} successfully.`, 'success');
      setConfirmAction(null);
      fetchUsers();
    } catch (err) {
      if (err instanceof ConcurrencyConflictError) {
        showToast('This user was updated by someone else. Refresh and try again.', 'error');
      } else if (err instanceof ApiError && err.code === 'USR-004') {
        showToast('This tenant must always have at least one active Owner.', 'error');
      } else {
        showToast(err instanceof ApiError ? err.message : 'Something went wrong.', 'error');
      }
      setConfirmAction(null);
    }
  };

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 flex flex-col md:flex-row justify-between items-stretch md:items-center gap-4 shadow-sm">
        <div className="flex items-center justify-between gap-3 md:block">
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">User Management</h2>
          <MobileFilterToggle open={showMobileFilters} onClick={() => setShowMobileFilters((v) => !v)} />
        </div>

        <div className={`${showMobileFilters ? 'flex' : 'hidden'} md:flex flex-col sm:flex-row gap-3 w-full md:w-auto`}>
          <div className="relative w-full sm:w-64">
            <input
              type="text"
              placeholder="Search name, phone, email…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-colors text-[14px]"
            />
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
          </div>

          <select
            value={roleFilter}
            onChange={(e) => { setRoleFilter(e.target.value); setPage(1); }}
            className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2"
          >
            <option value="">All Roles</option>
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>

          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2"
          >
            <option value="">All Statuses</option>
            <option value="ACTIVE">Active</option>
            <option value="INACTIVE">Inactive</option>
          </select>

          {canCreate && (
            <button
              onClick={() => setShowAddModal(true)}
              className="bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[14px] px-4 py-2 rounded-lg transition-colors flex items-center justify-center gap-2 whitespace-nowrap"
            >
              <Plus size={16} /> Add User
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={28} className="animate-spin text-gray-400" />
        </div>
      ) : users.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No users found.</div>
      ) : (
        <>
          {/* Desktop / tablet table */}
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    {[
                      { label: 'Name', align: 'text-left' }, { label: 'Login Identifier', align: 'text-left' }, { label: 'Role', align: 'text-left' },
                      { label: 'Status', align: 'text-left' }, { label: 'Actions', align: 'text-center' },
                    ].map((h) => (
                      <th key={h.label} className={`px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider ${h.align}`}>{h.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {users.map((user) => (
                    <tr key={user.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap text-left">
                        {user.name || <span className="text-gray-400 italic">Not set</span>}
                      </td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-left">{user.phone}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-left">{user.role}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-left">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[user.status]}`}>
                          {user.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-center whitespace-nowrap">
                        {(canEdit || canActivate || canDeactivate) && (
                          <div className="flex items-center justify-center gap-2">
                            {canEdit && (
                              <button onClick={() => setEditingUser(user)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="Edit">
                                <Pencil size={16} />
                              </button>
                            )}
                            {user.status === 'ACTIVE'
                              ? canDeactivate && (
                                  <button onClick={() => setConfirmAction({ user, type: 'deactivate' })} className="p-1.5 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500" title="Deactivate">
                                    <UserX size={16} />
                                  </button>
                                )
                              : canActivate && (
                                  <button onClick={() => setConfirmAction({ user, type: 'activate' })} className="p-1.5 rounded hover:bg-green-50 dark:hover:bg-green-900/20 text-green-600" title="Activate">
                                    <UserCheck size={16} />
                                  </button>
                                )}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Mobile cards */}
          <div className="md:hidden space-y-3">
            {users.map((user) => (
              <MobileAccordionCard
                key={user.id}
                title={user.name || 'Not set'}
                subtitle={user.phone}
                badge={
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[user.status]}`}>
                    {user.status}
                  </span>
                }
              >
                <p className="text-[13px] text-gray-600 dark:text-gray-300 mb-3">Role: <span className="font-medium">{user.role}</span></p>
                {(canEdit || canActivate || canDeactivate) && (
                  <div className="flex gap-2">
                    {canEdit && (
                      <button
                        onClick={() => setEditingUser(user)}
                        className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300"
                      >
                        <Pencil size={14} /> Edit
                      </button>
                    )}
                    {user.status === 'ACTIVE'
                      ? canDeactivate && (
                          <button
                            onClick={() => setConfirmAction({ user, type: 'deactivate' })}
                            className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-red-300 dark:border-red-800 text-red-600"
                          >
                            <UserX size={14} /> Deactivate
                          </button>
                        )
                      : canActivate && (
                          <button
                            onClick={() => setConfirmAction({ user, type: 'activate' })}
                            className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-green-300 dark:border-green-800 text-green-600"
                          >
                            <UserCheck size={14} /> Activate
                          </button>
                        )}
                  </div>
                )}
              </MobileAccordionCard>
            ))}
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between mt-4 px-1">
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{totalItems} user{totalItems === 1 ? '' : 's'}</p>
            <div className="flex items-center gap-2">
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300">
                <ChevronLeft size={16} />
              </button>
              <span className="text-[13px] text-gray-600 dark:text-gray-400">Page {page} of {totalPages}</span>
              <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300">
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        </>
      )}

      {showAddModal && (
        <UserFormModal
          mode="create"
          onClose={() => setShowAddModal(false)}
          onSaved={() => { setShowAddModal(false); fetchUsers(); }}
        />
      )}

      {editingUser && (
        <UserFormModal
          mode="edit"
          user={editingUser}
          onClose={() => setEditingUser(null)}
          onSaved={() => { setEditingUser(null); fetchUsers(); }}
        />
      )}

      {confirmAction && (
        <ConfirmDialog
          title={confirmAction.type === 'activate' ? 'Activate User' : 'Deactivate User'}
          message={
            confirmAction.type === 'activate'
              ? `Activate ${confirmAction.user.name || confirmAction.user.phone}? They will be able to sign in again.`
              : `Deactivate ${confirmAction.user.name || confirmAction.user.phone}? They will no longer be able to sign in, and any active sessions will be signed out.`
          }
          onCancel={() => setConfirmAction(null)}
          onConfirm={handleConfirmStatusChange}
        />
      )}
    </div>
  );
};

interface UserFormModalProps {
  mode: 'create' | 'edit';
  user?: TenantUser;
  onClose: () => void;
  onSaved: () => void;
}

const UserFormModal: React.FC<UserFormModalProps> = ({ mode, user, onClose, onSaved }) => {
  const { showToast } = useToast();
  const [name, setName] = useState(user?.name || '');
  const [phone, setPhone] = useState(user?.phone || '');
  const [email, setEmail] = useState(user?.email || '');
  const [role, setRole] = useState(user?.role || 'SALESPERSON');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const validate = (): boolean => {
    const next: Record<string, string> = {};
    if (!name.trim()) next.name = 'Please enter a name';
    if (mode === 'create' && !/^\d{10}$/.test(phone)) next.phone = 'Phone must be exactly 10 digits';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) next.email = 'Invalid email format';
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSubmit = async () => {
    if (!validate()) return;
    setIsSubmitting(true);
    try {
      if (mode === 'create') {
        await createUser({ name, phone, email, role });
        showToast('User created. A password setup link has been sent.', 'success');
      } else if (user) {
        await updateUser(user.id, { name, email, role, expected_row_version: user.row_version! });
        showToast('User updated successfully.', 'success');
      }
      onSaved();
    } catch (err) {
      if (err instanceof ConcurrencyConflictError) {
        showToast('This user was updated by someone else. Refresh and try again.', 'error');
      } else if (err instanceof ApiError && err.code === 'USR-002') {
        showToast('A user with this login identifier already exists.', 'error');
      } else if (err instanceof ApiError && err.code === 'USR-004') {
        showToast('This tenant must always have at least one active Owner.', 'error');
      } else {
        showToast(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.', 'error');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-md max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">
            {mode === 'create' ? 'Add User' : 'Edit User'}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X size={20} />
          </button>
        </div>
        <div className="p-6">
          <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} error={errors.name} />
          <Input
            label="Phone Number"
            value={phone}
            maxLength={10}
            disabled={mode === 'edit'}
            onChange={(e) => setPhone(e.target.value.replace(/\D/g, ''))}
            error={errors.phone}
          />
          <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} error={errors.email} />
          <Select label="Role" options={ROLE_OPTIONS} value={role} onChange={setRole} />

          {mode === 'create' && (
            <p className="text-[12px] text-gray-400 dark:text-gray-500 -mt-8 mb-6">
              The new user will receive a link to set their own password — no password is set by you.
            </p>
          )}

          <button
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="w-full bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] py-3 rounded-lg transition-colors disabled:opacity-70 flex items-center justify-center gap-2"
          >
            {isSubmitting && <Loader2 size={18} className="animate-spin" />}
            {mode === 'create' ? 'Create User' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
};

const ConfirmDialog: React.FC<{ title: string; message: string; onCancel: () => void; onConfirm: () => void }> = ({
  title,
  message,
  onCancel,
  onConfirm,
}) => (
  <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
      <div className="flex items-center gap-3 mb-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/30 shrink-0">
          <AlertTriangle size={20} className="text-amber-600 dark:text-amber-400" />
        </div>
        <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">{title}</h3>
      </div>
      <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-6">{message}</p>
      <div className="grid grid-cols-2 gap-3">
        <button onClick={onCancel} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">
          Cancel
        </button>
        <button onClick={onConfirm} className="py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium">
          Confirm
        </button>
      </div>
    </div>
  </div>
);

export default UserManagement;
