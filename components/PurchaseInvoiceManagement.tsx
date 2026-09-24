import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, Plus, X, Loader2, AlertTriangle, Receipt, CheckCircle2,
  Ban, ChevronLeft, ChevronRight, Eye, FileText, Trash2, RotateCcw,
  Printer, History, PackagePlus, PackageMinus, ShoppingCart,
} from 'lucide-react';
import Input from './Input';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { ApiError } from '../api/client';
import {
  PurchaseInvoiceListItem,
  PurchaseInvoiceDetail,
  PurchaseReturnEligibility,
  PurchaseInvoiceRelatedDocuments,
  PurchaseInvoiceAuditHistory,
  PurchaseOrderInvoiceEligibility,
  listPurchaseInvoices,
  getPurchaseInvoice,
  createDirectPurchaseInvoice,
  postPurchaseInvoice,
  cancelPurchaseInvoice,
  getPurchaseReturnEligibility,
  getPurchaseInvoiceRelatedDocuments,
  getPurchaseInvoiceAuditHistory,
  getPurchaseOrderInvoiceEligibility,
  createInvoiceFromPurchaseOrder,
} from '../api/purchaseInvoices';
import { createPurchaseReturn, PURCHASE_RETURN_REASONS, PurchaseReturnReason } from '../api/purchaseReturns';
import { Supplier } from '../api/suppliers';
import { listPurchaseOrders, PurchaseOrderListItem } from '../api/purchaseOrders';
import SupplierSelector from '../shared/SupplierSelector';
import ProductLineSelector, { SalesLineDraft } from '../shared/ProductLineSelector';

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  POSTED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  CANCELLED: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
  CONFIRMED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
};

const TYPE_LABEL: Record<string, string> = {
  DIRECT_PURCHASE_INVOICE: 'Direct',
  GOODS_RECEIPT_PURCHASE_INVOICE: 'From Goods Receipt',
  PURCHASE_ORDER_PURCHASE_INVOICE: 'From Purchase Order',
};

const AUDIT_ACTION_LABEL: Record<string, string> = {
  PURCHASE_INVOICE_CREATED: 'Created',
  PURCHASE_INVOICE_UPDATED: 'Draft updated',
  PURCHASE_INVOICE_POSTED: 'Posted',
  PURCHASE_INVOICE_CANCELLED: 'Cancelled',
};

const ELIGIBLE_PO_STATUSES = new Set(['CONFIRMED', 'PARTIALLY_RECEIVED', 'FULLY_RECEIVED']);

const PurchaseInvoiceManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const canCreate = hasPermission('purchase_invoice.create');
  const canPost = hasPermission('purchase_invoice.post');
  const canCancel = hasPermission('purchase_invoice.cancel');
  const canCreateReturn = hasPermission('purchase_return.create');

  const [items, setItems] = useState<PurchaseInvoiceListItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showCreateFromPoModal, setShowCreateFromPoModal] = useState(false);
  const [viewingId, setViewingId] = useState<string | null>(null);

  const fetchInvoices = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listPurchaseInvoices({ page, page_size: 10, search: search || undefined, status: statusFilter || undefined });
      setItems(result.data);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load purchase invoices.', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [page, search, statusFilter, showToast]);

  useEffect(() => { fetchInvoices(); /* eslint-disable-next-line */ }, [page, statusFilter]);
  useEffect(() => {
    const timer = setTimeout(() => { setPage(1); fetchInvoices(); }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 flex flex-col md:flex-row justify-between items-stretch md:items-center gap-4 shadow-sm">
        <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">Purchase Invoices</h2>
        <div className="flex flex-col sm:flex-row gap-3 w-full md:w-auto">
          <div className="relative w-full sm:w-64">
            <input
              type="text" placeholder="Search invoice #, receipt, supplier…" value={search}
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
            {['DRAFT', 'POSTED', 'CANCELLED'].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          {canCreate && (
            <>
              <button onClick={() => setShowCreateFromPoModal(true)} className="border border-[#0066ff] text-[#0066ff] font-semibold text-[14px] px-4 py-2 rounded-lg flex items-center justify-center gap-2 whitespace-nowrap">
                <ShoppingCart size={16} /> From PO
              </button>
              <button onClick={() => setShowCreateModal(true)} className="bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[14px] px-4 py-2 rounded-lg flex items-center justify-center gap-2 whitespace-nowrap">
                <Plus size={16} /> New Invoice
              </button>
            </>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No purchase invoices found.</div>
      ) : (
        <>
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    {['Invoice #', 'Date', 'Supplier', 'Type', 'Amount', 'GST', 'Stock Impact', 'Status', 'Source', 'Actions'].map((h) => (
                      <th key={h} className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {items.map((inv) => (
                    <tr key={inv.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap">
                        <button onClick={() => setViewingId(inv.id)} className="hover:text-[#0066ff] hover:underline">{inv.purchase_invoice_number}</button>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap">{inv.document_date}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">{inv.supplier_name}</td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap">{TYPE_LABEL[inv.invoice_type]}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap">₹{inv.grand_total}</td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap">₹{inv.tax_total}</td>
                      <td className="px-6 py-4 text-[12px] whitespace-nowrap">
                        {inv.stock_impact === 'STOCK_IN_REQUIRED' ? (
                          <span className="inline-flex items-center gap-1 text-green-600 dark:text-green-400"><PackagePlus size={12} /> Stock IN</span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-gray-400"><PackageMinus size={12} /> Already Received</span>
                        )}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[inv.status]}`}>{inv.status}</span>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap">
                        {inv.source_goods_receipt_number ? (
                          <span className="inline-flex items-center gap-1 text-purple-600 dark:text-purple-400"><FileText size={12} /> {inv.source_goods_receipt_number}</span>
                        ) : inv.source_purchase_order_number ? (
                          <span className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400"><FileText size={12} /> {inv.source_purchase_order_number}</span>
                        ) : 'Direct'}
                      </td>
                      <td className="px-6 py-4 text-center whitespace-nowrap">
                        <button onClick={() => setViewingId(inv.id)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="View">
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
            {items.map((inv) => (
              <button key={inv.id} onClick={() => setViewingId(inv.id)} className="w-full text-left bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <p className="font-semibold text-gray-900 dark:text-white text-[15px]">{inv.purchase_invoice_number}</p>
                    <p className="text-[13px] text-gray-500 dark:text-gray-400">{inv.supplier_name}</p>
                  </div>
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[inv.status]}`}>{inv.status}</span>
                </div>
                <p className="text-[13px] text-gray-600 dark:text-gray-300">₹{inv.grand_total} · {inv.document_date}</p>
              </button>
            ))}
          </div>

          <div className="flex items-center justify-between mt-4 px-1">
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{totalItems} invoice{totalItems === 1 ? '' : 's'}</p>
            <div className="flex items-center gap-2">
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronLeft size={16} /></button>
              <span className="text-[13px] text-gray-600 dark:text-gray-400">Page {page} of {totalPages}</span>
              <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronRight size={16} /></button>
            </div>
          </div>
        </>
      )}

      {showCreateModal && (
        <DirectInvoiceFormModal onClose={() => setShowCreateModal(false)} onSaved={() => { setShowCreateModal(false); fetchInvoices(); }} />
      )}

      {showCreateFromPoModal && (
        <CreateInvoiceFromPoModal onClose={() => setShowCreateFromPoModal(false)} onSaved={() => { setShowCreateFromPoModal(false); fetchInvoices(); }} />
      )}

      {viewingId && (
        <InvoiceDetailModal
          invoiceId={viewingId}
          onClose={() => setViewingId(null)}
          onChanged={fetchInvoices}
          permissions={{ canPost, canCancel, canCreateReturn }}
        />
      )}
    </div>
  );
};

const DirectInvoiceFormModal: React.FC<{ onClose: () => void; onSaved: () => void }> = ({ onClose, onSaved }) => {
  const { showToast } = useToast();
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [invoiceDate, setInvoiceDate] = useState(new Date().toISOString().slice(0, 10));
  const [supplierInvoiceNumber, setSupplierInvoiceNumber] = useState('');
  const [supplierInvoiceDate, setSupplierInvoiceDate] = useState('');
  const [dueDate, setDueDate] = useState('');
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
      const result = await createDirectPurchaseInvoice({
        supplier_id: supplier.id,
        document_date: invoiceDate || null,
        supplier_invoice_number: supplierInvoiceNumber || null,
        supplier_invoice_date: supplierInvoiceDate || null,
        due_date: dueDate || null,
        notes: notes || null,
        lines: lines.map((l) => {
          // Mirrors Purchase Order/Sales Invoice's fix: ProductLineSelector
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
      if (result.duplicate_supplier_invoice_warning) {
        showToast('Purchase invoice created — note: this supplier invoice number was already used.', 'success');
      } else {
        showToast('Purchase invoice created successfully.', 'success');
      }
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
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><Receipt size={18} /> New Direct Purchase Invoice</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>
        <div className="p-6">
          <SupplierSelector value={supplier} onChange={setSupplier} />

          <div className="grid grid-cols-2 gap-x-4">
            <Input label="Invoice Date" type="date" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} />
            <Input label="Supplier Invoice # (Optional)" value={supplierInvoiceNumber} onChange={(e) => setSupplierInvoiceNumber(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-x-4">
            <Input label="Supplier Invoice Date (Optional)" type="date" value={supplierInvoiceDate} onChange={(e) => setSupplierInvoiceDate(e.target.value)} />
            <Input label="Due Date (Optional)" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
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

          <div className="mt-4 mb-4">
            <Input label="Notes (Optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          <p className="text-[12px] text-gray-400 mb-4">
            Saving as Draft does not affect inventory — stock is only increased when this invoice is posted.
          </p>

          <button
            onClick={handleSave} disabled={isSubmitting}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[15px] font-medium disabled:opacity-70"
          >
            {isSubmitting && <Loader2 size={18} className="animate-spin" />} Save Invoice
          </button>
        </div>
      </div>
    </div>
  );
};

/** "Supported Flow 2" (§3/§8/§9): create a Purchase Invoice directly
 * from a Purchase Order, consolidating eligible quantity across
 * potentially multiple confirmed Goods Receipts under it — mirrors
 * GoodsReceiptManagement's own PO-picker + eligibility-table pattern. */
const CreateInvoiceFromPoModal: React.FC<{ onClose: () => void; onSaved: () => void }> = ({ onClose, onSaved }) => {
  const { showToast } = useToast();
  const [poQuery, setPoQuery] = useState('');
  const [poResults, setPoResults] = useState<PurchaseOrderListItem[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedPo, setSelectedPo] = useState<PurchaseOrderListItem | null>(null);
  const [eligibility, setEligibility] = useState<PurchaseOrderInvoiceEligibility | null>(null);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [invoiceDate, setInvoiceDate] = useState(new Date().toISOString().slice(0, 10));
  const [supplierInvoiceNumber, setSupplierInvoiceNumber] = useState('');
  const [supplierInvoiceDate, setSupplierInvoiceDate] = useState('');
  const [dueDate, setDueDate] = useState('');
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
      const data = await getPurchaseOrderInvoiceEligibility(order.id);
      setEligibility(data);
      const initialQuantities: Record<string, string> = {};
      data.lines.forEach((line) => { initialQuantities[line.purchase_order_line_id] = ''; });
      setQuantities(initialQuantities);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load invoiceable items.', 'error');
      setSelectedPo(null);
    } finally {
      setIsLoadingEligibility(false);
    }
  };

  const handleSave = async () => {
    if (!eligibility) return;
    const lines: { purchase_order_line_id: string; quantity: string }[] = [];
    for (const line of eligibility.lines) {
      const qty = quantities[line.purchase_order_line_id];
      if (qty && Number(qty) > 0) {
        if (Number(qty) > Number(line.invoiceable_quantity)) {
          showToast(`Invoice quantity for ${line.description} exceeds invoiceable quantity (${line.invoiceable_quantity}).`, 'error');
          return;
        }
        lines.push({ purchase_order_line_id: line.purchase_order_line_id, quantity: qty });
      }
    }
    if (lines.length === 0) { showToast('Enter an invoice quantity for at least one line.', 'error'); return; }

    setIsSubmitting(true);
    try {
      await createInvoiceFromPurchaseOrder(eligibility.purchase_order_id, {
        document_date: invoiceDate || null,
        supplier_invoice_number: supplierInvoiceNumber || null,
        supplier_invoice_date: supplierInvoiceDate || null,
        due_date: dueDate || null,
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
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><ShoppingCart size={18} /> New Purchase Invoice from Purchase Order</h3>
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
                    <p className="px-3 py-3 text-[13px] text-gray-400 italic">No eligible purchase orders found.</p>
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
                <Input label="Invoice Date" type="date" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} />
                <Input label="Supplier Invoice # (Optional)" value={supplierInvoiceNumber} onChange={(e) => setSupplierInvoiceNumber(e.target.value)} />
              </div>
              <div className="grid grid-cols-2 gap-x-4">
                <Input label="Supplier Invoice Date (Optional)" type="date" value={supplierInvoiceDate} onChange={(e) => setSupplierInvoiceDate(e.target.value)} />
                <Input label="Due Date (Optional)" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
              </div>

              <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 mt-2">Invoice Quantities</h4>
              <div className="overflow-x-auto mb-4">
                <table className="w-full text-left text-[13px]">
                  <thead>
                    <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                      <th className="py-2 pr-2">Product</th>
                      <th className="py-2 pr-2">Ordered</th>
                      <th className="py-2 pr-2">Received</th>
                      <th className="py-2 pr-2">Invoiced</th>
                      <th className="py-2 pr-2">Invoiceable</th>
                      <th className="py-2">Invoice Now</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                    {eligibility.lines.map((line) => (
                      <tr key={line.purchase_order_line_id}>
                        <td className="py-2 pr-2 text-gray-900 dark:text-white">{line.description}</td>
                        <td className="py-2 pr-2 text-gray-500 dark:text-gray-400">{line.ordered_quantity} {line.uom.code}</td>
                        <td className="py-2 pr-2 text-gray-500 dark:text-gray-400">{line.received_quantity}</td>
                        <td className="py-2 pr-2 text-gray-500 dark:text-gray-400">{line.invoiced_quantity}</td>
                        <td className="py-2 pr-2 font-medium text-gray-700 dark:text-gray-200">{line.invoiceable_quantity}</td>
                        <td className="py-2">
                          <input
                            type="number" min="0" step="0.001" max={line.invoiceable_quantity}
                            disabled={Number(line.invoiceable_quantity) <= 0}
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
                Inventory was already increased when the underlying goods receipt(s) were confirmed — this invoice will NOT increase inventory again, even across multiple receipts.
              </p>

              <button
                onClick={handleSave} disabled={isSubmitting}
                className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[15px] font-medium disabled:opacity-70"
              >
                {isSubmitting && <Loader2 size={18} className="animate-spin" />} Save Purchase Invoice
              </button>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
};

interface DetailPermissions {
  canPost: boolean; canCancel: boolean; canCreateReturn: boolean;
}

const InvoiceDetailModal: React.FC<{ invoiceId: string; onClose: () => void; onChanged: () => void; permissions: DetailPermissions }> = ({
  invoiceId, onClose, onChanged, permissions,
}) => {
  const { showToast } = useToast();
  const { currentTenant } = useAuth();
  const [invoice, setInvoice] = useState<PurchaseInvoiceDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirmAction, setConfirmAction] = useState<'post' | 'cancel' | null>(null);
  const [isActing, setIsActing] = useState(false);
  const [showReturnModal, setShowReturnModal] = useState(false);
  const [showPrintPreview, setShowPrintPreview] = useState(false);

  const [related, setRelated] = useState<PurchaseInvoiceRelatedDocuments | null>(null);
  const [isLoadingRelated, setIsLoadingRelated] = useState(true);
  const [audit, setAudit] = useState<PurchaseInvoiceAuditHistory | null>(null);
  const [isLoadingAudit, setIsLoadingAudit] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await getPurchaseInvoice(invoiceId);
      setInvoice(data);
    } catch {
      showToast('Failed to load purchase invoice.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceId]);

  const loadRelated = useCallback(async () => {
    setIsLoadingRelated(true);
    try {
      setRelated(await getPurchaseInvoiceRelatedDocuments(invoiceId));
    } catch {
      // non-critical section — fail silently, section just stays empty
    } finally {
      setIsLoadingRelated(false);
    }
  }, [invoiceId]);

  const loadAudit = useCallback(async () => {
    setIsLoadingAudit(true);
    try {
      setAudit(await getPurchaseInvoiceAuditHistory(invoiceId));
    } catch {
      // non-critical section — fail silently, section just stays empty
    } finally {
      setIsLoadingAudit(false);
    }
  }, [invoiceId]);

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

  if (isLoading || !invoice) {
    return (
      <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
        <Loader2 size={28} className="animate-spin text-white" />
      </div>
    );
  }

  const isDirect = invoice.invoice_type === 'DIRECT_PURCHASE_INVOICE';
  const isPostedCancellation = confirmAction === 'cancel' && invoice.status === 'POSTED';

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <div>
            <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{invoice.purchase_invoice_number}</h3>
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{invoice.supplier_name}</p>
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
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[invoice.status]}`}>{invoice.status}</span>
            <span className="text-gray-500 dark:text-gray-400">Date: {invoice.document_date}</span>
            {invoice.supplier_invoice_number && <span className="text-gray-500 dark:text-gray-400">· Supplier Inv# {invoice.supplier_invoice_number}</span>}
            {invoice.due_date && <span className="text-gray-500 dark:text-gray-400">· Due {invoice.due_date}</span>}
            {invoice.source_goods_receipt_number && (
              <span className="inline-flex items-center gap-1 text-purple-600 dark:text-purple-400 text-[12px]"><FileText size={12} /> From {invoice.source_goods_receipt_number}</span>
            )}
            {invoice.source_purchase_order_number && !invoice.source_goods_receipt_number && (
              <span className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400 text-[12px]"><FileText size={12} /> From {invoice.source_purchase_order_number}</span>
            )}
          </div>

          {invoice.duplicate_supplier_invoice_warning && (
            <div className="flex items-center gap-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-md px-3 py-2 text-[13px] text-amber-700 dark:text-amber-400">
              <AlertTriangle size={16} /> This supplier invoice number has been used on another invoice for this supplier. Please verify it is not a duplicate.
            </div>
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
                {invoice.lines.map((line) => (
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
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Subtotal</span><span>₹{invoice.subtotal}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Discount</span><span>−₹{invoice.discount_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Taxable Value</span><span>₹{invoice.taxable_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>CGST</span><span>₹{invoice.cgst_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>SGST</span><span>₹{invoice.sgst_total}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>IGST</span><span>₹{invoice.igst_total}</span></div>
            <div className="flex justify-between font-semibold text-gray-900 dark:text-white pt-1 border-t border-gray-100 dark:border-gray-700">
              <span>Grand Total</span><span>₹{invoice.grand_total}</span>
            </div>
          </div>

          {/* --- §46 Stock Impact --- */}
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
              <PackagePlus size={14} /> Stock Impact
            </h4>
            {invoice.stock_impact === 'STOCK_IN_REQUIRED' ? (
              <p className="text-[13px] text-gray-600 dark:text-gray-300">
                <span className="font-medium text-green-600 dark:text-green-400">STOCK IN</span> — no prior Goods Receipt exists for this invoice; posting will increase inventory.
              </p>
            ) : (
              <p className="text-[13px] text-gray-600 dark:text-gray-300">
                <span className="font-medium text-gray-500">NO STOCK IN</span> — quantity already received through {invoice.source_goods_receipt_number || 'a linked Goods Receipt'}.
              </p>
            )}
            {invoice.status !== 'DRAFT' && isDirect && (
              <div className="mt-2 space-y-1.5">
                {invoice.lines.map((line) => (
                  <div key={line.id} className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 rounded-md px-3 py-2 text-[13px] border border-gray-200 dark:border-gray-700">
                    <span className="text-gray-700 dark:text-gray-200">{line.description}</span>
                    {line.stock_movement_reversed ? (
                      <span className="inline-flex items-center gap-1 text-gray-400"><RotateCcw size={12} /> Reversed</span>
                    ) : line.stock_movement_id ? (
                      <span className="inline-flex items-center gap-1 text-green-600 dark:text-green-400"><PackagePlus size={12} /> +{line.quantity} {line.uom.code}</span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {invoice.notes && <p className="text-gray-600 dark:text-gray-300"><span className="text-gray-400 text-[12px] uppercase block">Notes</span>{invoice.notes}</p>}

          <div className="flex flex-wrap gap-2 pt-2">
            {permissions.canPost && invoice.status === 'DRAFT' && (
              <button disabled={isActing} onClick={() => setConfirmAction('post')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium">
                <CheckCircle2 size={14} /> Post Invoice
              </button>
            )}
            {permissions.canCancel && (invoice.status === 'DRAFT' || invoice.status === 'POSTED') && (
              <button disabled={isActing} onClick={() => setConfirmAction('cancel')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[13px] font-medium">
                <Ban size={14} /> Cancel
              </button>
            )}
            {permissions.canCreateReturn && invoice.status === 'POSTED' && (
              <button disabled={isActing} onClick={() => setShowReturnModal(true)} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-[13px] font-medium ml-auto">
                <RotateCcw size={14} /> Create Purchase Return
              </button>
            )}
          </div>

          {/* --- Related Documents (§36/§47) --- */}
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
                {related.purchase_returns.length > 0 && (
                  <div>
                    <p className="text-[11px] text-gray-400 uppercase mb-1">Purchase Returns</p>
                    <div className="space-y-1.5">
                      {related.purchase_returns.map((ret) => (
                        <div key={ret.id} className="flex items-center justify-between bg-gray-50 dark:bg-gray-900 rounded-md px-3 py-2 text-[13px] border border-gray-200 dark:border-gray-700">
                          <span className="text-gray-900 dark:text-white font-medium">{ret.purchase_return_number}</span>
                          <span className="text-gray-500 dark:text-gray-400">₹{ret.grand_total} · {ret.document_date}</span>
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${STATUS_BADGE[ret.status] || ''}`}>{ret.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {!related.source_purchase_order_number && related.goods_receipts.length === 0 && related.purchase_returns.length === 0 && (
                  <p className="text-[13px] text-gray-400 italic">No related documents.</p>
                )}
              </div>
            ) : (
              <p className="text-[13px] text-gray-400 italic">No related documents.</p>
            )}
          </div>

          {/* --- Audit History (§51) --- */}
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

      {showReturnModal && (
        <CreateReturnFromInvoiceModal
          invoiceId={invoice.id}
          onClose={() => setShowReturnModal(false)}
          onSaved={() => { setShowReturnModal(false); onChanged(); }}
        />
      )}

      {showPrintPreview && (
        <PiPrintPreviewModal invoice={invoice} businessName={currentTenant?.business_name || 'Your Business'} onClose={() => setShowPrintPreview(false)} />
      )}

      {confirmAction && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
            <div className="flex items-center gap-3 mb-3">
              <div className={`flex h-10 w-10 items-center justify-center rounded-full shrink-0 ${confirmAction === 'post' ? 'bg-blue-100 dark:bg-blue-900/30' : 'bg-amber-100 dark:bg-amber-900/30'}`}>
                <AlertTriangle size={20} className={confirmAction === 'post' ? 'text-blue-600 dark:text-blue-400' : 'text-amber-600 dark:text-amber-400'} />
              </div>
              <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">
                {confirmAction === 'post' ? 'Post Invoice' : isPostedCancellation ? 'Cancel Posted Invoice' : 'Cancel Invoice'}
              </h3>
            </div>
            <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-6">
              {confirmAction === 'post'
                ? (isDirect
                    ? 'This invoice will be posted and cannot be edited afterward. This action will increase inventory.'
                    : 'This invoice will be posted and cannot be edited afterward. Inventory was already increased when the goods receipt(s) were confirmed — this invoice will not increase inventory again.')
                : isPostedCancellation
                ? (isDirect
                    ? 'This invoice already increased inventory. Cancelling it will post a compensating Stock OUT reversal. This is blocked if a Purchase Return already exists against this invoice, or if the received stock has already been consumed elsewhere.'
                    : 'This invoice never affected stock — the source Goods Receipt remains the physical receipt. Cancelling it only releases its claim on the invoiced quantity. This is blocked if a Purchase Return already exists against this invoice.')
                : 'This draft invoice will be cancelled. No stock impact has occurred yet.'}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => setConfirmAction(null)} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Back</button>
              <button
                onClick={() => {
                  if (confirmAction === 'post') runAction(() => postPurchaseInvoice(invoice.id, invoice.row_version), 'Invoice posted.');
                  else runAction(() => cancelPurchaseInvoice(invoice.id, invoice.row_version), isPostedCancellation ? 'Invoice cancelled — reversal applied.' : 'Invoice cancelled.');
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

/** §48: Print/Preview capability, mirrors Purchase Order/Goods
 * Receipt's own print modals exactly. Explicitly headed "PURCHASE
 * INVOICE", never "Purchase Order" or "Goods Receipt". */
const PiPrintPreviewModal: React.FC<{ invoice: PurchaseInvoiceDetail; businessName: string; onClose: () => void }> = ({ invoice, businessName, onClose }) => {
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
          <p className="text-[20px] font-bold tracking-wide">PURCHASE INVOICE</p>
          <p className="text-gray-500 dark:text-gray-400 print:text-gray-600">{businessName}</p>
        </div>

        <div className="grid grid-cols-2 gap-6 mb-6">
          <div>
            <p className="text-[11px] uppercase text-gray-400 mb-1">Supplier</p>
            <p className="font-medium">{invoice.supplier_name}</p>
            {invoice.supplier_gstin && <p>GSTIN: {invoice.supplier_gstin}</p>}
          </div>
          <div className="text-right">
            <p><span className="text-gray-400">Invoice Number:</span> <span className="font-medium">{invoice.purchase_invoice_number}</span></p>
            {invoice.supplier_invoice_number && <p><span className="text-gray-400">Supplier Invoice #:</span> {invoice.supplier_invoice_number}</p>}
            <p><span className="text-gray-400">Invoice Date:</span> {invoice.document_date}</p>
            {invoice.due_date && <p><span className="text-gray-400">Due Date:</span> {invoice.due_date}</p>}
            {invoice.source_purchase_order_number && <p><span className="text-gray-400">PO Reference:</span> {invoice.source_purchase_order_number}</p>}
            {invoice.source_goods_receipt_number && <p><span className="text-gray-400">GR Reference:</span> {invoice.source_goods_receipt_number}</p>}
            <p><span className="text-gray-400">Status:</span> {invoice.status}</p>
          </div>
        </div>

        <table className="w-full text-left border-collapse mb-6">
          <thead>
            <tr className="border-b-2 border-gray-300 dark:border-gray-600 print:border-gray-400">
              <th className="py-2 pr-2">Product</th><th className="py-2 pr-2">HSN</th><th className="py-2 pr-2">Qty</th>
              <th className="py-2 pr-2">UOM</th><th className="py-2 pr-2">Rate</th><th className="py-2 pr-2">Discount</th>
              <th className="py-2 pr-2">GST</th><th className="py-2 text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {invoice.lines.map((line) => (
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
            <div className="flex justify-between"><span className="text-gray-500">Subtotal</span><span>₹{invoice.subtotal}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Discount</span><span>−₹{invoice.discount_total}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Taxable Value</span><span>₹{invoice.taxable_total}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">CGST</span><span>₹{invoice.cgst_total}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">SGST</span><span>₹{invoice.sgst_total}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">IGST</span><span>₹{invoice.igst_total}</span></div>
            <div className="flex justify-between font-semibold border-t border-gray-300 dark:border-gray-600 print:border-gray-400 pt-1">
              <span>Grand Total</span><span>₹{invoice.grand_total}</span>
            </div>
          </div>
        </div>

        {invoice.notes && (
          <div className="mb-6">
            <p className="text-[11px] uppercase text-gray-400 mb-1">Notes</p>
            <p>{invoice.notes}</p>
          </div>
        )}

        <p className="text-[11px] text-gray-400 text-center mt-10">This is a system-generated Purchase Invoice.</p>
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

const CreateReturnFromInvoiceModal: React.FC<{ invoiceId: string; onClose: () => void; onSaved: () => void }> = ({
  invoiceId, onClose, onSaved,
}) => {
  const { showToast } = useToast();
  const [eligibility, setEligibility] = useState<PurchaseReturnEligibility | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [returnDate, setReturnDate] = useState(new Date().toISOString().slice(0, 10));
  const [reason, setReason] = useState<PurchaseReturnReason>('DAMAGED');
  const [reasonDescription, setReasonDescription] = useState('');
  const [notes, setNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      try {
        const data = await getPurchaseReturnEligibility(invoiceId);
        setEligibility(data);
      } catch (err) {
        showToast(err instanceof ApiError ? err.message : 'Failed to load return eligibility.', 'error');
        onClose();
      } finally {
        setIsLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceId]);

  const handleSave = async () => {
    if (!eligibility) return;
    if (reason === 'OTHER' && !reasonDescription.trim()) {
      showToast('A reason description is required when the reason is "Other".', 'error');
      return;
    }
    const lines: { source_purchase_invoice_line_id: string; quantity: string }[] = [];
    for (const line of eligibility.lines) {
      const qty = quantities[line.source_purchase_invoice_line_id];
      if (qty && Number(qty) > 0) {
        if (Number(qty) > Number(line.returnable_quantity)) {
          showToast(`Return quantity for ${line.description} exceeds returnable quantity (${line.returnable_quantity}).`, 'error');
          return;
        }
        lines.push({ source_purchase_invoice_line_id: line.source_purchase_invoice_line_id, quantity: qty });
      }
    }
    if (lines.length === 0) { showToast('Enter a return quantity for at least one line.', 'error'); return; }

    setIsSubmitting(true);
    try {
      await createPurchaseReturn({
        source_purchase_invoice_id: invoiceId,
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
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><RotateCcw size={18} /> Create Purchase Return</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>
        <div className="p-6">
          {isLoading || !eligibility ? (
            <div className="flex justify-center py-8"><Loader2 size={24} className="animate-spin text-gray-400" /></div>
          ) : (
            <>
              <div className="flex items-center justify-between px-3 py-2.5 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 mb-4">
                <div>
                  <p className="text-[14px] font-medium text-gray-900 dark:text-white">{eligibility.source_purchase_invoice_number}</p>
                  <p className="text-[12px] text-gray-500 dark:text-gray-400">{eligibility.supplier_name}</p>
                </div>
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

export default PurchaseInvoiceManagement;
