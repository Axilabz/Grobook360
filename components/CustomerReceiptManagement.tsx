import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, Plus, X, Loader2, AlertTriangle, CheckCircle2, Ban,
  ChevronLeft, ChevronRight, Eye, Wallet, Receipt as ReceiptIcon,
} from 'lucide-react';
import Input from './Input';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { useNavigation } from '../context/NavigationContext';
import MobileFilterToggle from '../shared/MobileFilterToggle';
import ExportButton from '../shared/ExportButton';
import { ApiError } from '../api/client';
import { Customer, getCustomer } from '../api/customers';
import { getSalesInvoice } from '../api/salesInvoices';
import CustomerSelector from '../shared/CustomerSelector';
import {
  PaymentListItem, PaymentDetail, PaymentMethod, ChequeStatus, OutstandingInvoiceItem,
  PAYMENT_METHODS, AllocationLineInput,
  listCustomerReceipts, getCustomerReceipt, getCustomerOutstandingInvoices,
  createCustomerReceipt, postCustomerReceipt, reverseCustomerReceipt, updateCustomerReceiptChequeStatus,
} from '../api/payments';

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  POSTED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  REVERSED: 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400',
};

const CHEQUE_BADGE: Record<string, string> = {
  PENDING: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  CLEARED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  BOUNCED: 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400',
};

const CustomerReceiptManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const { consumeParams } = useNavigation();
  const canCreate = hasPermission('customer_receipt.create');
  const canPost = hasPermission('customer_receipt.post');
  const canReverse = hasPermission('customer_receipt.reverse');

  const [items, setItems] = useState<PaymentListItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showMobileFilters, setShowMobileFilters] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [prefillInvoiceId, setPrefillInvoiceId] = useState<string | null>(null);
  const [viewingId, setViewingId] = useState<string | null>(null);

  // Arrived here via the Sales Invoice list/detail's "Record Collection"
  // shortcut — open the create form pre-scoped to that one invoice
  // (reuses this same create flow rather than a second, parallel form).
  useEffect(() => {
    const params = consumeParams('Customer Receipts');
    if (params?.createForInvoiceId) {
      setPrefillInvoiceId(params.createForInvoiceId);
      setShowCreateModal(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchReceipts = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listCustomerReceipts({ page, page_size: 10, search: search || undefined, status: statusFilter || undefined });
      setItems(result.data);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load customer receipts.', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [page, search, statusFilter, showToast]);

  useEffect(() => { fetchReceipts(); /* eslint-disable-next-line */ }, [page, statusFilter]);
  useEffect(() => {
    const timer = setTimeout(() => { setPage(1); fetchReceipts(); }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 flex flex-col md:flex-row justify-between items-stretch md:items-center gap-4 shadow-sm">
        <div className="flex items-center justify-between gap-3 md:block">
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">Customer Receipts</h2>
          <MobileFilterToggle open={showMobileFilters} onClick={() => setShowMobileFilters((v) => !v)} />
        </div>

        <div className={`${showMobileFilters ? 'flex' : 'hidden'} md:flex flex-col sm:flex-row gap-3 w-full md:w-auto`}>
          <div className="relative w-full sm:w-64">
            <input
              type="text" placeholder="Search receipt #, reference, customer…" value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500/50 text-[14px]"
            />
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
          </div>
          <select
            value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2"
          >
            <option value="">All Statuses</option>
            {['DRAFT', 'POSTED', 'REVERSED'].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <ExportButton
            resource="customer_receipts"
            exportPermission="customer_receipt.export"
            search={search || undefined}
            status={statusFilter || undefined}
            page={page}
            pageSize={10}
            totalItems={totalItems}
          />
          {canCreate && (
            <button onClick={() => setShowCreateModal(true)} className="bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[14px] px-4 py-2 rounded-lg flex items-center justify-center gap-2 whitespace-nowrap">
              <Plus size={16} /> New Receipt
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No customer receipts found.</div>
      ) : (
        <>
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    {[
                      { label: 'Receipt #', align: 'text-left' }, { label: 'Date', align: 'text-right' }, { label: 'Customer', align: 'text-left' },
                      { label: 'Method', align: 'text-left' }, { label: 'Amount', align: 'text-right' }, { label: 'Allocated', align: 'text-right' },
                      { label: 'Unallocated', align: 'text-right' }, { label: 'Status', align: 'text-left' }, { label: 'Created By', align: 'text-left' },
                      { label: 'Actions', align: 'text-center' },
                    ].map((h) => (
                      <th key={h.label} className={`px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider ${h.align}`}>{h.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {items.map((p) => (
                    <tr key={p.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap text-left">
                        <button onClick={() => setViewingId(p.id)} className="hover:text-[#0066ff] hover:underline">{p.payment_number}</button>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-right">{p.payment_date}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-left">{p.party_name}</td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">
                        {p.payment_method}{p.payment_method === 'CHEQUE' && p.cheque_status && (
                          <span className={`ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${CHEQUE_BADGE[p.cheque_status]}`}>{p.cheque_status}</span>
                        )}
                      </td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">₹{p.amount}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">₹{p.allocated_amount}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">₹{p.unallocated_amount}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-left">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[p.status]}`}>{p.status}</span>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{p.created_by_name || '—'}</td>
                      <td className="px-6 py-4 text-center whitespace-nowrap">
                        <button onClick={() => setViewingId(p.id)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="View">
                          <Eye size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="md:hidden space-y-3">
            {items.map((p) => (
              <button key={p.id} onClick={() => setViewingId(p.id)} className="w-full text-left bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <p className="font-semibold text-gray-900 dark:text-white text-[15px]">{p.payment_number}</p>
                    <p className="text-[13px] text-gray-500 dark:text-gray-400">{p.party_name} · {p.payment_method}</p>
                  </div>
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[p.status]}`}>{p.status}</span>
                </div>
                <p className="text-[13px] text-gray-600 dark:text-gray-300">₹{p.amount} · Allocated ₹{p.allocated_amount} · {p.payment_date}</p>
              </button>
            ))}
          </div>

          <div className="flex items-center justify-between mt-4 px-1">
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{totalItems} receipt{totalItems === 1 ? '' : 's'}</p>
            <div className="flex items-center gap-2">
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronLeft size={16} /></button>
              <span className="text-[13px] text-gray-600 dark:text-gray-400">Page {page} of {totalPages}</span>
              <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronRight size={16} /></button>
            </div>
          </div>
        </>
      )}

      {showCreateModal && (
        <ReceiptFormModal
          initialInvoiceId={prefillInvoiceId}
          onClose={() => { setShowCreateModal(false); setPrefillInvoiceId(null); }}
          onSaved={() => { setShowCreateModal(false); setPrefillInvoiceId(null); fetchReceipts(); }}
        />
      )}

      {viewingId && (
        <ReceiptDetailModal
          paymentId={viewingId}
          onClose={() => setViewingId(null)}
          onChanged={fetchReceipts}
          permissions={{ canPost, canReverse }}
        />
      )}
    </div>
  );
};

const ReceiptFormModal: React.FC<{ initialInvoiceId?: string | null; onClose: () => void; onSaved: () => void }> = ({ initialInvoiceId, onClose, onSaved }) => {
  const { showToast } = useToast();
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [outstanding, setOutstanding] = useState<OutstandingInvoiceItem[]>([]);
  const [isLoadingOutstanding, setIsLoadingOutstanding] = useState(false);
  const [isLoadingPrefill, setIsLoadingPrefill] = useState(!!initialInvoiceId);
  const [paymentDate, setPaymentDate] = useState(new Date().toISOString().slice(0, 10));
  const [method, setMethod] = useState<PaymentMethod>('CASH');
  const [amount, setAmount] = useState('');
  const [referenceNumber, setReferenceNumber] = useState('');
  const [notes, setNotes] = useState('');
  const [chequeNumber, setChequeNumber] = useState('');
  const [chequeDate, setChequeDate] = useState('');
  const [chequeBankName, setChequeBankName] = useState('');
  const [allocations, setAllocations] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Pre-scope to one invoice when arriving from the Sales Invoice screen's
  // "Record Collection" shortcut — resolve the invoice's customer first
  // (CustomerSelector needs a full Customer object), then let the
  // outstanding-invoices effect below populate the allocation table as
  // usual and pre-fill this one invoice's row + the Amount field.
  useEffect(() => {
    if (!initialInvoiceId) return;
    let cancelled = false;
    (async () => {
      try {
        const invoice = await getSalesInvoice(initialInvoiceId);
        const cust = await getCustomer(invoice.customer_id);
        if (cancelled) return;
        setCustomer(cust);
        const outstandingAmount = (Number(invoice.grand_total) - Number(invoice.paid_amount)).toFixed(2);
        setAmount(outstandingAmount);
        setAllocations({ [initialInvoiceId]: outstandingAmount });
      } catch {
        if (!cancelled) showToast('Failed to load the selected invoice.', 'error');
      } finally {
        if (!cancelled) setIsLoadingPrefill(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialInvoiceId]);

  useEffect(() => {
    if (!customer) { setOutstanding([]); if (!initialInvoiceId) setAllocations({}); return; }
    setIsLoadingOutstanding(true);
    getCustomerOutstandingInvoices(customer.id)
      .then((res) => { setOutstanding(res.invoices); })
      .catch(() => setOutstanding([]))
      .finally(() => setIsLoadingOutstanding(false));
    // Only reset allocations when the customer changes AWAY from the
    // pre-filled invoice's own customer (e.g. user picks a different
    // customer manually) — don't clobber the prefill set above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customer]);

  const totalAllocated: number = (Object.values(allocations) as string[]).reduce((sum: number, v: string) => sum + (Number(v) || 0), 0) as number;
  const remaining = (Number(amount) || 0) - totalAllocated;

  const handleAllocateOldestFirst = () => {
    if (!amount) return;
    let left = Number(amount);
    const next: Record<string, string> = {};
    for (const inv of outstanding) {
      if (left <= 0) break;
      const take = Math.min(left, Number(inv.outstanding_amount));
      if (take > 0) { next[inv.invoice_id] = take.toFixed(2); left -= take; }
    }
    setAllocations(next);
  };

  const handleSave = async () => {
    if (!customer) { showToast('Select a customer.', 'error'); return; }
    if (!amount || Number(amount) <= 0) { showToast('Enter a valid amount.', 'error'); return; }
    if (method === 'CHEQUE' && (!chequeNumber || !chequeDate)) { showToast('Cheque number and date are required.', 'error'); return; }

    const allocationLines: AllocationLineInput[] = Object.entries(allocations)
      .filter(([, v]: [string, string]) => v && Number(v) > 0)
      .map(([invoice_id, allocated_amount]: [string, string]) => ({ invoice_id, allocated_amount }));

    setIsSubmitting(true);
    try {
      await createCustomerReceipt(customer.id, {
        payment_date: paymentDate || null, payment_method: method, amount,
        reference_number: referenceNumber || null, notes: notes || null,
        cheque_number: method === 'CHEQUE' ? chequeNumber : null,
        cheque_date: method === 'CHEQUE' ? chequeDate : null,
        cheque_bank_name: method === 'CHEQUE' ? chequeBankName || null : null,
        allocations: allocationLines,
      });
      showToast('Customer receipt created successfully.', 'success');
      onSaved();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.', 'error');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><Wallet size={18} /> New Customer Receipt</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>
        {isLoadingPrefill ? (
          <div className="flex justify-center py-16"><Loader2 size={24} className="animate-spin text-gray-400" /></div>
        ) : (
        <div className="p-6">
          {initialInvoiceId && (
            <p className="mb-4 text-[13px] text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-900/10 border border-green-200 dark:border-green-800 rounded-md px-3 py-2">
              Pre-filled for the invoice you selected — adjust the amount or allocation below if needed.
            </p>
          )}
          <CustomerSelector value={customer} onChange={setCustomer} />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4">
            <Input label="Receipt Date" type="date" value={paymentDate} onChange={(e) => setPaymentDate(e.target.value)} />
            <div>
              <label className="block text-[13px] font-medium text-gray-600 dark:text-gray-300 mb-1">Payment Method</label>
              <select
                value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)}
                className="w-full border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2"
              >
                {PAYMENT_METHODS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 mt-2">
            <Input label="Amount" type="number" min="0.01" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <Input label="Reference (Optional)" value={referenceNumber} onChange={(e) => setReferenceNumber(e.target.value)} />
          </div>

          {method === 'CHEQUE' && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-x-4 mt-2 p-3 rounded-md bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800">
              <Input label="Cheque Number" value={chequeNumber} onChange={(e) => setChequeNumber(e.target.value)} />
              <Input label="Cheque Date" type="date" value={chequeDate} onChange={(e) => setChequeDate(e.target.value)} />
              <Input label="Bank Name (Optional)" value={chequeBankName} onChange={(e) => setChequeBankName(e.target.value)} />
            </div>
          )}

          <div className="mt-3">
            <Input label="Notes (Optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          {customer && (
            <>
              <div className="flex items-center justify-between mt-5 mb-3">
                <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">Allocate Against Outstanding Invoices</h4>
                {outstanding.length > 0 && (
                  <button type="button" onClick={handleAllocateOldestFirst} className="text-[12px] text-blue-600 hover:underline">Allocate oldest first</button>
                )}
              </div>
              {isLoadingOutstanding ? (
                <div className="flex justify-center py-6"><Loader2 size={20} className="animate-spin text-gray-400" /></div>
              ) : outstanding.length === 0 ? (
                <p className="text-[13px] text-gray-400 italic">No outstanding invoices for this customer.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-[13px]">
                    <thead>
                      <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                        <th className="py-2 pr-2">Invoice</th><th className="py-2 pr-2">Date</th><th className="py-2 pr-2">Total</th>
                        <th className="py-2 pr-2">Paid</th><th className="py-2 pr-2">Outstanding</th><th className="py-2">Allocate</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                      {outstanding.map((inv) => (
                        <tr key={inv.invoice_id} className={inv.invoice_id === initialInvoiceId ? 'bg-green-50 dark:bg-green-900/10' : undefined}>
                          <td className="py-2 pr-2">{inv.invoice_number}</td>
                          <td className="py-2 pr-2">{inv.invoice_date}</td>
                          <td className="py-2 pr-2">₹{inv.invoice_total}</td>
                          <td className="py-2 pr-2">₹{inv.paid_amount}</td>
                          <td className="py-2 pr-2 font-medium">₹{inv.outstanding_amount}</td>
                          <td className="py-2">
                            <input
                              type="number" min="0" step="0.01" max={inv.outstanding_amount}
                              value={allocations[inv.invoice_id] || ''}
                              onChange={(e) => setAllocations((prev) => ({ ...prev, [inv.invoice_id]: e.target.value }))}
                              className="w-24 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-[13px] px-2 py-1"
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="text-[12px] text-gray-500 dark:text-gray-400 mt-2">
                Allocated: ₹{totalAllocated.toFixed(2)} · Remaining (on-account): ₹{remaining.toFixed(2)}
              </p>
            </>
          )}

          <button
            onClick={handleSave} disabled={isSubmitting}
            className="w-full mt-5 flex items-center justify-center gap-2 py-3 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[15px] font-medium disabled:opacity-70"
          >
            {isSubmitting && <Loader2 size={18} className="animate-spin" />} Save Receipt
          </button>
        </div>
        )}
      </div>
    </div>
  );
};

interface DetailPermissions { canPost: boolean; canReverse: boolean; }

const ReceiptDetailModal: React.FC<{ paymentId: string; onClose: () => void; onChanged: () => void; permissions: DetailPermissions }> = ({
  paymentId, onClose, onChanged, permissions,
}) => {
  const { showToast } = useToast();
  const [payment, setPayment] = useState<PaymentDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirmAction, setConfirmAction] = useState<'post' | 'reverse' | null>(null);
  const [chequeAction, setChequeAction] = useState<ChequeStatus | null>(null);
  const [isActing, setIsActing] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      setPayment(await getCustomerReceipt(paymentId));
    } catch {
      showToast('Failed to load receipt.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paymentId]);

  useEffect(() => { load(); }, [load]);

  const runAction = async (fn: () => Promise<unknown>, successMsg: string) => {
    setIsActing(true);
    try {
      await fn();
      showToast(successMsg, 'success');
      await load();
      onChanged();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Something went wrong.', 'error');
    } finally {
      setIsActing(false);
      setConfirmAction(null);
      setChequeAction(null);
    }
  };

  if (isLoading || !payment) {
    return (
      <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
        <Loader2 size={28} className="animate-spin text-white" />
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <div>
            <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{payment.payment_number}</h3>
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{payment.party_name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>

        <div className="p-6 space-y-5 text-[14px]">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[payment.status]}`}>{payment.status}</span>
            <span className="text-gray-500 dark:text-gray-400">Date: {payment.payment_date}</span>
            <span className="text-gray-500 dark:text-gray-400">· {payment.payment_method}</span>
            {payment.reference_number && <span className="text-gray-500 dark:text-gray-400">· Ref: {payment.reference_number}</span>}
          </div>

          {payment.payment_method === 'CHEQUE' && (
            <div className="rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/10 p-3 space-y-1">
              <p className="text-[13px] text-gray-700 dark:text-gray-200">
                Cheque #{payment.cheque_number} dated {payment.cheque_date} {payment.cheque_bank_name ? `(${payment.cheque_bank_name})` : ''}
              </p>
              <div className="flex items-center gap-2">
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${payment.cheque_status ? CHEQUE_BADGE[payment.cheque_status] : ''}`}>{payment.cheque_status}</span>
                {payment.cleared_date && <span className="text-[12px] text-gray-500">Cleared {payment.cleared_date}</span>}
              </div>
              {payment.status === 'POSTED' && payment.cheque_status === 'PENDING' && (
                <div className="flex gap-2 pt-1">
                  <button disabled={isActing} onClick={() => setChequeAction('CLEARED')} className="text-[12px] px-3 py-1.5 rounded-md bg-green-600 hover:bg-green-700 text-white font-medium">Mark Cleared</button>
                  <button disabled={isActing} onClick={() => setChequeAction('BOUNCED')} className="text-[12px] px-3 py-1.5 rounded-md bg-red-600 hover:bg-red-700 text-white font-medium">Mark Bounced</button>
                </div>
              )}
            </div>
          )}

          <div className="bg-gray-50 dark:bg-gray-900 rounded-md p-4 space-y-1 border border-gray-200 dark:border-gray-700">
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Amount</span><span>₹{payment.amount}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Allocated</span><span>₹{payment.allocated_amount}</span></div>
            <div className="flex justify-between font-semibold text-gray-900 dark:text-white pt-1 border-t border-gray-100 dark:border-gray-700">
              <span>Unallocated (On-Account)</span><span>₹{payment.unallocated_amount}</span>
            </div>
          </div>

          <div>
            <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2 flex items-center gap-1.5"><ReceiptIcon size={14} /> Allocations</h4>
            {payment.allocations.length === 0 ? (
              <p className="text-[13px] text-gray-400 italic">No allocations on this receipt.</p>
            ) : (
              <div className="space-y-1.5">
                {payment.allocations.map((a) => (
                  <div key={a.id} className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 rounded-md px-3 py-2 text-[13px] border border-gray-200 dark:border-gray-700">
                    <span className="text-gray-900 dark:text-white font-medium">{a.invoice_number}</span>
                    <span className="text-gray-500 dark:text-gray-400">₹{a.allocated_amount}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {payment.notes && <p className="text-gray-600 dark:text-gray-300"><span className="text-gray-400 text-[12px] uppercase block">Notes</span>{payment.notes}</p>}

          <div className="flex flex-wrap gap-2 pt-2">
            {permissions.canPost && payment.status === 'DRAFT' && (
              <button disabled={isActing} onClick={() => setConfirmAction('post')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium">
                <CheckCircle2 size={14} /> Post Receipt
              </button>
            )}
            {permissions.canReverse && payment.status === 'POSTED' && (
              <button disabled={isActing} onClick={() => setConfirmAction('reverse')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[13px] font-medium">
                <Ban size={14} /> Reverse
              </button>
            )}
          </div>
        </div>
      </div>

      {confirmAction && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
            <div className="flex items-center gap-3 mb-3">
              <div className={`flex h-10 w-10 items-center justify-center rounded-full shrink-0 ${confirmAction === 'post' ? 'bg-blue-100 dark:bg-blue-900/30' : 'bg-amber-100 dark:bg-amber-900/30'}`}>
                <AlertTriangle size={20} className={confirmAction === 'post' ? 'text-blue-600 dark:text-blue-400' : 'text-amber-600 dark:text-amber-400'} />
              </div>
              <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">{confirmAction === 'post' ? 'Post Receipt' : 'Reverse Receipt'}</h3>
            </div>
            <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-6">
              {confirmAction === 'post'
                ? 'This will apply the allocation to each selected invoice and reduce its outstanding balance.'
                : 'This will reverse the receipt in full, restoring outstanding balance on every allocated invoice. The original receipt record is never edited or deleted.'}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => setConfirmAction(null)} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Back</button>
              <button
                onClick={() => {
                  if (confirmAction === 'post') runAction(() => postCustomerReceipt(payment.id, payment.row_version), 'Receipt posted.');
                  else runAction(() => reverseCustomerReceipt(payment.id, payment.row_version), 'Receipt reversed.');
                }}
                className="py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium"
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}

      {chequeAction && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
            <div className="flex items-center gap-3 mb-3">
              <div className={`flex h-10 w-10 items-center justify-center rounded-full shrink-0 ${chequeAction === 'CLEARED' ? 'bg-green-100 dark:bg-green-900/30' : 'bg-red-100 dark:bg-red-900/30'}`}>
                <AlertTriangle size={20} className={chequeAction === 'CLEARED' ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'} />
              </div>
              <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">{chequeAction === 'CLEARED' ? 'Mark Cheque Cleared' : 'Mark Cheque Bounced'}</h3>
            </div>
            <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-6">
              {chequeAction === 'CLEARED'
                ? 'This confirms the cheque has cleared with the bank. No further financial change occurs — the receipt already reduced outstanding when posted.'
                : 'This will reverse the receipt in full — restoring outstanding on every allocated invoice — since a bounced cheque must not remain treated as a successful payment.'}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => setChequeAction(null)} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Back</button>
              <button
                onClick={() => runAction(
                  () => updateCustomerReceiptChequeStatus(payment.id, payment.row_version, chequeAction),
                  chequeAction === 'CLEARED' ? 'Cheque marked cleared.' : 'Cheque marked bounced — receipt reversed.',
                )}
                className={`py-2.5 rounded-lg text-white text-[14px] font-medium ${chequeAction === 'CLEARED' ? 'bg-green-600 hover:bg-green-700' : 'bg-red-600 hover:bg-red-700'}`}
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CustomerReceiptManagement;
