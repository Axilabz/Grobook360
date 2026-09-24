import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, Plus, X, Loader2, AlertTriangle, RotateCcw, CheckCircle2,
  Ban, ChevronLeft, ChevronRight, Eye, FileText,
} from 'lucide-react';
import Input from './Input';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { ApiError } from '../api/client';
import {
  SalesReturnListItem,
  SalesReturnDetail,
  ReturnReason,
  RETURN_REASONS,
  listSalesReturns,
  getSalesReturn,
  createSalesReturn,
  confirmSalesReturn,
  cancelSalesReturn,
} from '../api/salesReturns';
import { listSalesInvoices, SalesInvoiceListItem, ReturnEligibility, getReturnEligibility } from '../api/salesInvoices';

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  CONFIRMED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  CANCELLED: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
};

const ELIGIBLE_INVOICE_STATUSES = new Set(['POSTED']);

const SalesReturnManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const canCreate = hasPermission('sales_return.create');
  const canConfirm = hasPermission('sales_return.confirm');
  const canCancel = hasPermission('sales_return.cancel');

  const [items, setItems] = useState<SalesReturnListItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [viewingId, setViewingId] = useState<string | null>(null);

  const fetchReturns = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listSalesReturns({ page, page_size: 10, search: search || undefined, status: statusFilter || undefined });
      setItems(result.data);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load sales returns.', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [page, search, statusFilter, showToast]);

  useEffect(() => { fetchReturns(); /* eslint-disable-next-line */ }, [page, statusFilter]);
  useEffect(() => {
    const timer = setTimeout(() => { setPage(1); fetchReturns(); }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 flex flex-col md:flex-row justify-between items-stretch md:items-center gap-4 shadow-sm">
        <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">Sales Returns</h2>
        <div className="flex flex-col sm:flex-row gap-3 w-full md:w-auto">
          <div className="relative w-full sm:w-64">
            <input
              type="text" placeholder="Search return #, invoice, customer…" value={search}
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
            {['DRAFT', 'CONFIRMED', 'CANCELLED'].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          {canCreate && (
            <button onClick={() => setShowCreateModal(true)} className="bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[14px] px-4 py-2 rounded-lg flex items-center justify-center gap-2 whitespace-nowrap">
              <Plus size={16} /> New Sales Return
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No sales returns found.</div>
      ) : (
        <>
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    {['Return #', 'Date', 'Invoice', 'Customer', 'Qty', 'Value', 'Reason', 'Status', 'Actions'].map((h) => (
                      <th key={h} className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {items.map((ret) => (
                    <tr key={ret.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap">
                        <button onClick={() => setViewingId(ret.id)} className="hover:text-[#0066ff] hover:underline">{ret.return_number}</button>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap">{ret.return_date}</td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap">
                        <span className="inline-flex items-center gap-1"><FileText size={12} /> {ret.source_invoice_number}</span>
                      </td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">{ret.customer_name}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">{ret.total_return_quantity}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">₹{ret.grand_total}</td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap">{ret.return_reason}</td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[ret.status]}`}>{ret.status}</span>
                      </td>
                      <td className="px-6 py-4 text-center whitespace-nowrap">
                        <button onClick={() => setViewingId(ret.id)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="View">
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
            {items.map((ret) => (
              <button key={ret.id} onClick={() => setViewingId(ret.id)} className="w-full text-left bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <p className="font-semibold text-gray-900 dark:text-white text-[15px]">{ret.return_number}</p>
                    <p className="text-[13px] text-gray-500 dark:text-gray-400">{ret.customer_name} · {ret.source_invoice_number}</p>
                  </div>
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[ret.status]}`}>{ret.status}</span>
                </div>
                <p className="text-[13px] text-gray-600 dark:text-gray-300">Qty {ret.total_return_quantity} · ₹{ret.grand_total} · {ret.return_date}</p>
              </button>
            ))}
          </div>

          <div className="flex items-center justify-between mt-4 px-1">
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{totalItems} return{totalItems === 1 ? '' : 's'}</p>
            <div className="flex items-center gap-2">
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronLeft size={16} /></button>
              <span className="text-[13px] text-gray-600 dark:text-gray-400">Page {page} of {totalPages}</span>
              <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronRight size={16} /></button>
            </div>
          </div>
        </>
      )}

      {showCreateModal && (
        <ReturnFormModal onClose={() => setShowCreateModal(false)} onSaved={() => { setShowCreateModal(false); fetchReturns(); }} />
      )}

      {viewingId && (
        <ReturnDetailModal
          returnId={viewingId}
          onClose={() => setViewingId(null)}
          onChanged={fetchReturns}
          permissions={{ canConfirm, canCancel }}
        />
      )}
    </div>
  );
};

const ReturnFormModal: React.FC<{ onClose: () => void; onSaved: () => void }> = ({ onClose, onSaved }) => {
  const { showToast } = useToast();
  const [invoiceQuery, setInvoiceQuery] = useState('');
  const [invoiceResults, setInvoiceResults] = useState<SalesInvoiceListItem[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedInvoice, setSelectedInvoice] = useState<SalesInvoiceListItem | null>(null);
  const [eligibility, setEligibility] = useState<ReturnEligibility | null>(null);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [returnDate, setReturnDate] = useState(new Date().toISOString().slice(0, 10));
  const [reason, setReason] = useState<ReturnReason>('DAMAGED');
  const [reasonDescription, setReasonDescription] = useState('');
  const [notes, setNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoadingEligibility, setIsLoadingEligibility] = useState(false);

  useEffect(() => {
    if (!invoiceQuery || selectedInvoice) { setInvoiceResults([]); return; }
    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const result = await listSalesInvoices({ search: invoiceQuery, page_size: 10 });
        setInvoiceResults(result.data.filter((i) => ELIGIBLE_INVOICE_STATUSES.has(i.status)));
      } catch {
        setInvoiceResults([]);
      } finally {
        setIsSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [invoiceQuery, selectedInvoice]);

  const handleSelectInvoice = async (invoice: SalesInvoiceListItem) => {
    setSelectedInvoice(invoice);
    setInvoiceQuery('');
    setInvoiceResults([]);
    setIsLoadingEligibility(true);
    try {
      const data = await getReturnEligibility(invoice.id);
      setEligibility(data);
      const initialQuantities: Record<string, string> = {};
      data.lines.forEach((line) => { initialQuantities[line.source_invoice_line_id] = ''; });
      setQuantities(initialQuantities);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load return eligibility.', 'error');
      setSelectedInvoice(null);
    } finally {
      setIsLoadingEligibility(false);
    }
  };

  const handleSave = async () => {
    if (!eligibility) return;
    if (reason === 'OTHER' && !reasonDescription.trim()) {
      showToast('A reason description is required when the reason is "Other".', 'error');
      return;
    }
    const lines: { source_invoice_line_id: string; quantity: string }[] = Object.entries(quantities)
      .filter(([, qty]) => qty && Number(qty) > 0)
      .map(([source_invoice_line_id, quantity]) => ({ source_invoice_line_id, quantity: quantity as string }));

    if (lines.length === 0) { showToast('Enter a return quantity for at least one line.', 'error'); return; }

    for (const [lineId, qty] of Object.entries(quantities)) {
      const line = eligibility.lines.find((l) => l.source_invoice_line_id === lineId);
      if (line && qty && Number(qty) > Number(line.returnable_quantity)) {
        showToast(`Return quantity for ${line.description} exceeds returnable quantity (${line.returnable_quantity}).`, 'error');
        return;
      }
    }

    setIsSubmitting(true);
    try {
      await createSalesReturn({
        source_invoice_id: eligibility.source_invoice_id,
        return_date: returnDate || null,
        return_reason: reason,
        reason_description: reason === 'OTHER' ? reasonDescription : null,
        notes: notes || null,
        lines,
      });
      showToast('Sales return created successfully.', 'success');
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
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><RotateCcw size={18} /> New Sales Return</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>
        <div className="p-6">
          {!selectedInvoice ? (
            <div className="relative mb-6">
              <label className="block text-[13px] font-medium text-gray-600 dark:text-gray-400 mb-1.5">Sales Invoice</label>
              <div className="relative">
                <input
                  type="text" value={invoiceQuery} onChange={(e) => setInvoiceQuery(e.target.value)}
                  placeholder="Search invoice number or customer…"
                  className="w-full pl-9 pr-3 py-2.5 rounded-md border border-gray-300 dark:border-gray-600 text-[14px] bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:border-blue-500 focus:ring-blue-500"
                />
                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              </div>
              {invoiceQuery && (
                <div className="absolute z-30 mt-1 w-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md shadow-lg max-h-64 overflow-auto">
                  {isSearching ? (
                    <div className="flex justify-center py-4"><Loader2 size={18} className="animate-spin text-gray-400" /></div>
                  ) : invoiceResults.length === 0 ? (
                    <p className="px-3 py-3 text-[13px] text-gray-400 italic">No eligible invoices found (must be POSTED).</p>
                  ) : (
                    invoiceResults.map((invoice) => (
                      <button
                        type="button" key={invoice.id} onClick={() => handleSelectInvoice(invoice)}
                        className="w-full text-left px-3 py-2.5 hover:bg-blue-50 dark:hover:bg-gray-700 text-[13px] flex justify-between items-center"
                      >
                        <div>
                          <p className="font-medium text-gray-900 dark:text-white">{invoice.invoice_number}</p>
                          <p className="text-gray-500 dark:text-gray-400">{invoice.customer_name} · {invoice.status}</p>
                        </div>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          ) : isLoadingEligibility || !eligibility ? (
            <div className="flex justify-center py-8"><Loader2 size={24} className="animate-spin text-gray-400" /></div>
          ) : (
            <>
              <div className="flex items-center justify-between px-3 py-2.5 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 mb-4">
                <div>
                  <p className="text-[14px] font-medium text-gray-900 dark:text-white">{eligibility.source_invoice_number}</p>
                  <p className="text-[12px] text-gray-500 dark:text-gray-400">{eligibility.customer_name}</p>
                </div>
                <button onClick={() => { setSelectedInvoice(null); setEligibility(null); }} className="text-[12px] text-blue-600 hover:underline">Change</button>
              </div>

              <div className="grid grid-cols-2 gap-x-4">
                <Input label="Return Date" type="date" value={returnDate} onChange={(e) => setReturnDate(e.target.value)} />
                <div>
                  <label className="block text-[13px] font-medium text-gray-600 dark:text-gray-300 mb-1">Return Reason</label>
                  <select
                    value={reason} onChange={(e) => setReason(e.target.value as ReturnReason)}
                    className="w-full border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2"
                  >
                    {RETURN_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                  </select>
                </div>
              </div>

              {reason === 'OTHER' && (
                <div className="mt-2">
                  <Input label="Reason Description" value={reasonDescription} onChange={(e) => setReasonDescription(e.target.value)} />
                </div>
              )}

              <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 mt-4">Return Quantities</h4>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[13px]">
                  <thead>
                    <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                      <th className="py-2 pr-2">Product</th><th className="py-2 pr-2">Invoiced</th>
                      <th className="py-2 pr-2">Returned</th><th className="py-2 pr-2">Returnable</th><th className="py-2">Return Now</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                    {eligibility.lines.map((line) => (
                      <tr key={line.source_invoice_line_id}>
                        <td className="py-2 pr-2">{line.description} <span className="text-gray-400">({line.uom.code})</span></td>
                        <td className="py-2 pr-2">{line.original_quantity}</td>
                        <td className="py-2 pr-2">{line.previously_returned_quantity}</td>
                        <td className="py-2 pr-2 font-medium">{line.returnable_quantity}</td>
                        <td className="py-2">
                          <input
                            type="number" min="0" step="0.001" max={line.returnable_quantity}
                            value={quantities[line.source_invoice_line_id] || ''}
                            onChange={(e) => setQuantities((prev) => ({ ...prev, [line.source_invoice_line_id]: e.target.value }))}
                            className="w-24 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-[13px] px-2 py-1"
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mt-4 mb-4">
                <Input label="Notes (Optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
              </div>

              <p className="text-[12px] text-gray-400 mb-4">
                This action will add the returned quantity back to inventory when the return is confirmed.
              </p>

              <button
                onClick={handleSave} disabled={isSubmitting}
                className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[15px] font-medium disabled:opacity-70"
              >
                {isSubmitting && <Loader2 size={18} className="animate-spin" />} Save Sales Return
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

interface DetailPermissions {
  canConfirm: boolean; canCancel: boolean;
}

const ReturnDetailModal: React.FC<{ returnId: string; onClose: () => void; onChanged: () => void; permissions: DetailPermissions }> = ({
  returnId, onClose, onChanged, permissions,
}) => {
  const { showToast } = useToast();
  const [sales_return, setSalesReturn] = useState<SalesReturnDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirmAction, setConfirmAction] = useState<'confirm' | 'cancel' | null>(null);
  const [isActing, setIsActing] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await getSalesReturn(returnId);
      setSalesReturn(data);
    } catch {
      showToast('Failed to load sales return.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [returnId]);

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
    }
  };

  if (isLoading || !sales_return) {
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
            <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{sales_return.return_number}</h3>
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{sales_return.customer_name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>

        <div className="p-6 space-y-5 text-[14px]">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[sales_return.status]}`}>{sales_return.status}</span>
            <span className="text-gray-500 dark:text-gray-400">Date: {sales_return.return_date}</span>
            <span className="text-gray-500 dark:text-gray-400">· {sales_return.return_reason}</span>
            <span className="inline-flex items-center gap-1 text-purple-600 dark:text-purple-400 text-[12px]"><FileText size={12} /> From {sales_return.source_invoice_number}</span>
          </div>

          {sales_return.reason_description && (
            <p className="text-gray-600 dark:text-gray-300"><span className="text-gray-400 text-[12px] uppercase block">Reason Description</span>{sales_return.reason_description}</p>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                  <th className="py-2 pr-2">Product</th><th className="py-2 pr-2">HSN</th><th className="py-2 pr-2">Qty</th>
                  <th className="py-2 pr-2">Price</th><th className="py-2 pr-2">Disc.</th><th className="py-2 pr-2">Taxable</th>
                  <th className="py-2 pr-2">GST</th><th className="py-2">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {sales_return.lines.map((line) => (
                  <tr key={line.id}>
                    <td className="py-2 pr-2">{line.description}</td>
                    <td className="py-2 pr-2">{line.hsn_code || '—'}</td>
                    <td className="py-2 pr-2">{line.quantity} {line.uom.code}</td>
                    <td className="py-2 pr-2">₹{line.unit_price}</td>
                    <td className="py-2 pr-2">₹{line.discount_amount}</td>
                    <td className="py-2 pr-2">₹{line.taxable_amount}</td>
                    <td className="py-2 pr-2">₹{(Number(line.cgst_amount) + Number(line.sgst_amount) + Number(line.igst_amount)).toFixed(2)}</td>
                    <td className="py-2 font-medium">₹{line.line_total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="bg-gray-50 dark:bg-gray-900 rounded-md p-4 space-y-1 border border-gray-200 dark:border-gray-700">
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Subtotal</span><span>₹{sales_return.subtotal}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Discount</span><span>−₹{sales_return.discount_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Taxable Value</span><span>₹{sales_return.taxable_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>CGST</span><span>₹{sales_return.cgst_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>SGST</span><span>₹{sales_return.sgst_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>IGST</span><span>₹{sales_return.igst_total}</span></div>
            <div className="flex justify-between font-semibold text-gray-900 dark:text-white pt-1 border-t border-gray-100 dark:border-gray-700">
              <span>Total Return Value</span><span>₹{sales_return.grand_total}</span>
            </div>
          </div>

          {sales_return.status === 'CONFIRMED' && (
            <div className="text-[12px] text-gray-500 dark:text-gray-400 space-y-0.5">
              {sales_return.accounting_posting_reference && <p>Accounting reference: {sales_return.accounting_posting_reference}</p>}
              {sales_return.gst_transaction_reference && <p>GST transaction reference: {sales_return.gst_transaction_reference}</p>}
            </div>
          )}

          {sales_return.notes && <p className="text-gray-600 dark:text-gray-300"><span className="text-gray-400 text-[12px] uppercase block">Notes</span>{sales_return.notes}</p>}

          <div className="flex flex-wrap gap-2 pt-2">
            {permissions.canConfirm && sales_return.status === 'DRAFT' && (
              <button disabled={isActing} onClick={() => setConfirmAction('confirm')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium">
                <CheckCircle2 size={14} /> Confirm Return
              </button>
            )}
            {permissions.canCancel && sales_return.status === 'DRAFT' && (
              <button disabled={isActing} onClick={() => setConfirmAction('cancel')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[13px] font-medium">
                <Ban size={14} /> Cancel
              </button>
            )}
          </div>
        </div>
      </div>

      {confirmAction && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
            <div className="flex items-center gap-3 mb-3">
              <div className={`flex h-10 w-10 items-center justify-center rounded-full shrink-0 ${confirmAction === 'confirm' ? 'bg-blue-100 dark:bg-blue-900/30' : 'bg-amber-100 dark:bg-amber-900/30'}`}>
                <AlertTriangle size={20} className={confirmAction === 'confirm' ? 'text-blue-600 dark:text-blue-400' : 'text-amber-600 dark:text-amber-400'} />
              </div>
              <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">
                {confirmAction === 'confirm' ? 'Confirm Sales Return' : 'Cancel Sales Return'}
              </h3>
            </div>
            <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-6">
              {confirmAction === 'confirm'
                ? 'This action will add the returned quantity back to inventory and cannot be undone.'
                : 'This draft sales return will be cancelled. No stock, accounting, or GST impact has occurred yet.'}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => setConfirmAction(null)} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Back</button>
              <button
                onClick={() => {
                  if (confirmAction === 'confirm') runAction(() => confirmSalesReturn(sales_return.id, sales_return.row_version), 'Sales return confirmed — stock updated.');
                  else runAction(() => cancelSalesReturn(sales_return.id, sales_return.row_version), 'Sales return cancelled.');
                }}
                className="py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium"
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

export default SalesReturnManagement;
