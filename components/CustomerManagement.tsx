import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, Plus, Pencil, UserCheck, UserX, ChevronLeft, ChevronRight, X, Loader2,
  AlertTriangle, Building2, User, MapPin, FileText, Eye, Navigation,
} from 'lucide-react';
import Input from './Input';
import Select from './Select';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import MobileFilterToggle from '../shared/MobileFilterToggle';
import { ApiError, ConcurrencyConflictError } from '../api/client';
import {
  Customer,
  CustomerFormPayload,
  listCustomers,
  createCustomer,
  updateCustomer,
  activateCustomer,
  deactivateCustomer,
} from '../api/customers';
import { GST_STATE_CODES, stateNameForCode, stateCodeForName } from '../shared/gstStateCodes';
import ExportButton from '../shared/ExportButton';
import MobileAccordionCard from '../shared/MobileAccordionCard';

const STATUS_BADGE: Record<string, string> = {
  ACTIVE: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  INACTIVE: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};

const CustomerManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  // Backend independently re-checks every call regardless of what this UI
  // shows (PROMPT-006 S27 pattern, carried into PROMPT-007).
  const canCreate = hasPermission('customers.create');
  const canEdit = hasPermission('customers.update');
  const canActivate = hasPermission('customers.activate');
  const canDeactivate = hasPermission('customers.deactivate');

  const [customers, setCustomers] = useState<Customer[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showMobileFilters, setShowMobileFilters] = useState(false);
  const [gstFilter, setGstFilter] = useState(''); // '', 'registered', 'unregistered'
  const [isLoading, setIsLoading] = useState(true);

  const [showAddModal, setShowAddModal] = useState(false);
  const [editingCustomer, setEditingCustomer] = useState<Customer | null>(null);
  const [viewingCustomer, setViewingCustomer] = useState<Customer | null>(null);
  const [confirmAction, setConfirmAction] = useState<{ customer: Customer; type: 'activate' | 'deactivate' } | null>(null);

  const fetchCustomers = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listCustomers({
        page,
        page_size: 10,
        search: search || undefined,
        status: statusFilter || undefined,
        gst_registered: gstFilter === '' ? undefined : gstFilter === 'registered',
      });
      setCustomers(result.data);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load customers.', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [page, search, statusFilter, gstFilter, showToast]);

  useEffect(() => {
    fetchCustomers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, statusFilter, gstFilter]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setPage(1);
      fetchCustomers();
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const handleConfirmStatusChange = async () => {
    if (!confirmAction) return;
    const { customer, type } = confirmAction;
    try {
      if (type === 'activate') {
        await activateCustomer(customer.id, customer.row_version);
      } else {
        await deactivateCustomer(customer.id, customer.row_version);
      }
      showToast(`Customer ${type === 'activate' ? 'activated' : 'deactivated'} successfully.`, 'success');
      setConfirmAction(null);
      fetchCustomers();
    } catch (err) {
      if (err instanceof ConcurrencyConflictError) {
        showToast('This customer was updated by someone else. Refresh and try again.', 'error');
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
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">Customers</h2>
          <MobileFilterToggle open={showMobileFilters} onClick={() => setShowMobileFilters((v) => !v)} />
        </div>

        <div className={`${showMobileFilters ? 'flex' : 'hidden'} md:flex flex-col sm:flex-row gap-3 w-full md:w-auto`}>
          <div className="relative w-full sm:w-64">
            <input
              type="text"
              placeholder="Search name, code, GSTIN, phone…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-colors text-[14px]"
            />
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
          </div>

          <select
            value={gstFilter}
            onChange={(e) => { setGstFilter(e.target.value); setPage(1); }}
            className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2"
          >
            <option value="">All GST Types</option>
            <option value="registered">GST Registered</option>
            <option value="unregistered">Unregistered</option>
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

          <ExportButton
            resource="customers"
            exportPermission="customers.export"
            search={search || undefined}
            status={statusFilter || undefined}
            page={page}
            pageSize={10}
            totalItems={totalItems}
          />

          {canCreate && (
            <button
              onClick={() => setShowAddModal(true)}
              className="bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[14px] px-4 py-2 rounded-lg transition-colors flex items-center justify-center gap-2 whitespace-nowrap"
            >
              <Plus size={16} /> Add Customer
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={28} className="animate-spin text-gray-400" />
        </div>
      ) : customers.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No customers found.</div>
      ) : (
        <>
          {/* Desktop / tablet table */}
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">Code</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">Name</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">Phone</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">GSTIN</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">Balance</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">Status</th>
                    <th className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider text-center">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {customers.map((customer) => (
                    <tr key={customer.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap">{customer.customer_code}</td>
                      <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap">
                        <button onClick={() => setViewingCustomer(customer)} className="hover:text-[#0066ff] hover:underline text-left">
                          {customer.name}
                        </button>
                        {customer.is_over_credit_limit && (
                          <span title="Balance exceeds credit limit" className="ml-2 inline-flex"><AlertTriangle size={14} className="text-amber-500" /></span>
                        )}
                      </td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">{customer.phone || '—'}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">{customer.gstin || <span className="text-gray-400 italic">Unregistered</span>}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">₹{customer.balance}</td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[customer.status]}`}>
                          {customer.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-center whitespace-nowrap">
                        <div className="flex items-center justify-center gap-2">
                          <button onClick={() => setViewingCustomer(customer)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="View">
                            <Eye size={16} />
                          </button>
                          {canEdit && (
                            <button onClick={() => setEditingCustomer(customer)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="Edit">
                              <Pencil size={16} />
                            </button>
                          )}
                          {customer.status === 'ACTIVE'
                            ? canDeactivate && (
                                <button onClick={() => setConfirmAction({ customer, type: 'deactivate' })} className="p-1.5 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500" title="Deactivate">
                                  <UserX size={16} />
                                </button>
                              )
                            : canActivate && (
                                <button onClick={() => setConfirmAction({ customer, type: 'activate' })} className="p-1.5 rounded hover:bg-green-50 dark:hover:bg-green-900/20 text-green-600" title="Activate">
                                  <UserCheck size={16} />
                                </button>
                              )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Mobile cards */}
          <div className="md:hidden space-y-3">
            {customers.map((customer) => (
              <MobileAccordionCard
                key={customer.id}
                title={customer.name}
                subtitle={`${customer.customer_code} · ${customer.phone || '—'}`}
                badge={
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[customer.status]}`}>
                    {customer.status}
                  </span>
                }
              >
                <p className="text-[13px] text-gray-600 dark:text-gray-300 mb-3">
                  GSTIN: <span className="font-medium">{customer.gstin || 'Unregistered'}</span> · Balance: <span className="font-medium">₹{customer.balance}</span>
                  {customer.is_over_credit_limit && <AlertTriangle size={12} className="inline ml-1 text-amber-500" />}
                </p>
                <div className="flex gap-2">
                  <button onClick={() => setViewingCustomer(customer)} className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300">
                    <Eye size={14} /> View
                  </button>
                  {canEdit && (
                    <button onClick={() => setEditingCustomer(customer)} className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300">
                      <Pencil size={14} /> Edit
                    </button>
                  )}
                  {customer.status === 'ACTIVE'
                    ? canDeactivate && (
                        <button onClick={() => setConfirmAction({ customer, type: 'deactivate' })} className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-red-300 dark:border-red-800 text-red-600">
                          <UserX size={14} /> Deactivate
                        </button>
                      )
                    : canActivate && (
                        <button onClick={() => setConfirmAction({ customer, type: 'activate' })} className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-green-300 dark:border-green-800 text-green-600">
                          <UserCheck size={14} /> Activate
                        </button>
                      )}
                </div>
              </MobileAccordionCard>
            ))}
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between mt-4 px-1">
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{totalItems} customer{totalItems === 1 ? '' : 's'}</p>
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
        <CustomerFormModal
          mode="create"
          onClose={() => setShowAddModal(false)}
          onSaved={() => { setShowAddModal(false); fetchCustomers(); }}
        />
      )}

      {editingCustomer && (
        <CustomerFormModal
          mode="edit"
          customer={editingCustomer}
          onClose={() => setEditingCustomer(null)}
          onSaved={() => { setEditingCustomer(null); fetchCustomers(); }}
        />
      )}

      {viewingCustomer && (
        <CustomerDetailModal
          customer={viewingCustomer}
          onClose={() => setViewingCustomer(null)}
          onEdit={canEdit ? () => { setEditingCustomer(viewingCustomer); setViewingCustomer(null); } : undefined}
        />
      )}

      {confirmAction && (
        <ConfirmDialog
          title={confirmAction.type === 'activate' ? 'Activate Customer' : 'Deactivate Customer'}
          message={
            confirmAction.type === 'activate'
              ? `Activate ${confirmAction.customer.name}? They will become available for new transactions again.`
              : `Deactivate ${confirmAction.customer.name}? They cannot be used for new transactions; historical records are preserved.`
          }
          onCancel={() => setConfirmAction(null)}
          onConfirm={handleConfirmStatusChange}
        />
      )}
    </div>
  );
};

interface CustomerFormModalProps {
  mode: 'create' | 'edit';
  customer?: Customer;
  onClose: () => void;
  onSaved: () => void;
}

const CustomerFormModal: React.FC<CustomerFormModalProps> = ({ mode, customer, onClose, onSaved }) => {
  const { showToast } = useToast();
  const [name, setName] = useState(customer?.name || '');
  const [ownerName, setOwnerName] = useState(customer?.owner_name || '');
  const [phone, setPhone] = useState(customer?.phone || '');
  const [email, setEmail] = useState(customer?.email || '');
  const [gstin, setGstin] = useState(customer?.gstin || '');
  const [stateName, setStateName] = useState(stateNameForCode(customer?.state_code));
  const [address, setAddress] = useState(customer?.address || '');
  const [city, setCity] = useState(customer?.city || '');
  const [pincode, setPincode] = useState(customer?.pincode || '');
  const [region, setRegion] = useState(customer?.region || '');
  const [gpsLocation, setGpsLocation] = useState(customer?.gps_location || '');
  const [creditLimit, setCreditLimit] = useState(String(customer?.credit_limit ?? '0'));
  const [paymentTermsDays, setPaymentTermsDays] = useState(String(customer?.payment_terms_days ?? '0'));
  const [isLocating, setIsLocating] = useState(false);

  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isGstRegistered = gstin.trim().length > 0;

  const handleGetLocation = () => {
    if (!navigator.geolocation) {
      showToast('Geolocation is not supported by your browser', 'error');
      return;
    }
    setIsLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords;
        setGpsLocation(`https://www.google.com/maps?q=${latitude},${longitude}`);
        showToast('Location captured successfully!', 'success');
        setIsLocating(false);
      },
      () => {
        showToast('Unable to retrieve your location', 'error');
        setIsLocating(false);
      }
    );
  };

  const validate = (): boolean => {
    const next: Record<string, string> = {};
    if (!name.trim()) next.name = 'Customer name is required';
    if (!ownerName.trim()) next.ownerName = 'Owner name is required';
    if (!/^\d{10}$/.test(phone)) next.phone = 'Phone must be exactly 10 digits';
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) next.email = 'Invalid email format';
    if (gstin && !/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/.test(gstin)) next.gstin = 'Enter a valid GSTIN';
    if (pincode && !/^\d{6}$/.test(pincode)) next.pincode = 'Pincode must be exactly 6 digits';
    if (isGstRegistered) {
      const derivedCode = gstin.slice(0, 2);
      const selectedCode = stateCodeForName(stateName);
      if (selectedCode && selectedCode !== derivedCode) {
        next.state = 'Selected state does not match the state encoded in the GSTIN';
      }
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSubmit = async () => {
    if (!validate()) return;
    setIsSubmitting(true);
    const payload: CustomerFormPayload = {
      name,
      owner_name: ownerName,
      phone,
      email: email || null,
      gstin: gstin || null,
      state_code: stateCodeForName(stateName) || (gstin ? gstin.slice(0, 2) : null),
      address: address || null,
      city: city || null,
      pincode: pincode || null,
      region: region || null,
      gps_location: gpsLocation || null,
      credit_limit: creditLimit ? Number(creditLimit) : 0,
      payment_terms_days: paymentTermsDays ? Number(paymentTermsDays) : 0,
    };
    try {
      if (mode === 'create') {
        await createCustomer(payload);
        showToast('Customer created successfully.', 'success');
      } else if (customer) {
        await updateCustomer(customer.id, { ...payload, expected_row_version: customer.row_version });
        showToast('Customer updated successfully.', 'success');
      }
      onSaved();
    } catch (err) {
      if (err instanceof ConcurrencyConflictError) {
        showToast('This customer was updated by someone else. Refresh and try again.', 'error');
      } else if (err instanceof ApiError && err.code === 'CUST-002') {
        showToast('A customer with this GSTIN already exists.', 'error');
      } else {
        showToast(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.', 'error');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">
            {mode === 'create' ? 'Add Customer' : 'Edit Customer'}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X size={20} />
          </button>
        </div>
        <div className="p-6">
          {/* Basic Information */}
          <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4 flex items-center gap-2">
            <Building2 size={14} /> Basic Information
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4">
            <Input label="Customer / Business Name" value={name} onChange={(e) => setName(e.target.value)} error={errors.name} />
            <Input label="Owner Name" value={ownerName} onChange={(e) => setOwnerName(e.target.value)} error={errors.ownerName} />
          </div>

          {/* Contact Information */}
          <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4 mt-2 flex items-center gap-2">
            <User size={14} /> Contact Information
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4">
            <Input label="Phone Number" value={phone} maxLength={10} onChange={(e) => setPhone(e.target.value.replace(/\D/g, ''))} error={errors.phone} />
            <Input label="Email (Optional)" value={email} onChange={(e) => setEmail(e.target.value)} error={errors.email} />
          </div>

          {/* GST Information */}
          <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4 mt-2 flex items-center gap-2">
            <FileText size={14} /> GST Information
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4">
            <Input
              label="GSTIN (Optional — leave blank if unregistered)"
              value={gstin}
              maxLength={15}
              onChange={(e) => setGstin(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))}
              error={errors.gstin}
            />
            {/* GST-conditional UX (PROMPT-007 S48): state becomes relevant once
                a GSTIN is entered, since GST split logic needs it — server
                independently enforces the state/GSTIN match regardless. */}
            <Select
              label={isGstRegistered ? 'State (from GSTIN)' : 'State'}
              options={GST_STATE_CODES.map((s) => s.name)}
              value={stateName}
              onChange={setStateName}
              error={errors.state}
            />
          </div>
          {!isGstRegistered && (
            <p className="text-[12px] text-gray-400 dark:text-gray-500 -mt-8 mb-6">
              Blank GSTIN is treated as a non-GST/unregistered party for billing and GST reporting.
            </p>
          )}

          {/* Address */}
          <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4 mt-2 flex items-center gap-2">
            <MapPin size={14} /> Address
          </h4>
          <Input label="Address" value={address} onChange={(e) => setAddress(e.target.value)} />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-x-4">
            <Input label="City" value={city} onChange={(e) => setCity(e.target.value)} />
            <Input label="Pin Code" value={pincode} maxLength={6} onChange={(e) => setPincode(e.target.value.replace(/\D/g, ''))} error={errors.pincode} />
            <Input label="Region / Beat (Optional)" value={region} onChange={(e) => setRegion(e.target.value)} />
          </div>
          <Input
            label="GPS Location (Optional)"
            value={gpsLocation}
            onChange={(e) => setGpsLocation(e.target.value)}
            icon={<div className="bg-[#0066ff] hover:bg-blue-700 transition-colors p-1 rounded text-white" title="Capture Current Location">{isLocating ? <Loader2 size={16} className="animate-spin" /> : <Navigation size={16} />}</div>}
            onIconClick={handleGetLocation}
          />

          {/* Commercial Information */}
          <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-4 mt-2">
            Commercial Information
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4">
            <Input label="Credit Limit (₹)" type="number" min={0} value={creditLimit} onChange={(e) => setCreditLimit(e.target.value)} />
            <Input label="Payment Terms (Days)" type="number" min={0} value={paymentTermsDays} onChange={(e) => setPaymentTermsDays(e.target.value)} />
          </div>

          <button
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="w-full bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] py-3 rounded-lg transition-colors disabled:opacity-70 flex items-center justify-center gap-2"
          >
            {isSubmitting && <Loader2 size={18} className="animate-spin" />}
            {mode === 'create' ? 'Create Customer' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
};

const CustomerDetailModal: React.FC<{ customer: Customer; onClose: () => void; onEdit?: () => void }> = ({ customer, onClose, onEdit }) => (
  <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-lg max-h-[90vh] overflow-y-auto">
      <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
        <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{customer.name}</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
          <X size={20} />
        </button>
      </div>
      <div className="p-6 space-y-4 text-[14px]">
        <div className="flex items-center gap-2">
          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[customer.status]}`}>{customer.status}</span>
          <span className="text-gray-500 dark:text-gray-400">{customer.customer_code}</span>
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
          <div><dt className="text-gray-400 text-[12px] uppercase">Owner</dt><dd className="text-gray-900 dark:text-white">{customer.owner_name}</dd></div>
          <div><dt className="text-gray-400 text-[12px] uppercase">Phone</dt><dd className="text-gray-900 dark:text-white">{customer.phone || '—'}</dd></div>
          <div><dt className="text-gray-400 text-[12px] uppercase">Email</dt><dd className="text-gray-900 dark:text-white">{customer.email || '—'}</dd></div>
          <div><dt className="text-gray-400 text-[12px] uppercase">GSTIN</dt><dd className="text-gray-900 dark:text-white">{customer.gstin || 'Unregistered'}</dd></div>
          <div><dt className="text-gray-400 text-[12px] uppercase">State</dt><dd className="text-gray-900 dark:text-white">{stateNameForCode(customer.state_code) || '—'}</dd></div>
          <div><dt className="text-gray-400 text-[12px] uppercase">City / Pincode</dt><dd className="text-gray-900 dark:text-white">{[customer.city, customer.pincode].filter(Boolean).join(' / ') || '—'}</dd></div>
          <div className="col-span-2"><dt className="text-gray-400 text-[12px] uppercase">Address</dt><dd className="text-gray-900 dark:text-white">{customer.address || '—'}</dd></div>
          <div><dt className="text-gray-400 text-[12px] uppercase">Region</dt><dd className="text-gray-900 dark:text-white">{customer.region || '—'}</dd></div>
          <div><dt className="text-gray-400 text-[12px] uppercase">Credit Limit</dt><dd className="text-gray-900 dark:text-white">₹{customer.credit_limit}</dd></div>
          <div><dt className="text-gray-400 text-[12px] uppercase">Payment Terms</dt><dd className="text-gray-900 dark:text-white">{customer.payment_terms_days} days</dd></div>
          <div>
            <dt className="text-gray-400 text-[12px] uppercase">Balance</dt>
            <dd className="text-gray-900 dark:text-white flex items-center gap-1">
              ₹{customer.balance}
              {customer.is_over_credit_limit && (
                <span title="Balance exceeds credit limit"><AlertTriangle size={14} className="text-amber-500" /></span>
              )}
            </dd>
          </div>
          {customer.gps_location && (
            <div className="col-span-2">
              <dt className="text-gray-400 text-[12px] uppercase">Location</dt>
              <dd><a href={customer.gps_location} target="_blank" rel="noopener noreferrer" className="text-[#0066ff] hover:underline flex items-center gap-1"><MapPin size={14} /> View on map</a></dd>
            </div>
          )}
        </dl>
        {onEdit && (
          <button onClick={onEdit} className="w-full mt-2 flex items-center justify-center gap-2 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium hover:bg-gray-50 dark:hover:bg-gray-700">
            <Pencil size={14} /> Edit Customer
          </button>
        )}
      </div>
    </div>
  </div>
);

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

export default CustomerManagement;
