import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, Plus, X, Loader2, AlertTriangle, ShoppingCart, CheckCircle2,
  Ban, ChevronLeft, ChevronRight, Eye, Trash2, Printer, FileText, History, Truck, Receipt,
} from 'lucide-react';
import Input from './Input';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import MobileFilterToggle from '../shared/MobileFilterToggle';
import { ApiError } from '../api/client';
import {
  PurchaseOrderListItem,
  PurchaseOrderDetail,
  PurchaseOrderRelatedDocuments,
  PurchaseOrderAuditHistory,
  listPurchaseOrders,
  getPurchaseOrder,
  createPurchaseOrder,
  confirmPurchaseOrder,
  cancelPurchaseOrder,
  getRelatedDocuments,
  getAuditHistory,
} from '../api/purchaseOrders';
import { Supplier } from '../api/suppliers';
import SupplierSelector from '../shared/SupplierSelector';
import ProductLineSelector, { SalesLineDraft } from '../shared/ProductLineSelector';
import LoadingState from '../shared/LoadingState';

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  CONFIRMED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  PARTIALLY_RECEIVED: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  FULLY_RECEIVED: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  CANCELLED: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
};

const AUDIT_ACTION_LABEL: Record<string, string> = {
  PURCHASE_ORDER_CREATED: 'Created',
  PURCHASE_ORDER_UPDATED: 'Draft updated',
  PURCHASE_ORDER_CONFIRMED: 'Confirmed',
  PURCHASE_ORDER_CANCELLED: 'Cancelled',
  PURCHASE_ORDER_RECEIPT_UPDATED: 'Receipt recorded',
};

// Mirrors the backend's own state machine (app/services/purchase/purchase_order_service.py)
// for UX only — the server independently enforces every transition.
const ACTION_ALLOWED_FROM: Record<string, string[]> = {
  confirm: ['DRAFT'],
  cancel: ['DRAFT', 'CONFIRMED', 'PARTIALLY_RECEIVED'],
};

const PurchaseOrderManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const canCreate = hasPermission('purchase_order.create');
  const canConfirm = hasPermission('purchase_order.confirm');
  const canCancel = hasPermission('purchase_order.cancel');

  const [items, setItems] = useState<PurchaseOrderListItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showMobileFilters, setShowMobileFilters] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [viewingId, setViewingId] = useState<string | null>(null);

  const fetchOrders = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listPurchaseOrders({ page, page_size: 10, search: search || undefined, status: statusFilter || undefined });
      setItems(result.data);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load purchase orders.', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [page, search, statusFilter, showToast]);

  useEffect(() => { fetchOrders(); /* eslint-disable-next-line */ }, [page, statusFilter]);
  useEffect(() => {
    const timer = setTimeout(() => { setPage(1); fetchOrders(); }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 flex flex-col md:flex-row justify-between items-stretch md:items-center gap-4 shadow-sm">
        <div className="flex items-center justify-between gap-3 md:block">
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">Purchase Orders</h2>
          <MobileFilterToggle open={showMobileFilters} onClick={() => setShowMobileFilters((v) => !v)} />
        </div>

        <div className={`${showMobileFilters ? 'flex' : 'hidden'} md:flex flex-col sm:flex-row gap-3 w-full md:w-auto`}>
          <div className="relative w-full sm:w-64">
            <input
              type="text" placeholder="Search PO #, supplier…" value={search}
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
            {['DRAFT', 'CONFIRMED', 'PARTIALLY_RECEIVED', 'FULLY_RECEIVED', 'CANCELLED'].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          {canCreate && (
            <button onClick={() => setShowCreateModal(true)} className="bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[14px] px-4 py-2 rounded-lg flex items-center justify-center gap-2 whitespace-nowrap">
              <Plus size={16} /> New Purchase Order
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16"><LoadingState bare /></div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No purchase orders found.</div>
      ) : (
        <>
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    {[
                      { label: 'PO #', align: 'text-left' }, { label: 'Date', align: 'text-right' }, { label: 'Supplier', align: 'text-left' },
                      { label: 'Expected Delivery', align: 'text-right' }, { label: 'Qty (Ord / Rcv / Rem)', align: 'text-right' },
                      { label: 'Amount', align: 'text-right' }, { label: 'Status', align: 'text-left' }, { label: 'Created By', align: 'text-left' },
                      { label: 'Actions', align: 'text-center' },
                    ].map((h) => (
                      <th key={h.label} className={`px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider ${h.align}`}>{h.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {items.map((order) => (
                    <tr key={order.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap text-left">
                        <button onClick={() => setViewingId(order.id)} className="hover:text-[#0066ff] hover:underline">{order.po_number}</button>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-right">{order.document_date}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-left">{order.supplier_name}</td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-right">{order.expected_delivery_date || '—'}</td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-right">
                        {order.total_ordered_quantity} / {order.total_received_quantity} / {order.total_remaining_quantity}
                      </td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">₹{order.grand_total}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-left">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[order.status]}`}>{order.status.replace('_', ' ')}</span>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{order.created_by_name || '—'}</td>
                      <td className="px-6 py-4 text-center whitespace-nowrap">
                        <button onClick={() => setViewingId(order.id)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="View">
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
            {items.map((order) => (
              <button key={order.id} onClick={() => setViewingId(order.id)} className="w-full text-left bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <p className="font-semibold text-gray-900 dark:text-white text-[15px]">{order.po_number}</p>
                    <p className="text-[13px] text-gray-500 dark:text-gray-400">{order.supplier_name}</p>
                  </div>
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[order.status]}`}>{order.status.replace('_', ' ')}</span>
                </div>
                <p className="text-[13px] text-gray-600 dark:text-gray-300">₹{order.grand_total} · {order.document_date}</p>
                <p className="text-[12px] text-gray-400 mt-1">Qty {order.total_ordered_quantity} · Received {order.total_received_quantity} · Remaining {order.total_remaining_quantity}</p>
              </button>
            ))}
          </div>

          <div className="flex items-center justify-between mt-4 px-1">
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{totalItems} order{totalItems === 1 ? '' : 's'}</p>
            <div className="flex items-center gap-2">
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronLeft size={16} /></button>
              <span className="text-[13px] text-gray-600 dark:text-gray-400">Page {page} of {totalPages}</span>
              <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronRight size={16} /></button>
            </div>
          </div>
        </>
      )}

      {showCreateModal && (
        <OrderFormModal onClose={() => setShowCreateModal(false)} onSaved={() => { setShowCreateModal(false); fetchOrders(); }} />
      )}

      {viewingId && (
        <OrderDetailModal
          orderId={viewingId}
          onClose={() => setViewingId(null)}
          onChanged={fetchOrders}
          permissions={{ canConfirm, canCancel }}
        />
      )}
    </div>
  );
};

const OrderFormModal: React.FC<{ onClose: () => void; onSaved: () => void }> = ({ onClose, onSaved }) => {
  const { showToast } = useToast();
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [documentDate, setDocumentDate] = useState(new Date().toISOString().slice(0, 10));
  const [supplierReference, setSupplierReference] = useState('');
  const [expectedDeliveryDate, setExpectedDeliveryDate] = useState('');
  const [paymentTerms, setPaymentTerms] = useState('');
  const [deliveryTerms, setDeliveryTerms] = useState('');
  const [shippingAddress, setShippingAddress] = useState('');
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
    if (!supplier) { showToast('Select a supplier.', 'error'); return; }
    if (lines.length === 0) { showToast('Add at least one product line.', 'error'); return; }
    setIsSubmitting(true);
    try {
      await createPurchaseOrder({
        supplier_id: supplier.id,
        document_date: documentDate || null,
        supplier_reference: supplierReference || null,
        expected_delivery_date: expectedDeliveryDate || null,
        payment_terms: paymentTerms || null,
        delivery_terms: deliveryTerms || null,
        shipping_address: shippingAddress || null,
        notes: notes || null,
        lines: lines.map((l) => {
          // Mirrors Sales Order/Estimate's own fix: ProductLineSelector
          // always fills both discount fields with '0' — forward only the
          // one actually entered, never both (the backend rejects both).
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
      showToast('Purchase order created successfully.', 'success');
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
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><ShoppingCart size={18} /> New Purchase Order</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>
        <div className="p-6">
          <SupplierSelector value={supplier} onChange={setSupplier} />

          <div className="grid grid-cols-2 gap-x-4">
            <Input label="Document Date" type="date" value={documentDate} onChange={(e) => setDocumentDate(e.target.value)} />
            <Input label="Expected Delivery Date (Optional)" type="date" value={expectedDeliveryDate} onChange={(e) => setExpectedDeliveryDate(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-x-4">
            <Input label="Supplier Reference (Optional)" value={supplierReference} onChange={(e) => setSupplierReference(e.target.value)} />
            <Input label="Shipping Address (Optional)" value={shippingAddress} onChange={(e) => setShippingAddress(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-x-4">
            <Input label="Payment Terms (Optional)" value={paymentTerms} onChange={(e) => setPaymentTerms(e.target.value)} placeholder="e.g. Net 30" />
            <Input label="Delivery Terms (Optional)" value={deliveryTerms} onChange={(e) => setDeliveryTerms(e.target.value)} placeholder="e.g. FOB Destination" />
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

          <p className="text-[12px] text-gray-400 -mt-8 mb-4">
            Creating a purchase order does not affect inventory — stock is only increased once a Goods Receipt against this order is confirmed.
          </p>

          <button
            onClick={handleSave} disabled={isSubmitting}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[15px] font-medium disabled:opacity-70"
          >
            {isSubmitting && <Loader2 size={18} className="animate-spin" />} Save Purchase Order
          </button>
        </div>
      </div>
    </div>
  );
};

interface DetailPermissions {
  canConfirm: boolean; canCancel: boolean;
}

const OrderDetailModal: React.FC<{ orderId: string; onClose: () => void; onChanged: () => void; permissions: DetailPermissions }> = ({
  orderId, onClose, onChanged, permissions,
}) => {
  const { showToast } = useToast();
  const { currentTenant } = useAuth();
  const [order, setOrder] = useState<PurchaseOrderDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirmAction, setConfirmAction] = useState<'cancel' | null>(null);
  const [isActing, setIsActing] = useState(false);
  const [showPrintPreview, setShowPrintPreview] = useState(false);

  const [related, setRelated] = useState<PurchaseOrderRelatedDocuments | null>(null);
  const [isLoadingRelated, setIsLoadingRelated] = useState(true);
  const [audit, setAudit] = useState<PurchaseOrderAuditHistory | null>(null);
  const [isLoadingAudit, setIsLoadingAudit] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await getPurchaseOrder(orderId);
      setOrder(data);
    } catch {
      showToast('Failed to load purchase order.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId]);

  const loadRelated = useCallback(async () => {
    setIsLoadingRelated(true);
    try {
      setRelated(await getRelatedDocuments(orderId));
    } catch {
      // non-critical section — fail silently, section just stays empty
    } finally {
      setIsLoadingRelated(false);
    }
  }, [orderId]);

  const loadAudit = useCallback(async () => {
    setIsLoadingAudit(true);
    try {
      setAudit(await getAuditHistory(orderId));
    } catch {
      // non-critical section — fail silently, section just stays empty
    } finally {
      setIsLoadingAudit(false);
    }
  }, [orderId]);

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

  if (isLoading || !order) {
    return (
      <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
        <LoadingState bare />
      </div>
    );
  }

  const allowed = (action: keyof typeof ACTION_ALLOWED_FROM) => ACTION_ALLOWED_FROM[action].includes(order.status);

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <div>
            <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{order.po_number}</h3>
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{order.supplier_name}</p>
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
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[order.status]}`}>{order.status.replace('_', ' ')}</span>
            <span className="text-gray-500 dark:text-gray-400">Date: {order.document_date}</span>
            {order.expected_delivery_date && <span className="text-gray-500 dark:text-gray-400">· Expected: {order.expected_delivery_date}</span>}
            {order.supplier_reference && <span className="text-gray-500 dark:text-gray-400">· Ref: {order.supplier_reference}</span>}
          </div>

          {(order.billing_address || order.shipping_address) && (
            <div className="grid grid-cols-2 gap-4 text-[13px]">
              <div>
                <span className="text-gray-400 text-[11px] uppercase block">Billing Address</span>
                <p className="text-gray-600 dark:text-gray-300">{order.billing_address || '—'}</p>
              </div>
              <div>
                <span className="text-gray-400 text-[11px] uppercase block">Shipping Address</span>
                <p className="text-gray-600 dark:text-gray-300">{order.shipping_address || '—'}</p>
              </div>
            </div>
          )}

          {(order.payment_terms || order.delivery_terms) && (
            <div className="grid grid-cols-2 gap-4 text-[13px]">
              <div>
                <span className="text-gray-400 text-[11px] uppercase block">Payment Terms</span>
                <p className="text-gray-600 dark:text-gray-300">{order.payment_terms || '—'}</p>
              </div>
              <div>
                <span className="text-gray-400 text-[11px] uppercase block">Delivery Terms</span>
                <p className="text-gray-600 dark:text-gray-300">{order.delivery_terms || '—'}</p>
              </div>
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                  <th className="py-2 pr-2">Product</th><th className="py-2 pr-2">HSN</th><th className="py-2 pr-2">Ordered</th>
                  <th className="py-2 pr-2">Received</th><th className="py-2 pr-2">Remaining</th><th className="py-2 pr-2">Price</th><th className="py-2 pr-2">Taxable</th>
                  <th className="py-2 pr-2">GST</th><th className="py-2">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {order.lines.map((line) => (
                  <tr key={line.id}>
                    <td className="py-2 pr-2">{line.description}</td>
                    <td className="py-2 pr-2">{line.hsn_code || '—'}</td>
                    <td className="py-2 pr-2">{line.quantity} {line.uom.code}</td>
                    <td className="py-2 pr-2">{line.received_quantity}</td>
                    <td className="py-2 pr-2 font-medium">{line.remaining_quantity}</td>
                    <td className="py-2 pr-2">₹{line.unit_price}</td>
                    <td className="py-2 pr-2">₹{line.taxable_amount}</td>
                    <td className="py-2 pr-2">₹{(Number(line.cgst_amount) + Number(line.sgst_amount) + Number(line.igst_amount)).toFixed(2)}</td>
                    <td className="py-2 font-medium">₹{line.line_total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="bg-gray-50 dark:bg-gray-900 rounded-md p-4 space-y-1 border border-gray-200 dark:border-gray-700">
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Subtotal</span><span>₹{order.subtotal}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Discount</span><span>−₹{order.discount_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Taxable Value</span><span>₹{order.taxable_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>CGST</span><span>₹{order.cgst_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>SGST</span><span>₹{order.sgst_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>IGST</span><span>₹{order.igst_total}</span></div>
            <div className="flex justify-between font-semibold text-gray-900 dark:text-white pt-1 border-t border-gray-100 dark:border-gray-700">
              <span>Grand Total</span><span>₹{order.grand_total}</span>
            </div>
          </div>

          {order.notes && <p className="text-gray-600 dark:text-gray-300"><span className="text-gray-400 text-[12px] uppercase block">Notes</span>{order.notes}</p>}

          <div className="flex flex-wrap gap-2 pt-2">
            {permissions.canConfirm && allowed('confirm') && (
              <button disabled={isActing} onClick={() => runAction(() => confirmPurchaseOrder(order.id, order.row_version), 'Purchase order confirmed.')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-green-300 dark:border-green-800 text-green-600 text-[13px] font-medium">
                <CheckCircle2 size={14} /> Confirm
              </button>
            )}
            {permissions.canCancel && allowed('cancel') && (
              <button disabled={isActing} onClick={() => setConfirmAction('cancel')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[13px] font-medium">
                <Ban size={14} /> Cancel
              </button>
            )}
          </div>

          {/* --- Related Documents (§17/§24/§34) --- */}
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
              <FileText size={14} /> Related Documents
            </h4>
            {isLoadingRelated ? (
              <div className="flex justify-center py-4"><LoadingState bare compact /></div>
            ) : related && (related.goods_receipts.length > 0 || related.purchase_invoices.length > 0) ? (
              <div className="space-y-3">
                {related.goods_receipts.length > 0 && (
                  <div>
                    <p className="text-[11px] text-gray-400 uppercase mb-1 flex items-center gap-1"><Truck size={12} /> Goods Receipts</p>
                    <div className="space-y-1.5">
                      {related.goods_receipts.map((gr) => (
                        <div key={gr.id} className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 rounded-md px-3 py-2 text-[13px] border border-gray-200 dark:border-gray-700">
                          <span className="text-gray-900 dark:text-white font-medium">{gr.grn_number}</span>
                          <span className="text-gray-500 dark:text-gray-400">{gr.total_quantity} units · {gr.document_date}</span>
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${STATUS_BADGE[gr.status] || ''}`}>{gr.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {related.purchase_invoices.length > 0 && (
                  <div>
                    <p className="text-[11px] text-gray-400 uppercase mb-1 flex items-center gap-1"><Receipt size={12} /> Purchase Invoices</p>
                    <div className="space-y-1.5">
                      {related.purchase_invoices.map((inv) => (
                        <div key={inv.id} className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 rounded-md px-3 py-2 text-[13px] border border-gray-200 dark:border-gray-700">
                          <span className="text-gray-900 dark:text-white font-medium">{inv.purchase_invoice_number}</span>
                          <span className="text-gray-500 dark:text-gray-400">₹{inv.grand_total} · {inv.document_date}</span>
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">{inv.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-[13px] text-gray-400 italic">No Goods Receipts or Purchase Invoices linked to this order yet.</p>
            )}
          </div>

          {/* --- Audit History (§34/§38) --- */}
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
              <History size={14} /> Audit History
            </h4>
            {isLoadingAudit ? (
              <div className="flex justify-center py-4"><LoadingState bare compact /></div>
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

      {confirmAction && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/30 shrink-0"><AlertTriangle size={20} className="text-amber-600 dark:text-amber-400" /></div>
              <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">Cancel Purchase Order</h3>
            </div>
            <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-6">
              This purchase order will be cancelled and can no longer be actioned. Any quantity already received against it is unaffected.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => setConfirmAction(null)} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Back</button>
              <button
                onClick={() => runAction(() => cancelPurchaseOrder(order.id, order.row_version), 'Purchase order cancelled.')}
                className="py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium"
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}

      {showPrintPreview && (
        <PrintPreviewModal order={order} businessName={currentTenant?.business_name || 'Your Business'} onClose={() => setShowPrintPreview(false)} />
      )}
    </div>
  );
};

/** §36: Print/Preview capability — a print-friendly, full-page layout of
 * the Purchase Order, printed via the browser's own window.print() (no
 * backend PDF/print service exists anywhere in this codebase yet — a
 * client-side print stylesheet is the established-elsewhere-appropriate
 * minimal implementation for a foundation-level requirement like this).
 * The heading explicitly says "PURCHASE ORDER" — never "Invoice" — per
 * §36's own instruction not to represent a PO as a Purchase Invoice. */
const PrintPreviewModal: React.FC<{ order: PurchaseOrderDetail; businessName: string; onClose: () => void }> = ({ order, businessName, onClose }) => {
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
          <p className="text-[20px] font-bold tracking-wide">PURCHASE ORDER</p>
          <p className="text-gray-500 dark:text-gray-400 print:text-gray-600">{businessName}</p>
        </div>

        <div className="grid grid-cols-2 gap-6 mb-6">
          <div>
            <p className="text-[11px] uppercase text-gray-400 mb-1">Supplier</p>
            <p className="font-medium">{order.supplier_name}</p>
            {order.supplier_gstin && <p>GSTIN: {order.supplier_gstin}</p>}
            {order.shipping_address && <p>{order.shipping_address}</p>}
          </div>
          <div className="text-right">
            <p><span className="text-gray-400">PO Number:</span> <span className="font-medium">{order.po_number}</span></p>
            <p><span className="text-gray-400">PO Date:</span> {order.document_date}</p>
            {order.expected_delivery_date && <p><span className="text-gray-400">Expected Delivery:</span> {order.expected_delivery_date}</p>}
            {order.supplier_reference && <p><span className="text-gray-400">Supplier Reference:</span> {order.supplier_reference}</p>}
            <p><span className="text-gray-400">Status:</span> {order.status.replace('_', ' ')}</p>
          </div>
        </div>

        {(order.payment_terms || order.delivery_terms) && (
          <div className="grid grid-cols-2 gap-6 mb-6">
            {order.payment_terms && <p><span className="text-gray-400">Payment Terms:</span> {order.payment_terms}</p>}
            {order.delivery_terms && <p><span className="text-gray-400">Delivery Terms:</span> {order.delivery_terms}</p>}
          </div>
        )}

        <table className="w-full text-left border-collapse mb-6">
          <thead>
            <tr className="border-b-2 border-gray-300 dark:border-gray-600 print:border-gray-400">
              <th className="py-2 pr-2">Product</th><th className="py-2 pr-2">HSN</th><th className="py-2 pr-2">Qty</th>
              <th className="py-2 pr-2">UOM</th><th className="py-2 pr-2">Rate</th><th className="py-2 pr-2">Discount</th>
              <th className="py-2 pr-2">GST</th><th className="py-2 text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {order.lines.map((line) => (
              <tr key={line.id} className="border-b border-gray-100 dark:border-gray-700 print:border-gray-300">
                <td className="py-1.5 pr-2">{line.description}</td>
                <td className="py-1.5 pr-2">{line.hsn_code || '—'}</td>
                <td className="py-1.5 pr-2">{line.quantity}</td>
                <td className="py-1.5 pr-2">{line.uom.code}</td>
                <td className="py-1.5 pr-2">₹{line.unit_price}</td>
                <td className="py-1.5 pr-2">₹{line.discount_amount}</td>
                <td className="py-1.5 pr-2">{line.gst_rate}%</td>
                <td className="py-1.5 text-right">₹{line.line_total}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex justify-end mb-6">
          <div className="w-64 space-y-1">
            <div className="flex justify-between"><span className="text-gray-500">Subtotal</span><span>₹{order.subtotal}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Discount</span><span>−₹{order.discount_total}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Taxable Value</span><span>₹{order.taxable_total}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">CGST</span><span>₹{order.cgst_total}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">SGST</span><span>₹{order.sgst_total}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">IGST</span><span>₹{order.igst_total}</span></div>
            <div className="flex justify-between font-semibold border-t border-gray-300 dark:border-gray-600 print:border-gray-400 pt-1">
              <span>Grand Total</span><span>₹{order.grand_total}</span>
            </div>
          </div>
        </div>

        {order.notes && (
          <div className="mb-6">
            <p className="text-[11px] uppercase text-gray-400 mb-1">Notes</p>
            <p>{order.notes}</p>
          </div>
        )}

        <p className="text-[11px] text-gray-400 text-center mt-10">This is a system-generated Purchase Order. Not a tax invoice.</p>
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

export default PurchaseOrderManagement;
