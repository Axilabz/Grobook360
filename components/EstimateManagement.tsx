import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, Plus, X, Loader2, AlertTriangle, FileText, Send,
  Ban, ArrowRightCircle, ChevronLeft, ChevronRight, Eye, Trash2, History,
} from 'lucide-react';
import Input from './Input';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import MobileFilterToggle from '../shared/MobileFilterToggle';
import { ApiError } from '../api/client';
import {
  EstimateListItem,
  EstimateDetail,
  EstimateAuditEvent,
  listEstimates,
  getEstimate,
  getEstimateAuditHistory,
  createEstimate,
  sendEstimate,
  cancelEstimate,
  convertEstimate,
} from '../api/salesEstimates';
import { Customer } from '../api/customers';
import CustomerSelector from '../shared/CustomerSelector';
import ProductLineSelector, { SalesLineDraft } from '../shared/ProductLineSelector';
import LoadingState from '../shared/LoadingState';

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  SENT: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  ACCEPTED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  REJECTED: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  EXPIRED: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  CANCELLED: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
  CONVERTED: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
};

const ACTION_HISTORY_LABEL: Record<string, string> = {
  ESTIMATE_CREATED: 'Created', ESTIMATE_UPDATED: 'Updated', ESTIMATE_SENT: 'Sent',
  ESTIMATE_ACCEPTED: 'Accepted', ESTIMATE_REJECTED: 'Rejected', ESTIMATE_CANCELLED: 'Cancelled',
  ESTIMATE_CONVERTED: 'Converted to Sales Order',
};

// A line's own gst_rate is the FULL rate (CGST+SGST split it in half for
// intra-state, IGST uses it whole for inter-state) — only shown when every
// line shares one rate, since a mixed-rate estimate has no single percentage
// to display next to the header-level total.
function uniformGstRate(lines: EstimateDetail['lines']): number | null {
  if (lines.length === 0) return null;
  const first = Number(lines[0].gst_rate);
  return lines.every((l) => Number(l.gst_rate) === first) ? first : null;
}
function halfGstRateLabel(lines: EstimateDetail['lines']): string {
  const rate = uniformGstRate(lines);
  return rate === null ? '' : ` (${(rate / 2).toFixed(rate % 2 === 0 ? 0 : 1)}%)`;
}
function fullGstRateLabel(lines: EstimateDetail['lines']): string {
  const rate = uniformGstRate(lines);
  return rate === null ? '' : ` (${rate}%)`;
}

// Mirrors the backend's own state machine (app/services/sales/estimate_service.py)
// for UX only — the server independently enforces every transition.
const ACTION_ALLOWED_FROM: Record<string, string[]> = {
  send: ['DRAFT'],
  accept: ['SENT'],
  reject: ['SENT', 'ACCEPTED'],
  cancel: ['DRAFT', 'SENT', 'ACCEPTED'],
  convert: ['DRAFT', 'SENT', 'ACCEPTED'],
};

const EstimateManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const canCreate = hasPermission('sales_estimate.create');
  const canEdit = hasPermission('sales_estimate.edit');
  const canSend = hasPermission('sales_estimate.send');
  const canCancel = hasPermission('sales_estimate.cancel');
  const canConvert = hasPermission('sales_estimate.convert');

  const [items, setItems] = useState<EstimateListItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showMobileFilters, setShowMobileFilters] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [viewingId, setViewingId] = useState<string | null>(null);

  const fetchEstimates = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listEstimates({ page, page_size: 10, search: search || undefined, status: statusFilter || undefined });
      setItems(result.data);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load estimates.', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [page, search, statusFilter, showToast]);

  useEffect(() => { fetchEstimates(); /* eslint-disable-next-line */ }, [page, statusFilter]);
  useEffect(() => {
    const timer = setTimeout(() => { setPage(1); fetchEstimates(); }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 flex flex-col md:flex-row justify-between items-stretch md:items-center gap-4 shadow-sm">
        <div className="flex items-center justify-between gap-3 md:block">
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">Estimates</h2>
          <MobileFilterToggle open={showMobileFilters} onClick={() => setShowMobileFilters((v) => !v)} />
        </div>

        <div className={`${showMobileFilters ? 'flex' : 'hidden'} md:flex flex-col sm:flex-row gap-3 w-full md:w-auto`}>
          <div className="relative w-full sm:w-64">
            <input
              type="text" placeholder="Search estimate #, customer…" value={search}
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
            {['DRAFT', 'SENT', 'ACCEPTED', 'REJECTED', 'EXPIRED', 'CANCELLED', 'CONVERTED'].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          {canCreate && (
            <button onClick={() => setShowCreateModal(true)} className="bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[14px] px-4 py-2 rounded-lg flex items-center justify-center gap-2 whitespace-nowrap">
              <Plus size={16} /> New Estimate
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16"><LoadingState bare /></div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No estimates found.</div>
      ) : (
        <>
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    {/* Header labels are center-aligned; row cells below stay left/right/center per column type (text/date-number/icon) */}
                    {['Estimate #', 'Date', 'Customer', 'Valid Until', 'Amount', 'Status', 'Created By', 'Actions'].map((label) => (
                      <th key={label} className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider text-center">{label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {items.map((est) => (
                    <tr key={est.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap text-left">
                        <button onClick={() => setViewingId(est.id)} className="hover:text-[#0066ff] hover:underline">{est.estimate_number}</button>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-right">{est.document_date}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-left">{est.customer_name}</td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-right">{est.valid_until_date || '—'}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">₹{est.grand_total}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-left">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[est.status]}`}>{est.status}</span>
                        {est.is_expired_display && est.status !== 'EXPIRED' && <AlertTriangle size={12} className="inline ml-1.5 text-amber-500" />}
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{est.created_by_name || '—'}</td>
                      <td className="px-6 py-4 text-center whitespace-nowrap">
                        <button onClick={() => setViewingId(est.id)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="View">
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
            {items.map((est) => (
              <button key={est.id} onClick={() => setViewingId(est.id)} className="w-full text-left bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <p className="font-semibold text-gray-900 dark:text-white text-[15px]">{est.estimate_number}</p>
                    <p className="text-[13px] text-gray-500 dark:text-gray-400">{est.customer_name}</p>
                  </div>
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[est.status]}`}>{est.status}</span>
                </div>
                <p className="text-[13px] text-gray-600 dark:text-gray-300">₹{est.grand_total} · {est.document_date}</p>
              </button>
            ))}
          </div>

          <div className="flex items-center justify-between mt-4 px-1">
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{totalItems} estimate{totalItems === 1 ? '' : 's'}</p>
            <div className="flex items-center gap-2">
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronLeft size={16} /></button>
              <span className="text-[13px] text-gray-600 dark:text-gray-400">Page {page} of {totalPages}</span>
              <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronRight size={16} /></button>
            </div>
          </div>
        </>
      )}

      {showCreateModal && (
        <EstimateFormModal onClose={() => setShowCreateModal(false)} onSaved={() => { setShowCreateModal(false); fetchEstimates(); }} />
      )}

      {viewingId && (
        <EstimateDetailModal
          estimateId={viewingId}
          onClose={() => setViewingId(null)}
          onChanged={fetchEstimates}
          permissions={{ canSend, canCancel, canConvert }}
        />
      )}
    </div>
  );
};

const EstimateFormModal: React.FC<{ onClose: () => void; onSaved: () => void }> = ({ onClose, onSaved }) => {
  const { showToast } = useToast();
  const today = new Date().toISOString().slice(0, 10);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [documentDate, setDocumentDate] = useState(today);
  const [validUntilDate, setValidUntilDate] = useState('');
  const [notes, setNotes] = useState('');
  const [lines, setLines] = useState<SalesLineDraft[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleAddLine = (line: SalesLineDraft) => setLines((prev) => [...prev, line]);
  const handleRemoveLine = (index: number) => setLines((prev) => prev.filter((_, i) => i !== index));

  const estimatedGrandTotal = lines.reduce((sum, l) => {
    const gross = Number(l.quantity) * Number(l.unitPrice);
    const discount = l.discountAmount ? Number(l.discountAmount) : gross * (Number(l.discountPercent || 0) / 100);
    const taxable = Math.max(gross - discount, 0);
    const gstRate = l.product.gst_rate ? Number(l.product.gst_rate) : 0;
    return sum + taxable + taxable * (gstRate / 100);
  }, 0);

  const handleSave = async () => {
    if (!customer) { showToast('Select a customer.', 'error'); return; }
    if (lines.length === 0) { showToast('Add at least one product line.', 'error'); return; }
    setIsSubmitting(true);
    try {
      await createEstimate({
        customer_id: customer.id,
        document_date: documentDate || null,
        valid_until_date: validUntilDate || null,
        notes: notes || null,
        lines: lines.map((l) => {
          // ProductLineSelector always fills both fields with '0' as a
          // default; the backend rejects both being non-null at once, so
          // only forward whichever discount was actually entered.
          const hasAmount = Number(l.discountAmount) > 0;
          const hasPercent = Number(l.discountPercent) > 0;
          return {
            product_id: l.product.id,
            quantity: l.quantity,
            uom_id: l.uomId,
            unit_price: l.unitPrice,
            discount_percent: hasPercent && !hasAmount ? l.discountPercent : null,
            discount_amount: hasAmount ? l.discountAmount : null,
          };
        }),
      });
      showToast('Estimate created successfully.', 'success');
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
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><FileText size={18} /> New Estimate</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>
        <div className="p-6">
          <CustomerSelector value={customer} onChange={setCustomer} />

          <div className="grid grid-cols-2 gap-x-4">
            <Input
              label="Estimate Date" type="date" value={documentDate} min={today}
              onChange={(e) => {
                const next = e.target.value;
                setDocumentDate(next);
                // Valid Until can never be before the (possibly just-changed)
                // Estimate Date — clear it rather than silently leaving a
                // now-invalid value in place.
                if (validUntilDate && validUntilDate < next) setValidUntilDate('');
              }}
            />
            <Input
              label="Valid Until (Optional)" type="date" value={validUntilDate} min={documentDate || today}
              onChange={(e) => setValidUntilDate(e.target.value)}
            />
          </div>

          <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 mt-2">Product Lines</h4>
          <ProductLineSelector onAdd={handleAddLine} />

          {lines.length > 0 && (
            <div className="mt-4 space-y-2">
              {lines.map((line, index) => (
                <div key={index} className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 rounded-md px-3 py-2 text-[13px] border border-gray-200 dark:border-gray-700">
                  <div>
                    <p className="font-medium text-gray-900 dark:text-white">{line.product.name}</p>
                    <p className="text-gray-500 dark:text-gray-400">{line.quantity} {line.uomCode} × ₹{line.unitPrice}</p>
                  </div>
                  <button onClick={() => handleRemoveLine(index)} className="text-red-500 hover:text-red-700 p-1"><Trash2 size={14} /></button>
                </div>
              ))}
              <div className="flex justify-between font-semibold text-gray-900 dark:text-white text-[14px] pt-2 border-t border-gray-100 dark:border-gray-700">
                <span>Estimated Grand Total</span><span>₹{estimatedGrandTotal.toFixed(2)}</span>
              </div>
            </div>
          )}

          <div className="mt-4">
            <Input label="Notes (Optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          <button
            onClick={handleSave} disabled={isSubmitting}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[15px] font-medium disabled:opacity-70"
          >
            {isSubmitting && <Loader2 size={18} className="animate-spin" />} Save Estimate
          </button>
        </div>
      </div>
    </div>
  );
};

interface DetailPermissions {
  canSend: boolean; canCancel: boolean; canConvert: boolean;
}

const EstimateDetailModal: React.FC<{ estimateId: string; onClose: () => void; onChanged: () => void; permissions: DetailPermissions }> = ({
  estimateId, onClose, onChanged, permissions,
}) => {
  const { showToast } = useToast();
  const [estimate, setEstimate] = useState<EstimateDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirmAction, setConfirmAction] = useState<'cancel' | 'convert' | null>(null);
  const [isActing, setIsActing] = useState(false);
  const [history, setHistory] = useState<EstimateAuditEvent[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await getEstimate(estimateId);
      setEstimate(data);
    } catch {
      showToast('Failed to load estimate.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [estimateId]);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const data = await getEstimateAuditHistory(estimateId);
      setHistory(data.events);
    } catch {
      // Non-critical section — a failed fetch here shouldn't block the
      // rest of the estimate from being usable.
    } finally {
      setHistoryLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [estimateId]);

  useEffect(() => { load(); loadHistory(); }, [load, loadHistory]);

  const runAction = async (fn: () => Promise<unknown>, successMsg: string) => {
    setIsActing(true);
    try {
      await fn();
      showToast(successMsg, 'success');
      await load();
      await loadHistory();
      onChanged();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Something went wrong.', 'error');
    } finally {
      setIsActing(false);
      setConfirmAction(null);
    }
  };

  const runConvert = async () => {
    setIsActing(true);
    try {
      const result = await convertEstimate(estimate.id, estimate.row_version);
      showToast(result.message, 'success');
      await load();
      await loadHistory();
      onChanged();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Something went wrong.', 'error');
    } finally {
      setIsActing(false);
      setConfirmAction(null);
    }
  };

  if (isLoading || !estimate) {
    return (
      <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
        <LoadingState bare />
      </div>
    );
  }

  const allowed = (action: keyof typeof ACTION_ALLOWED_FROM) => ACTION_ALLOWED_FROM[action].includes(estimate.status);

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <div>
            <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{estimate.estimate_number}</h3>
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{estimate.customer_name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>

        <div className="p-6 space-y-5 text-[14px]">
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[estimate.status]}`}>{estimate.status}</span>
            <span className="text-gray-500 dark:text-gray-400">Date: {estimate.document_date}</span>
            {estimate.valid_until_date && <span className="text-gray-500 dark:text-gray-400">· Valid until: {estimate.valid_until_date}</span>}
          </div>

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
                {estimate.lines.map((line) => (
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
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Subtotal</span><span>₹{estimate.subtotal}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Discount</span><span>−₹{estimate.discount_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Taxable Value</span><span>₹{estimate.taxable_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>CGST{Number(estimate.cgst_total) > 0 ? halfGstRateLabel(estimate.lines) : ''}</span><span>₹{estimate.cgst_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>SGST{Number(estimate.sgst_total) > 0 ? halfGstRateLabel(estimate.lines) : ''}</span><span>₹{estimate.sgst_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>IGST{Number(estimate.igst_total) > 0 ? fullGstRateLabel(estimate.lines) : ''}</span><span>₹{estimate.igst_total}</span></div>
            <div className="flex justify-between font-semibold text-gray-900 dark:text-white pt-1 border-t border-gray-100 dark:border-gray-700">
              <span>Grand Total</span><span>₹{estimate.grand_total}</span>
            </div>
          </div>

          {estimate.notes && <p className="text-gray-600 dark:text-gray-300"><span className="text-gray-400 text-[12px] uppercase block">Notes</span>{estimate.notes}</p>}

          <div>
            <p className="text-gray-400 text-[12px] uppercase font-semibold flex items-center gap-1.5 mb-2"><History size={13} /> Action History</p>
            {historyLoading ? (
              <LoadingState bare compact />
            ) : history.length === 0 ? (
              <p className="text-[13px] text-gray-400">No history recorded.</p>
            ) : (
              <div className="space-y-2">
                {history.map((event) => (
                  <div key={event.id} className="flex items-start justify-between gap-3 text-[13px] border-b border-gray-50 dark:border-gray-800 pb-2 last:border-0">
                    <span className="text-gray-700 dark:text-gray-300 font-medium">{ACTION_HISTORY_LABEL[event.action] || event.action}</span>
                    <span className="text-gray-500 dark:text-gray-400 text-right">
                      {event.actor_name || 'System'} · {new Date(event.occurred_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="flex flex-wrap gap-2 pt-2">
            {permissions.canSend && allowed('send') && (
              <button disabled={isActing} onClick={() => runAction(() => sendEstimate(estimate.id, estimate.row_version), 'Estimate sent.')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-blue-300 dark:border-blue-800 text-blue-600 text-[13px] font-medium">
                <Send size={14} /> Send
              </button>
            )}
            {permissions.canCancel && allowed('cancel') && (
              <button disabled={isActing} onClick={() => setConfirmAction('cancel')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[13px] font-medium">
                <Ban size={14} /> Cancel
              </button>
            )}
            {permissions.canConvert && allowed('convert') && (
              <button disabled={isActing} onClick={() => setConfirmAction('convert')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium ml-auto">
                <ArrowRightCircle size={14} /> Convert to Sales Order
              </button>
            )}
          </div>
        </div>
      </div>

      {confirmAction && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/30 shrink-0"><AlertTriangle size={20} className="text-amber-600 dark:text-amber-400" /></div>
              <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">
                {confirmAction === 'convert' ? 'Convert to Sales Order' : 'Cancel Estimate'}
              </h3>
            </div>
            <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-6">
              {confirmAction === 'convert'
                ? 'This will create a new Sales Order from this estimate and mark the estimate as converted. This action cannot be undone.'
                : 'This estimate will be cancelled and can no longer be actioned.'}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => setConfirmAction(null)} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Cancel</button>
              <button
                onClick={() => {
                  if (confirmAction === 'convert') runConvert();
                  else runAction(() => cancelEstimate(estimate.id, estimate.row_version), 'Estimate cancelled.');
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

export default EstimateManagement;
