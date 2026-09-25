import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, Plus, X, Loader2, AlertTriangle, Truck, CheckCircle2,
  Ban, ChevronLeft, ChevronRight, Eye, FileText, Receipt, Printer,
  History, PackagePlus, PackageMinus, RotateCcw,
} from 'lucide-react';
import Input from './Input';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import MobileFilterToggle from '../shared/MobileFilterToggle';
import { ApiError } from '../api/client';
import {
  GoodsReceiptListItem,
  GoodsReceiptDetail,
  GoodsReceiptRelatedDocuments,
  GoodsReceiptAuditHistory,
  listGoodsReceipts,
  getGoodsReceipt,
  createGoodsReceipt,
  confirmGoodsReceipt,
  cancelGoodsReceipt,
  InvoiceEligibility,
  getInvoiceEligibility,
  createInvoiceFromReceipt,
  getGoodsReceiptRelatedDocuments,
  getGoodsReceiptAuditHistory,
} from '../api/goodsReceipts';
import { listPurchaseOrders, PurchaseOrderListItem, ReceiptEligibility, getReceiptEligibility } from '../api/purchaseOrders';

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  CONFIRMED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  CANCELLED: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
  POSTED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
};

const AUDIT_ACTION_LABEL: Record<string, string> = {
  GOODS_RECEIPT_CREATED: 'Created',
  GOODS_RECEIPT_UPDATED: 'Draft updated',
  GOODS_RECEIPT_CONFIRMED: 'Confirmed — Stock IN posted',
  GOODS_RECEIPT_CANCELLED: 'Cancelled',
};

const ELIGIBLE_PO_STATUSES = new Set(['CONFIRMED', 'PARTIALLY_RECEIVED']);

const GoodsReceiptManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const canCreate = hasPermission('goods_receipt.create');
  const canConfirm = hasPermission('goods_receipt.confirm');
  const canCancel = hasPermission('goods_receipt.cancel');
  const canCreateInvoice = hasPermission('purchase_invoice.create');

  const [items, setItems] = useState<GoodsReceiptListItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showMobileFilters, setShowMobileFilters] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [viewingId, setViewingId] = useState<string | null>(null);

  const fetchReceipts = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listGoodsReceipts({ page, page_size: 10, search: search || undefined, status: statusFilter || undefined });
      setItems(result.data);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load goods receipts.', 'error');
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
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">Goods Receipts</h2>
          <MobileFilterToggle open={showMobileFilters} onClick={() => setShowMobileFilters((v) => !v)} />
        </div>

        <div className={`${showMobileFilters ? 'flex' : 'hidden'} md:flex flex-col sm:flex-row gap-3 w-full md:w-auto`}>
          <div className="relative w-full sm:w-64">
            <input
              type="text" placeholder="Search GRN #, order, supplier…" value={search}
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
              <Plus size={16} /> New Goods Receipt
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No goods receipts found.</div>
      ) : (
        <>
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    {['GRN #', 'Date', 'Purchase Order', 'Supplier', 'Total Qty', 'Status', 'Created By', 'Actions'].map((h) => (
                      <th key={h} className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {items.map((gr) => (
                    <tr key={gr.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap">
                        <button onClick={() => setViewingId(gr.id)} className="hover:text-[#0066ff] hover:underline">{gr.grn_number}</button>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap">{gr.document_date}</td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap">
                        <span className="inline-flex items-center gap-1"><FileText size={12} /> {gr.source_purchase_order_number || '—'}</span>
                      </td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">{gr.supplier_name}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">{gr.total_quantity}</td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[gr.status]}`}>{gr.status}</span>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap">{gr.created_by ? gr.created_by.slice(0, 8) : '—'}</td>
                      <td className="px-6 py-4 text-center whitespace-nowrap">
                        <button onClick={() => setViewingId(gr.id)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="View">
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
            {items.map((gr) => (
              <button key={gr.id} onClick={() => setViewingId(gr.id)} className="w-full text-left bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <p className="font-semibold text-gray-900 dark:text-white text-[15px]">{gr.grn_number}</p>
                    <p className="text-[13px] text-gray-500 dark:text-gray-400">{gr.supplier_name} · {gr.source_purchase_order_number || 'Ad-hoc'}</p>
                  </div>
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[gr.status]}`}>{gr.status}</span>
                </div>
                <p className="text-[13px] text-gray-600 dark:text-gray-300">Qty {gr.total_quantity} · {gr.document_date}</p>
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
        <ReceiptFormModal onClose={() => setShowCreateModal(false)} onSaved={() => { setShowCreateModal(false); fetchReceipts(); }} />
      )}

      {viewingId && (
        <ReceiptDetailModal
          receiptId={viewingId}
          onClose={() => setViewingId(null)}
          onChanged={fetchReceipts}
          permissions={{ canConfirm, canCancel, canCreateInvoice }}
        />
      )}
    </div>
  );
};

const ReceiptFormModal: React.FC<{ onClose: () => void; onSaved: () => void }> = ({ onClose, onSaved }) => {
  const { showToast } = useToast();
  const [poQuery, setPoQuery] = useState('');
  const [poResults, setPoResults] = useState<PurchaseOrderListItem[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedPo, setSelectedPo] = useState<PurchaseOrderListItem | null>(null);
  const [eligibility, setEligibility] = useState<ReceiptEligibility | null>(null);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [documentDate, setDocumentDate] = useState(new Date().toISOString().slice(0, 10));
  const [supplierDeliveryNote, setSupplierDeliveryNote] = useState('');
  const [notes, setNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoadingEligibility, setIsLoadingEligibility] = useState(false);

  useEffect(() => {
    if (!poQuery || selectedPo) { setPoResults([]); return; }
    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const result = await listPurchaseOrders({ search: poQuery, page_size: 10 });
        setPoResults(result.data.filter((o) => ELIGIBLE_PO_STATUSES.has(o.status)));
      } catch {
        setPoResults([]);
      } finally {
        setIsSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [poQuery, selectedPo]);

  const handleSelectPo = async (order: PurchaseOrderListItem) => {
    setSelectedPo(order);
    setPoQuery('');
    setPoResults([]);
    setIsLoadingEligibility(true);
    try {
      const data = await getReceiptEligibility(order.id);
      setEligibility(data);
      const initialQuantities: Record<string, string> = {};
      data.lines.forEach((line) => { initialQuantities[line.purchase_order_line_id] = ''; });
      setQuantities(initialQuantities);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load receipt eligibility.', 'error');
      setSelectedPo(null);
    } finally {
      setIsLoadingEligibility(false);
    }
  };

  const handleSave = async () => {
    if (!eligibility) return;
    const lines: { purchase_order_line_id: string; quantity: string }[] = Object.entries(quantities)
      .filter(([, qty]) => qty && Number(qty) > 0)
      .map(([purchase_order_line_id, quantity]) => ({ purchase_order_line_id, quantity: quantity as string }));

    if (lines.length === 0) { showToast('Enter a receipt quantity for at least one line.', 'error'); return; }

    for (const [lineId, qty] of Object.entries(quantities)) {
      const line = eligibility.lines.find((l) => l.purchase_order_line_id === lineId);
      if (line && qty && Number(qty) > Number(line.remaining_quantity)) {
        showToast(`Receipt quantity for ${line.description} exceeds remaining quantity (${line.remaining_quantity}).`, 'error');
        return;
      }
    }

    setIsSubmitting(true);
    try {
      await createGoodsReceipt({
        purchase_order_id: eligibility.purchase_order_id,
        document_date: documentDate || null,
        supplier_delivery_note: supplierDeliveryNote || null,
        notes: notes || null,
        lines,
      });
      showToast('Goods receipt created successfully.', 'success');
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
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><Truck size={18} /> New Goods Receipt</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>
        <div className="p-6">
          {!selectedPo ? (
            <div className="relative mb-6">
              <label className="block text-[13px] font-medium text-gray-600 dark:text-gray-400 mb-1.5">Purchase Order</label>
              <div className="relative">
                <input
                  type="text" value={poQuery} onChange={(e) => setPoQuery(e.target.value)}
                  placeholder="Search purchase order number or supplier…"
                  className="w-full pl-9 pr-3 py-2.5 rounded-md border border-gray-300 dark:border-gray-600 text-[14px] bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:border-blue-500 focus:ring-blue-500"
                />
                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              </div>
              {poQuery && (
                <div className="absolute z-30 mt-1 w-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md shadow-lg max-h-64 overflow-auto">
                  {isSearching ? (
                    <div className="flex justify-center py-4"><Loader2 size={18} className="animate-spin text-gray-400" /></div>
                  ) : poResults.length === 0 ? (
                    <p className="px-3 py-3 text-[13px] text-gray-400 italic">No eligible purchase orders found (must be CONFIRMED or PARTIALLY_RECEIVED).</p>
                  ) : (
                    poResults.map((order) => (
                      <button
                        type="button" key={order.id} onClick={() => handleSelectPo(order)}
                        className="w-full text-left px-3 py-2.5 hover:bg-blue-50 dark:hover:bg-gray-700 text-[13px] flex justify-between items-center"
                      >
                        <div>
                          <p className="font-medium text-gray-900 dark:text-white">{order.po_number}</p>
                          <p className="text-gray-500 dark:text-gray-400">{order.supplier_name} · {order.status.replace('_', ' ')}</p>
                        </div>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          ) : isLoadingEligibility ? (
            <div className="flex justify-center py-8"><Loader2 size={24} className="animate-spin text-gray-400" /></div>
          ) : eligibility ? (
            <>
              <div className="flex items-center justify-between px-3 py-2.5 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 mb-4">
                <div>
                  <p className="text-[14px] font-medium text-gray-900 dark:text-white">{eligibility.purchase_order_number}</p>
                  <p className="text-[12px] text-gray-500 dark:text-gray-400">{eligibility.supplier_name}</p>
                </div>
                <button onClick={() => { setSelectedPo(null); setEligibility(null); }} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
                  <X size={16} />
                </button>
              </div>

              <div className="grid grid-cols-2 gap-x-4">
                <Input label="Document Date" type="date" value={documentDate} onChange={(e) => setDocumentDate(e.target.value)} />
                <Input label="Supplier Delivery Note (Optional)" value={supplierDeliveryNote} onChange={(e) => setSupplierDeliveryNote(e.target.value)} placeholder="e.g. DN-2026-001" />
              </div>

              <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 mt-2">Receipt Quantities</h4>
              <div className="overflow-x-auto mb-4">
                <table className="w-full text-left text-[13px]">
                  <thead>
                    <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                      <th className="py-2 pr-2">Product</th>
                      <th className="py-2 pr-2">Ordered</th>
                      <th className="py-2 pr-2">Received</th>
                      <th className="py-2 pr-2">Remaining</th>
                      <th className="py-2">Receive Now</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                    {eligibility.lines.map((line) => (
                      <tr key={line.purchase_order_line_id}>
                        <td className="py-2 pr-2 text-gray-900 dark:text-white">{line.description}</td>
                        <td className="py-2 pr-2 text-gray-500 dark:text-gray-400">{line.ordered_quantity} {line.uom.code}</td>
                        <td className="py-2 pr-2 text-gray-500 dark:text-gray-400">{line.received_quantity}</td>
                        <td className="py-2 pr-2 font-medium text-gray-700 dark:text-gray-200">{line.remaining_quantity}</td>
                        <td className="py-2">
                          <input
                            type="number" min="0" step="0.001" max={line.remaining_quantity}
                            disabled={Number(line.remaining_quantity) <= 0}
                            value={quantities[line.purchase_order_line_id] || ''}
                            onChange={(e) => setQuantities((prev) => ({ ...prev, [line.purchase_order_line_id]: e.target.value }))}
                            placeholder="0"
                            className="w-24 px-2 py-1.5 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-[13px] disabled:opacity-40 disabled:cursor-not-allowed"
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mb-4">
                <Input label="Notes (Optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
              </div>

              <p className="text-[12px] text-gray-400 mb-4">
                Saving as Draft does not affect inventory — stock is only increased when this receipt is confirmed.
              </p>

              <button
                onClick={handleSave} disabled={isSubmitting}
                className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[15px] font-medium disabled:opacity-70"
              >
                {isSubmitting && <Loader2 size={18} className="animate-spin" />} Save Goods Receipt
              </button>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
};

interface DetailPermissions {
  canConfirm: boolean; canCancel: boolean; canCreateInvoice: boolean;
}

const ReceiptDetailModal: React.FC<{ receiptId: string; onClose: () => void; onChanged: () => void; permissions: DetailPermissions }> = ({
  receiptId, onClose, onChanged, permissions,
}) => {
  const { showToast } = useToast();
  const { currentTenant } = useAuth();
  const [receipt, setReceipt] = useState<GoodsReceiptDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirmAction, setConfirmAction] = useState<'confirm' | 'cancel' | null>(null);
  const [isActing, setIsActing] = useState(false);
  const [showInvoiceModal, setShowInvoiceModal] = useState(false);
  const [showPrintPreview, setShowPrintPreview] = useState(false);

  const [related, setRelated] = useState<GoodsReceiptRelatedDocuments | null>(null);
  const [isLoadingRelated, setIsLoadingRelated] = useState(true);
  const [audit, setAudit] = useState<GoodsReceiptAuditHistory | null>(null);
  const [isLoadingAudit, setIsLoadingAudit] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await getGoodsReceipt(receiptId);
      setReceipt(data);
    } catch {
      showToast('Failed to load goods receipt.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [receiptId]);

  const loadRelated = useCallback(async () => {
    setIsLoadingRelated(true);
    try {
      setRelated(await getGoodsReceiptRelatedDocuments(receiptId));
    } catch {
      // non-critical section — fail silently, section just stays empty
    } finally {
      setIsLoadingRelated(false);
    }
  }, [receiptId]);

  const loadAudit = useCallback(async () => {
    setIsLoadingAudit(true);
    try {
      setAudit(await getGoodsReceiptAuditHistory(receiptId));
    } catch {
      // non-critical section — fail silently, section just stays empty
    } finally {
      setIsLoadingAudit(false);
    }
  }, [receiptId]);

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

  if (isLoading || !receipt) {
    return (
      <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
        <Loader2 size={28} className="animate-spin text-white" />
      </div>
    );
  }

  const isConfirmedCancellation = confirmAction === 'cancel' && receipt.status === 'CONFIRMED';

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <div>
            <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{receipt.grn_number}</h3>
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{receipt.supplier_name} · {receipt.source_purchase_order_number || 'Ad-hoc'}</p>
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
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[receipt.status]}`}>{receipt.status}</span>
            <span className="text-gray-500 dark:text-gray-400">Date: {receipt.document_date}</span>
            {receipt.supplier_delivery_note && <span className="text-gray-500 dark:text-gray-400">· Delivery Note: {receipt.supplier_delivery_note}</span>}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                  <th className="py-2 pr-2">Product</th><th className="py-2 pr-2">HSN</th>
                  <th className="py-2 pr-2">Ordered</th><th className="py-2 pr-2">Prev. Received</th>
                  <th className="py-2 pr-2">This Receipt</th><th className="py-2">Remaining</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {receipt.lines.map((line) => (
                  <tr key={line.id}>
                    <td className="py-2 pr-2">{line.description}</td>
                    <td className="py-2 pr-2">{line.hsn_code || '—'}</td>
                    <td className="py-2 pr-2">{line.ordered_quantity} {line.uom.code}</td>
                    <td className="py-2 pr-2">{line.previously_received_quantity}</td>
                    <td className="py-2 pr-2 font-medium">{line.quantity}</td>
                    <td className="py-2">{line.remaining_quantity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="bg-gray-50 dark:bg-gray-900 rounded-md p-4 space-y-1 border border-gray-200 dark:border-gray-700">
            <div className="flex justify-between font-semibold text-gray-900 dark:text-white">
              <span>Grand Total (informational)</span><span>₹{receipt.grand_total}</span>
            </div>
          </div>

          {/* --- §42 Stock Impact Visibility --- */}
          {receipt.status !== 'DRAFT' && (
            <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
              <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
                <PackagePlus size={14} /> Inventory Impact
              </h4>
              <div className="space-y-1.5">
                {receipt.lines.map((line) => (
                  <div key={line.id} className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 rounded-md px-3 py-2 text-[13px] border border-gray-200 dark:border-gray-700">
                    <span className="text-gray-700 dark:text-gray-200">{line.description}</span>
                    {line.stock_movement_reversed ? (
                      <span className="inline-flex items-center gap-1 text-gray-400"><RotateCcw size={12} /> Reversed</span>
                    ) : line.stock_movement_id ? (
                      <span className="inline-flex items-center gap-1 text-green-600 dark:text-green-400"><PackagePlus size={12} /> STOCK IN +{line.quantity} {line.uom.code}</span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </div>
                ))}
              </div>
              {receipt.status === 'CANCELLED' && receipt.lines.some((l) => l.stock_movement_reversed) && (
                <p className="text-[12px] text-gray-400 mt-2 flex items-center gap-1"><PackageMinus size={12} /> A compensating Stock OUT reversal was posted for this cancellation. The original Stock IN entries remain in history.</p>
              )}
            </div>
          )}

          {receipt.notes && <p className="text-gray-600 dark:text-gray-300"><span className="text-gray-400 text-[12px] uppercase block">Notes</span>{receipt.notes}</p>}

          <div className="flex flex-wrap gap-2 pt-2">
            {permissions.canConfirm && receipt.status === 'DRAFT' && (
              <button disabled={isActing} onClick={() => setConfirmAction('confirm')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium">
                <CheckCircle2 size={14} /> Confirm Receipt
              </button>
            )}
            {permissions.canCancel && (receipt.status === 'DRAFT' || receipt.status === 'CONFIRMED') && (
              <button disabled={isActing} onClick={() => setConfirmAction('cancel')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[13px] font-medium">
                <Ban size={14} /> Cancel
              </button>
            )}
            {permissions.canCreateInvoice && receipt.status === 'CONFIRMED' && (
              <button disabled={isActing} onClick={() => setShowInvoiceModal(true)} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium ml-auto">
                <Receipt size={14} /> Create Purchase Invoice
              </button>
            )}
          </div>

          {/* --- Related Documents (§18/§34/§41) --- */}
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
              <FileText size={14} /> Related Documents
            </h4>
            {isLoadingRelated ? (
              <div className="flex justify-center py-4"><Loader2 size={18} className="animate-spin text-gray-400" /></div>
            ) : related ? (
              <div className="space-y-3">
                {related.source_purchase_order_number && (
                  <div className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 rounded-md px-3 py-2 text-[13px] border border-gray-200 dark:border-gray-700">
                    <span className="inline-flex items-center gap-1 text-gray-900 dark:text-white font-medium"><FileText size={12} /> {related.source_purchase_order_number}</span>
                    <span className="text-gray-500 dark:text-gray-400">{related.source_purchase_order_status}</span>
                  </div>
                )}
                {related.purchase_invoices.length > 0 ? (
                  <div>
                    <p className="text-[11px] text-gray-400 uppercase mb-1 flex items-center gap-1"><Receipt size={12} /> Purchase Invoices</p>
                    <div className="space-y-1.5">
                      {related.purchase_invoices.map((inv) => (
                        <div key={inv.id} className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 rounded-md px-3 py-2 text-[13px] border border-gray-200 dark:border-gray-700">
                          <span className="text-gray-900 dark:text-white font-medium">{inv.purchase_invoice_number}</span>
                          <span className="text-gray-500 dark:text-gray-400">₹{inv.grand_total} · {inv.document_date}</span>
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${STATUS_BADGE[inv.status] || ''}`}>{inv.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <p className="text-[13px] text-gray-400 italic">No Purchase Invoices linked to this receipt yet.</p>
                )}
              </div>
            ) : (
              <p className="text-[13px] text-gray-400 italic">No related documents.</p>
            )}
          </div>

          {/* --- Audit History (§46) --- */}
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

      {showInvoiceModal && (
        <CreateInvoiceFromReceiptModal
          receiptId={receipt.id}
          onClose={() => setShowInvoiceModal(false)}
          onSaved={() => { setShowInvoiceModal(false); onChanged(); }}
        />
      )}

      {showPrintPreview && (
        <GrPrintPreviewModal receipt={receipt} businessName={currentTenant?.business_name || 'Your Business'} onClose={() => setShowPrintPreview(false)} />
      )}

      {confirmAction && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
            <div className="flex items-center gap-3 mb-3">
              <div className={`flex h-10 w-10 items-center justify-center rounded-full shrink-0 ${confirmAction === 'confirm' ? 'bg-blue-100 dark:bg-blue-900/30' : 'bg-amber-100 dark:bg-amber-900/30'}`}>
                <AlertTriangle size={20} className={confirmAction === 'confirm' ? 'text-blue-600 dark:text-blue-400' : 'text-amber-600 dark:text-amber-400'} />
              </div>
              <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">
                {confirmAction === 'confirm' ? 'Confirm Goods Receipt' : isConfirmedCancellation ? 'Cancel Confirmed Goods Receipt' : 'Cancel Goods Receipt'}
              </h3>
            </div>
            <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-6">
              {confirmAction === 'confirm'
                ? 'This action will increase inventory. Stock will be received for every line on this receipt and cannot be undone.'
                : isConfirmedCancellation
                ? 'This receipt already increased inventory. Cancelling it will post a compensating Stock OUT reversal for every line and reduce the source Purchase Order\'s received quantity. This is blocked if a Purchase Invoice already exists against this receipt, or if the received stock has already been consumed elsewhere.'
                : 'This draft goods receipt will be cancelled. No stock has been affected yet.'}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => setConfirmAction(null)} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Back</button>
              <button
                onClick={() => {
                  if (confirmAction === 'confirm') runAction(() => confirmGoodsReceipt(receipt.id, receipt.row_version), 'Goods receipt confirmed — stock updated.');
                  else runAction(() => cancelGoodsReceipt(receipt.id, receipt.row_version), isConfirmedCancellation ? 'Goods receipt cancelled — stock reversed.' : 'Goods receipt cancelled.');
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

/** §43: Print/Preview capability, mirrors PurchaseOrderManagement's own
 * `PrintPreviewModal` exactly (same window.print()-based approach — no
 * backend PDF service exists). Explicitly headed "GOODS RECEIPT", never
 * "Purchase Invoice", per that section's own instruction. */
const GrPrintPreviewModal: React.FC<{ receipt: GoodsReceiptDetail; businessName: string; onClose: () => void }> = ({ receipt, businessName, onClose }) => {
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
          <p className="text-[20px] font-bold tracking-wide">GOODS RECEIPT</p>
          <p className="text-gray-500 dark:text-gray-400 print:text-gray-600">{businessName}</p>
        </div>

        <div className="grid grid-cols-2 gap-6 mb-6">
          <div>
            <p className="text-[11px] uppercase text-gray-400 mb-1">Supplier</p>
            <p className="font-medium">{receipt.supplier_name}</p>
          </div>
          <div className="text-right">
            <p><span className="text-gray-400">GRN Number:</span> <span className="font-medium">{receipt.grn_number}</span></p>
            <p><span className="text-gray-400">GR Date:</span> {receipt.document_date}</p>
            {receipt.source_purchase_order_number && <p><span className="text-gray-400">PO Reference:</span> {receipt.source_purchase_order_number}</p>}
            {receipt.supplier_delivery_note && <p><span className="text-gray-400">Supplier Delivery Note:</span> {receipt.supplier_delivery_note}</p>}
            <p><span className="text-gray-400">Status:</span> {receipt.status}</p>
          </div>
        </div>

        <table className="w-full text-left border-collapse mb-6">
          <thead>
            <tr className="border-b-2 border-gray-300 dark:border-gray-600 print:border-gray-400">
              <th className="py-2 pr-2">Product</th><th className="py-2 pr-2">HSN</th>
              <th className="py-2 pr-2">Ordered Qty</th><th className="py-2 pr-2">Received Qty</th><th className="py-2">UOM</th>
            </tr>
          </thead>
          <tbody>
            {receipt.lines.map((line) => (
              <tr key={line.id} className="border-b border-gray-100 dark:border-gray-700 print:border-gray-300">
                <td className="py-1.5 pr-2">{line.description}</td>
                <td className="py-1.5 pr-2">{line.hsn_code || '—'}</td>
                <td className="py-1.5 pr-2">{line.ordered_quantity}</td>
                <td className="py-1.5 pr-2">{line.quantity}</td>
                <td className="py-1.5">{line.uom.code}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {receipt.notes && (
          <div className="mb-6">
            <p className="text-[11px] uppercase text-gray-400 mb-1">Notes</p>
            <p>{receipt.notes}</p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-6 mt-16 pt-6 border-t border-gray-200 dark:border-gray-700 print:border-gray-400">
          <div>
            <p className="border-t border-gray-400 pt-1 mt-8 text-[12px] text-gray-500">Received By</p>
          </div>
          <div>
            <p className="border-t border-gray-400 pt-1 mt-8 text-[12px] text-gray-500">Approved By</p>
          </div>
        </div>

        <p className="text-[11px] text-gray-400 text-center mt-10">This is a system-generated Goods Receipt. Not a Purchase Invoice.</p>
      </div>

      <style>{`
        @media print {
          body * { visibility: hidden; }
          .print\\:static, .print\\:static * { visibility: visible; }
          .print\\:static { position: absolute; inset: 0; }
          .print\\:hidden { display: none !important; }
        }
      `}</style>
    </div>
  );
};

const CreateInvoiceFromReceiptModal: React.FC<{ receiptId: string; onClose: () => void; onSaved: () => void }> = ({
  receiptId, onClose, onSaved,
}) => {
  const { showToast } = useToast();
  const [eligibility, setEligibility] = useState<InvoiceEligibility | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [invoiceDate, setInvoiceDate] = useState(new Date().toISOString().slice(0, 10));
  const [supplierInvoiceNumber, setSupplierInvoiceNumber] = useState('');
  const [notes, setNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      try {
        const data = await getInvoiceEligibility(receiptId);
        setEligibility(data);
        const initial: Record<string, string> = {};
        data.lines.forEach((line) => { initial[line.source_goods_receipt_line_id] = line.invoiceable_quantity; });
        setQuantities(initial);
      } catch (err) {
        showToast(err instanceof ApiError ? err.message : 'Failed to load invoice eligibility.', 'error');
        onClose();
      } finally {
        setIsLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [receiptId]);

  const handleSave = async () => {
    if (!eligibility) return;
    const lines: { source_goods_receipt_line_id: string; quantity: string }[] = [];
    for (const line of eligibility.lines) {
      const qty = quantities[line.source_goods_receipt_line_id];
      if (qty && Number(qty) > 0) {
        if (Number(qty) > Number(line.invoiceable_quantity)) {
          showToast(`Invoice quantity for ${line.description} exceeds invoiceable quantity (${line.invoiceable_quantity}).`, 'error');
          return;
        }
        lines.push({ source_goods_receipt_line_id: line.source_goods_receipt_line_id, quantity: qty });
      }
    }
    if (lines.length === 0) { showToast('Enter an invoice quantity for at least one line.', 'error'); return; }

    setIsSubmitting(true);
    try {
      await createInvoiceFromReceipt(receiptId, {
        document_date: invoiceDate || null,
        supplier_invoice_number: supplierInvoiceNumber || null,
        notes: notes || null,
        lines,
      });
      showToast('Purchase invoice created successfully.', 'success');
      onSaved();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.', 'error');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><Receipt size={18} /> Create Purchase Invoice</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>
        <div className="p-6">
          {isLoading || !eligibility ? (
            <div className="flex justify-center py-8"><Loader2 size={24} className="animate-spin text-gray-400" /></div>
          ) : (
            <>
              <div className="flex items-center justify-between px-3 py-2.5 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 mb-4">
                <div>
                  <p className="text-[14px] font-medium text-gray-900 dark:text-white">{eligibility.source_goods_receipt_number}</p>
                  <p className="text-[12px] text-gray-500 dark:text-gray-400">{eligibility.supplier_name}</p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-x-4">
                <Input label="Invoice Date" type="date" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} />
                <Input label="Supplier Invoice # (Optional)" value={supplierInvoiceNumber} onChange={(e) => setSupplierInvoiceNumber(e.target.value)} />
              </div>

              <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 mt-2">Invoice Quantities</h4>
              <div className="overflow-x-auto mb-4">
                <table className="w-full text-left text-[13px]">
                  <thead>
                    <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                      <th className="py-2 pr-2">Product</th>
                      <th className="py-2 pr-2">Received</th>
                      <th className="py-2 pr-2">Invoiced</th>
                      <th className="py-2 pr-2">Invoiceable</th>
                      <th className="py-2">Invoice Now</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                    {eligibility.lines.map((line) => (
                      <tr key={line.source_goods_receipt_line_id}>
                        <td className="py-2 pr-2 text-gray-900 dark:text-white">{line.description}</td>
                        <td className="py-2 pr-2 text-gray-500 dark:text-gray-400">{line.received_quantity} {line.uom.code}</td>
                        <td className="py-2 pr-2 text-gray-500 dark:text-gray-400">{line.invoiced_quantity}</td>
                        <td className="py-2 pr-2 font-medium text-gray-700 dark:text-gray-200">{line.invoiceable_quantity}</td>
                        <td className="py-2">
                          <input
                            type="number" min="0" step="0.001" max={line.invoiceable_quantity}
                            disabled={Number(line.invoiceable_quantity) <= 0}
                            value={quantities[line.source_goods_receipt_line_id] || ''}
                            onChange={(e) => setQuantities((prev) => ({ ...prev, [line.source_goods_receipt_line_id]: e.target.value }))}
                            placeholder="0"
                            className="w-24 px-2 py-1.5 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-[13px] disabled:opacity-40 disabled:cursor-not-allowed"
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mb-4">
                <Input label="Notes (Optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
              </div>

              <p className="text-[12px] text-gray-400 mb-4">
                Inventory was already increased when this goods receipt was confirmed — creating and posting this invoice will NOT increase inventory again.
              </p>

              <button
                onClick={handleSave} disabled={isSubmitting}
                className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[15px] font-medium disabled:opacity-70"
              >
                {isSubmitting && <Loader2 size={18} className="animate-spin" />} Save Purchase Invoice
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default GoodsReceiptManagement;
