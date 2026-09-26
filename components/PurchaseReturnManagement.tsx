import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, Plus, X, Loader2, AlertTriangle, RotateCcw, CheckCircle2,
  Ban, ChevronLeft, ChevronRight, Eye, FileText, Printer, History, PackageMinus,
} from 'lucide-react';
import Input from './Input';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import MobileFilterToggle from '../shared/MobileFilterToggle';
import { ApiError } from '../api/client';
import {
  PurchaseReturnListItem,
  PurchaseReturnDetail,
  PurchaseReturnReason,
  PurchaseReturnRelatedDocuments,
  PurchaseReturnAuditHistory,
  PURCHASE_RETURN_REASONS,
  listPurchaseReturns,
  getPurchaseReturn,
  createPurchaseReturn,
  confirmPurchaseReturn,
  cancelPurchaseReturn,
  getPurchaseReturnRelatedDocuments,
  getPurchaseReturnAuditHistory,
} from '../api/purchaseReturns';
import { listPurchaseInvoices, PurchaseInvoiceListItem, PurchaseReturnEligibility, getPurchaseReturnEligibility } from '../api/purchaseInvoices';

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  CONFIRMED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  CANCELLED: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
  POSTED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
};

const AUDIT_ACTION_LABEL: Record<string, string> = {
  PURCHASE_RETURN_CREATED: 'Created',
  PURCHASE_RETURN_UPDATED: 'Draft updated',
  PURCHASE_RETURN_CONFIRMED: 'Confirmed',
  PURCHASE_RETURN_CANCELLED: 'Cancelled',
};

const ELIGIBLE_INVOICE_STATUSES = new Set(['POSTED']);

const PurchaseReturnManagement: React.FC = () => {
  const { hasPermission, currentTenant } = useAuth();
  const { showToast } = useToast();
  const canCreate = hasPermission('purchase_return.create');
  const canConfirm = hasPermission('purchase_return.confirm');
  const canCancel = hasPermission('purchase_return.cancel');

  const [items, setItems] = useState<PurchaseReturnListItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showMobileFilters, setShowMobileFilters] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [viewingId, setViewingId] = useState<string | null>(null);

  const fetchReturns = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listPurchaseReturns({ page, page_size: 10, search: search || undefined, status: statusFilter || undefined });
      setItems(result.data);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load purchase returns.', 'error');
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
        <div className="flex items-center justify-between gap-3 md:block">
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">Purchase Returns</h2>
          <MobileFilterToggle open={showMobileFilters} onClick={() => setShowMobileFilters((v) => !v)} />
        </div>

        <div className={`${showMobileFilters ? 'flex' : 'hidden'} md:flex flex-col sm:flex-row gap-3 w-full md:w-auto`}>
          <div className="relative w-full sm:w-64">
            <input
              type="text" placeholder="Search return #, invoice, supplier…" value={search}
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
              <Plus size={16} /> New Purchase Return
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No purchase returns found.</div>
      ) : (
        <>
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    {[
                      { label: 'Return #', align: 'text-left' }, { label: 'Date', align: 'text-right' }, { label: 'Invoice', align: 'text-left' },
                      { label: 'Supplier', align: 'text-left' }, { label: 'Qty', align: 'text-right' }, { label: 'Value', align: 'text-right' },
                      { label: 'Reason', align: 'text-left' }, { label: 'Status', align: 'text-left' }, { label: 'Actions', align: 'text-center' },
                    ].map((h) => (
                      <th key={h.label} className={`px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider ${h.align}`}>{h.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {items.map((ret) => (
                    <tr key={ret.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap text-left">
                        <button onClick={() => setViewingId(ret.id)} className="hover:text-[#0066ff] hover:underline">{ret.purchase_return_number}</button>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-right">{ret.document_date}</td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">
                        <span className="inline-flex items-center gap-1"><FileText size={12} /> {ret.source_purchase_invoice_number}</span>
                      </td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-left">{ret.supplier_name}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">{ret.total_return_quantity}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">₹{ret.grand_total}</td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{ret.return_reason}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-left">
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
                    <p className="font-semibold text-gray-900 dark:text-white text-[15px]">{ret.purchase_return_number}</p>
                    <p className="text-[13px] text-gray-500 dark:text-gray-400">{ret.supplier_name} · {ret.source_purchase_invoice_number}</p>
                  </div>
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[ret.status]}`}>{ret.status}</span>
                </div>
                <p className="text-[13px] text-gray-600 dark:text-gray-300">Qty {ret.total_return_quantity} · ₹{ret.grand_total} · {ret.document_date}</p>
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
          businessName={currentTenant?.business_name || 'Your Business'}
        />
      )}
    </div>
  );
};

const ReturnFormModal: React.FC<{ onClose: () => void; onSaved: () => void }> = ({ onClose, onSaved }) => {
  const { showToast } = useToast();
  const [invoiceQuery, setInvoiceQuery] = useState('');
  const [invoiceResults, setInvoiceResults] = useState<PurchaseInvoiceListItem[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedInvoice, setSelectedInvoice] = useState<PurchaseInvoiceListItem | null>(null);
  const [eligibility, setEligibility] = useState<PurchaseReturnEligibility | null>(null);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [returnDate, setReturnDate] = useState(new Date().toISOString().slice(0, 10));
  const [reason, setReason] = useState<PurchaseReturnReason>('DAMAGED');
  const [reasonDescription, setReasonDescription] = useState('');
  const [notes, setNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoadingEligibility, setIsLoadingEligibility] = useState(false);

  useEffect(() => {
    if (!invoiceQuery || selectedInvoice) { setInvoiceResults([]); return; }
    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const result = await listPurchaseInvoices({ search: invoiceQuery, page_size: 10 });
        setInvoiceResults(result.data.filter((i) => ELIGIBLE_INVOICE_STATUSES.has(i.status)));
      } catch {
        setInvoiceResults([]);
      } finally {
        setIsSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [invoiceQuery, selectedInvoice]);

  const handleSelectInvoice = async (invoice: PurchaseInvoiceListItem) => {
    setSelectedInvoice(invoice);
    setInvoiceQuery('');
    setInvoiceResults([]);
    setIsLoadingEligibility(true);
    try {
      const data = await getPurchaseReturnEligibility(invoice.id);
      setEligibility(data);
      const initialQuantities: Record<string, string> = {};
      data.lines.forEach((line) => { initialQuantities[line.source_purchase_invoice_line_id] = ''; });
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
    const lines: { source_purchase_invoice_line_id: string; quantity: string }[] = Object.entries(quantities)
      .filter(([, qty]) => qty && Number(qty) > 0)
      .map(([source_purchase_invoice_line_id, quantity]) => ({ source_purchase_invoice_line_id, quantity: quantity as string }));

    if (lines.length === 0) { showToast('Enter a return quantity for at least one line.', 'error'); return; }

    for (const [lineId, qty] of Object.entries(quantities)) {
      const line = eligibility.lines.find((l) => l.source_purchase_invoice_line_id === lineId);
      if (line && qty && Number(qty) > Number(line.returnable_quantity)) {
        showToast(`Return quantity for ${line.description} exceeds returnable quantity (${line.returnable_quantity}).`, 'error');
        return;
      }
    }

    setIsSubmitting(true);
    try {
      await createPurchaseReturn({
        source_purchase_invoice_id: eligibility.source_purchase_invoice_id,
        document_date: returnDate || null,
        return_reason: reason,
        reason_description: reason === 'OTHER' ? reasonDescription : null,
        notes: notes || null,
        lines,
      });
      showToast('Purchase return created successfully.', 'success');
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
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><RotateCcw size={18} /> New Purchase Return</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>
        <div className="p-6">
          {!selectedInvoice ? (
            <div className="relative mb-6">
              <label className="block text-[13px] font-medium text-gray-600 dark:text-gray-400 mb-1.5">Purchase Invoice</label>
              <div className="relative">
                <input
                  type="text" value={invoiceQuery} onChange={(e) => setInvoiceQuery(e.target.value)}
                  placeholder="Search invoice number or supplier…"
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
                          <p className="font-medium text-gray-900 dark:text-white">{invoice.purchase_invoice_number}</p>
                          <p className="text-gray-500 dark:text-gray-400">{invoice.supplier_name} · {invoice.status}</p>
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
                  <p className="text-[14px] font-medium text-gray-900 dark:text-white">{eligibility.source_purchase_invoice_number}</p>
                  <p className="text-[12px] text-gray-500 dark:text-gray-400">{eligibility.supplier_name}</p>
                </div>
                <button onClick={() => { setSelectedInvoice(null); setEligibility(null); }} className="text-[12px] text-blue-600 hover:underline">Change</button>
              </div>

              <div className="grid grid-cols-2 gap-x-4">
                <Input label="Return Date" type="date" value={returnDate} onChange={(e) => setReturnDate(e.target.value)} />
                <div>
                  <label className="block text-[13px] font-medium text-gray-600 dark:text-gray-300 mb-1">Return Reason</label>
                  <select
                    value={reason} onChange={(e) => setReason(e.target.value as PurchaseReturnReason)}
                    className="w-full border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2"
                  >
                    {PURCHASE_RETURN_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
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
                      <tr key={line.source_purchase_invoice_line_id}>
                        <td className="py-2 pr-2">{line.description} <span className="text-gray-400">({line.uom.code})</span></td>
                        <td className="py-2 pr-2">{line.original_quantity}</td>
                        <td className="py-2 pr-2">{line.previously_returned_quantity}</td>
                        <td className="py-2 pr-2 font-medium">{line.returnable_quantity}</td>
                        <td className="py-2">
                          <input
                            type="number" min="0" step="0.001" max={line.returnable_quantity}
                            value={quantities[line.source_purchase_invoice_line_id] || ''}
                            onChange={(e) => setQuantities((prev) => ({ ...prev, [line.source_purchase_invoice_line_id]: e.target.value }))}
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
                This action will remove the returned quantity from inventory when the return is confirmed.
              </p>

              <button
                onClick={handleSave} disabled={isSubmitting}
                className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[15px] font-medium disabled:opacity-70"
              >
                {isSubmitting && <Loader2 size={18} className="animate-spin" />} Save Purchase Return
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

const ReturnDetailModal: React.FC<{ returnId: string; onClose: () => void; onChanged: () => void; permissions: DetailPermissions; businessName: string }> = ({
  returnId, onClose, onChanged, permissions, businessName,
}) => {
  const { showToast } = useToast();
  const [purchaseReturn, setPurchaseReturn] = useState<PurchaseReturnDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirmAction, setConfirmAction] = useState<'confirm' | 'cancel' | null>(null);
  const [isActing, setIsActing] = useState(false);
  const [related, setRelated] = useState<PurchaseReturnRelatedDocuments | null>(null);
  const [isLoadingRelated, setIsLoadingRelated] = useState(true);
  const [audit, setAudit] = useState<PurchaseReturnAuditHistory | null>(null);
  const [isLoadingAudit, setIsLoadingAudit] = useState(true);
  const [showPrintPreview, setShowPrintPreview] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await getPurchaseReturn(returnId);
      setPurchaseReturn(data);
    } catch {
      showToast('Failed to load purchase return.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [returnId]);

  const loadRelated = useCallback(async () => {
    setIsLoadingRelated(true);
    try {
      setRelated(await getPurchaseReturnRelatedDocuments(returnId));
    } catch {
      // non-critical section — fail silently, section just stays empty
    } finally {
      setIsLoadingRelated(false);
    }
  }, [returnId]);

  const loadAudit = useCallback(async () => {
    setIsLoadingAudit(true);
    try {
      setAudit(await getPurchaseReturnAuditHistory(returnId));
    } catch {
      // non-critical section — fail silently, section just stays empty
    } finally {
      setIsLoadingAudit(false);
    }
  }, [returnId]);

  useEffect(() => { load(); loadRelated(); loadAudit(); }, [load, loadRelated, loadAudit]);

  const runAction = async (fn: () => Promise<unknown>, successMsg: string) => {
    setIsActing(true);
    try {
      await fn();
      showToast(successMsg, 'success');
      await Promise.all([load(), loadRelated(), loadAudit()]);
      onChanged();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Something went wrong.', 'error');
    } finally {
      setIsActing(false);
      setConfirmAction(null);
    }
  };

  if (isLoading || !purchaseReturn) {
    return (
      <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
        <Loader2 size={28} className="animate-spin text-white" />
      </div>
    );
  }

  const isPostedCancellation = confirmAction === 'cancel' && purchaseReturn.status === 'CONFIRMED';

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <div>
            <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{purchaseReturn.purchase_return_number}</h3>
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{purchaseReturn.supplier_name}</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setShowPrintPreview(true)} className="p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-300" title="Print / Preview">
              <Printer size={18} />
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
          </div>
        </div>

        <div className="p-6 space-y-5 text-[14px]">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[purchaseReturn.status]}`}>{purchaseReturn.status}</span>
            <span className="text-gray-500 dark:text-gray-400">Date: {purchaseReturn.document_date}</span>
            <span className="text-gray-500 dark:text-gray-400">· {purchaseReturn.return_reason}</span>
            <span className="inline-flex items-center gap-1 text-purple-600 dark:text-purple-400 text-[12px]"><FileText size={12} /> From {purchaseReturn.source_purchase_invoice_number}</span>
          </div>

          {purchaseReturn.reason_description && (
            <p className="text-gray-600 dark:text-gray-300"><span className="text-gray-400 text-[12px] uppercase block">Reason Description</span>{purchaseReturn.reason_description}</p>
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
                {purchaseReturn.lines.map((line) => (
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
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Subtotal</span><span>₹{purchaseReturn.subtotal}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Discount</span><span>−₹{purchaseReturn.discount_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Taxable Value</span><span>₹{purchaseReturn.taxable_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>CGST</span><span>₹{purchaseReturn.cgst_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>SGST</span><span>₹{purchaseReturn.sgst_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>IGST</span><span>₹{purchaseReturn.igst_total}</span></div>
            <div className="flex justify-between font-semibold text-gray-900 dark:text-white pt-1 border-t border-gray-100 dark:border-gray-700">
              <span>Grand Total</span><span>₹{purchaseReturn.grand_total}</span>
            </div>
          </div>

          {/* --- Stock Impact (§18/§42/§43) --- */}
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
              <PackageMinus size={14} /> Stock Impact
            </h4>
            <p className="text-[13px] text-gray-600 dark:text-gray-300">
              <span className="font-medium text-red-600 dark:text-red-400">STOCK OUT</span> — goods are removed from inventory once this return is confirmed.
            </p>
            {purchaseReturn.status !== 'DRAFT' && (
              <div className="mt-2 space-y-1.5">
                {purchaseReturn.lines.map((line) => (
                  <div key={line.id} className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 rounded-md px-3 py-2 text-[13px] border border-gray-200 dark:border-gray-700">
                    <span className="text-gray-700 dark:text-gray-200">{line.description}</span>
                    {line.stock_movement_reversed ? (
                      <span className="inline-flex items-center gap-1 text-gray-400"><RotateCcw size={12} /> Reversed</span>
                    ) : line.stock_movement_id ? (
                      <span className="inline-flex items-center gap-1 text-red-600 dark:text-red-400"><PackageMinus size={12} /> −{line.quantity} {line.uom.code}</span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {purchaseReturn.notes && <p className="text-gray-600 dark:text-gray-300"><span className="text-gray-400 text-[12px] uppercase block">Notes</span>{purchaseReturn.notes}</p>}

          <div className="flex flex-wrap gap-2 pt-2">
            {permissions.canConfirm && purchaseReturn.status === 'DRAFT' && (
              <button disabled={isActing} onClick={() => setConfirmAction('confirm')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium">
                <CheckCircle2 size={14} /> Confirm Return
              </button>
            )}
            {permissions.canCancel && (purchaseReturn.status === 'DRAFT' || purchaseReturn.status === 'CONFIRMED') && (
              <button disabled={isActing} onClick={() => setConfirmAction('cancel')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[13px] font-medium">
                <Ban size={14} /> Cancel
              </button>
            )}
          </div>

          {/* --- Related Documents (§4/§44) --- */}
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
              <FileText size={14} /> Related Documents
            </h4>
            {isLoadingRelated ? (
              <div className="flex justify-center py-4"><Loader2 size={18} className="animate-spin text-gray-400" /></div>
            ) : related ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 rounded-md px-3 py-2 text-[13px] border border-gray-200 dark:border-gray-700">
                  <span className="inline-flex items-center gap-1 text-gray-900 dark:text-white font-medium"><FileText size={12} /> {related.source_purchase_invoice_number}</span>
                  <span className="text-gray-500 dark:text-gray-400">{related.source_purchase_invoice_status}</span>
                </div>
                {related.source_purchase_order_number && (
                  <div className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 rounded-md px-3 py-2 text-[13px] border border-gray-200 dark:border-gray-700">
                    <span className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400 font-medium"><FileText size={12} /> {related.source_purchase_order_number}</span>
                    <span className="text-gray-500 dark:text-gray-400">Source Purchase Order</span>
                  </div>
                )}
                {related.goods_receipts.length > 0 && (
                  <div className="space-y-1.5">
                    {related.goods_receipts.map((gr) => (
                      <div key={gr.id} className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 rounded-md px-3 py-2 text-[13px] border border-gray-200 dark:border-gray-700">
                        <span className="text-gray-900 dark:text-white font-medium">{gr.grn_number}</span>
                        <span className="text-gray-500 dark:text-gray-400">{gr.document_date}</span>
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${STATUS_BADGE[gr.status] || ''}`}>{gr.status}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-[13px] text-gray-400 italic">No related documents.</p>
            )}
          </div>

          {/* --- Audit History (§48) --- */}
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
              <History size={14} /> Audit History
            </h4>
            {isLoadingAudit ? (
              <div className="flex justify-center py-4"><Loader2 size={18} className="animate-spin text-gray-400" /></div>
            ) : audit && audit.events.length > 0 ? (
              <ul className="space-y-2">
                {audit.events.map((event) => (
                  <li key={event.id} className="flex items-start justify-between text-[13px] border-l-2 border-gray-200 dark:border-gray-700 pl-3">
                    <span className="text-gray-700 dark:text-gray-200">{AUDIT_ACTION_LABEL[event.action] || event.action}</span>
                    <span className="text-gray-400 text-[12px] whitespace-nowrap ml-2">{new Date(event.occurred_at).toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[13px] text-gray-400 italic">No audit events recorded yet.</p>
            )}
          </div>
        </div>
      </div>

      {showPrintPreview && (
        <PrPrintPreviewModal purchaseReturn={purchaseReturn} businessName={businessName} onClose={() => setShowPrintPreview(false)} />
      )}

      {confirmAction && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
            <div className="flex items-center gap-3 mb-3">
              <div className={`flex h-10 w-10 items-center justify-center rounded-full shrink-0 ${confirmAction === 'confirm' ? 'bg-blue-100 dark:bg-blue-900/30' : 'bg-amber-100 dark:bg-amber-900/30'}`}>
                <AlertTriangle size={20} className={confirmAction === 'confirm' ? 'text-blue-600 dark:text-blue-400' : 'text-amber-600 dark:text-amber-400'} />
              </div>
              <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">
                {confirmAction === 'confirm' ? 'Confirm Purchase Return' : isPostedCancellation ? 'Cancel Confirmed Return' : 'Cancel Purchase Return'}
              </h3>
            </div>
            <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-6">
              {confirmAction === 'confirm'
                ? 'This action will reduce inventory. Stock will be removed for every line on this return and cannot be undone directly (a cancellation-with-reversal will be required to undo it).'
                : isPostedCancellation
                ? 'This return already removed stock. Cancelling it will post a compensating Stock IN reversal and release its claim on the source invoice’s returnable quantity.'
                : 'This draft purchase return will be cancelled. No stock has been affected yet.'}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => setConfirmAction(null)} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Back</button>
              <button
                onClick={() => {
                  if (confirmAction === 'confirm') runAction(() => confirmPurchaseReturn(purchaseReturn.id, purchaseReturn.row_version), 'Purchase return confirmed — stock updated.');
                  else runAction(() => cancelPurchaseReturn(purchaseReturn.id, purchaseReturn.row_version), isPostedCancellation ? 'Purchase return cancelled — reversal applied.' : 'Purchase return cancelled.');
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

/** Print/Preview capability, mirrors Purchase Order/Goods Receipt/
 * Purchase Invoice's own print modals exactly. Explicitly headed
 * "PURCHASE RETURN", never any other document type. */
const PrPrintPreviewModal: React.FC<{ purchaseReturn: PurchaseReturnDetail; businessName: string; onClose: () => void }> = ({ purchaseReturn, businessName, onClose }) => {
  return (
    <div className="fixed inset-0 z-[70] bg-white dark:bg-gray-900 overflow-y-auto print:static">
      <div className="sticky top-0 z-20 flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 print:hidden">
        <h3 className="text-[16px] font-semibold text-gray-800 dark:text-gray-100">Print Preview</h3>
        <div className="flex items-center gap-2">
          <button onClick={() => window.print()} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium">
            <Printer size={14} /> Print
          </button>
          <button onClick={onClose} className="p-2 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-300"><X size={20} /></button>
        </div>
      </div>

      <div className="max-w-3xl mx-auto p-8 text-[13px] text-gray-800 dark:text-gray-100 print:text-black">
        <div className="text-center mb-6">
          <p className="text-[20px] font-bold tracking-wide">PURCHASE RETURN</p>
          <p className="text-gray-500 dark:text-gray-400 print:text-gray-600">{businessName}</p>
        </div>

        <div className="grid grid-cols-2 gap-6 mb-6">
          <div>
            <p className="text-[11px] uppercase text-gray-400 mb-1">Supplier</p>
            <p className="font-medium">{purchaseReturn.supplier_name}</p>
          </div>
          <div className="text-right">
            <p className="text-[11px] uppercase text-gray-400 mb-1">Return #</p>
            <p className="font-medium">{purchaseReturn.purchase_return_number}</p>
            <p className="text-gray-500 dark:text-gray-400 print:text-gray-600">{purchaseReturn.document_date}</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-6 mb-6 text-[12px]">
          <div>
            <p className="text-[11px] uppercase text-gray-400 mb-1">Source Invoice</p>
            <p>{purchaseReturn.source_purchase_invoice_number}</p>
          </div>
          <div className="text-right">
            <p className="text-[11px] uppercase text-gray-400 mb-1">Return Reason</p>
            <p>{purchaseReturn.return_reason}{purchaseReturn.reason_description ? ` — ${purchaseReturn.reason_description}` : ''}</p>
          </div>
        </div>

        <table className="w-full text-left border-collapse mb-6">
          <thead>
            <tr className="border-b border-gray-300 dark:border-gray-600 text-[11px] uppercase text-gray-500">
              <th className="py-2 pr-2">Product</th><th className="py-2 pr-2">HSN</th><th className="py-2 pr-2">Qty</th>
              <th className="py-2 pr-2">Price</th><th className="py-2 pr-2">Taxable</th><th className="py-2 pr-2">GST</th><th className="py-2">Total</th>
            </tr>
          </thead>
          <tbody>
            {purchaseReturn.lines.map((line) => (
              <tr key={line.id} className="border-b border-gray-100 dark:border-gray-800">
                <td className="py-2 pr-2">{line.description}</td>
                <td className="py-2 pr-2">{line.hsn_code || '—'}</td>
                <td className="py-2 pr-2">{line.quantity} {line.uom.code}</td>
                <td className="py-2 pr-2">₹{line.unit_price}</td>
                <td className="py-2 pr-2">₹{line.taxable_amount}</td>
                <td className="py-2 pr-2">₹{(Number(line.cgst_amount) + Number(line.sgst_amount) + Number(line.igst_amount)).toFixed(2)}</td>
                <td className="py-2">₹{line.line_total}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex justify-end mb-8">
          <div className="w-64 space-y-1">
            <div className="flex justify-between text-gray-500 dark:text-gray-400 print:text-gray-600"><span>Taxable Value</span><span>₹{purchaseReturn.taxable_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400 print:text-gray-600"><span>CGST</span><span>₹{purchaseReturn.cgst_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400 print:text-gray-600"><span>SGST</span><span>₹{purchaseReturn.sgst_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400 print:text-gray-600"><span>IGST</span><span>₹{purchaseReturn.igst_total}</span></div>
            <div className="flex justify-between font-semibold pt-1 border-t border-gray-200 dark:border-gray-700"><span>Grand Total</span><span>₹{purchaseReturn.grand_total}</span></div>
          </div>
        </div>

        {purchaseReturn.notes && (
          <div className="mb-8">
            <p className="text-[11px] uppercase text-gray-400 mb-1">Notes</p>
            <p>{purchaseReturn.notes}</p>
          </div>
        )}

        <p className="text-center text-[11px] text-gray-400 print:text-gray-500">This is a Purchase Return document. Not a Purchase Invoice or Credit Note.</p>
      </div>
    </div>
  );
};

export default PurchaseReturnManagement;
