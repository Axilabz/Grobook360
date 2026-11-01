import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, Plus, X, Loader2, AlertTriangle, ShoppingCart, CheckCircle2,
  Ban, ChevronLeft, ChevronRight, Eye, Trash2, FileText,
} from 'lucide-react';
import Input from './Input';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import MobileFilterToggle from '../shared/MobileFilterToggle';
import { ApiError } from '../api/client';
import {
  SalesOrderListItem,
  SalesOrderDetail,
  SalesOrderLine,
  listSalesOrders,
  getSalesOrder,
  createSalesOrder,
  confirmSalesOrder,
  cancelSalesOrder,
} from '../api/salesOrders';
import { Customer } from '../api/customers';
import CustomerSelector from '../shared/CustomerSelector';
import ProductLineSelector, { SalesLineDraft } from '../shared/ProductLineSelector';
import { getProduct, ProductDetail } from '../api/products';

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  CONFIRMED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  CANCELLED: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
};

// Mirrors the backend's own state machine (app/services/sales/sales_order_service.py)
// for UX only — the server independently enforces every transition.
const ACTION_ALLOWED_FROM: Record<string, string[]> = {
  confirm: ['DRAFT'],
  cancel: ['DRAFT', 'CONFIRMED'],
};

const SalesOrderManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const canCreate = hasPermission('sales_order.create');
  const canConfirm = hasPermission('sales_order.confirm');
  const canCancel = hasPermission('sales_order.cancel');

  const [items, setItems] = useState<SalesOrderListItem[]>([]);
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
      const result = await listSalesOrders({ page, page_size: 10, search: search || undefined, status: statusFilter || undefined });
      setItems(result.data);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load sales orders.', 'error');
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
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">Sales Orders</h2>
          <MobileFilterToggle open={showMobileFilters} onClick={() => setShowMobileFilters((v) => !v)} />
        </div>

        <div className={`${showMobileFilters ? 'flex' : 'hidden'} md:flex flex-col sm:flex-row gap-3 w-full md:w-auto`}>
          <div className="relative w-full sm:w-64">
            <input
              type="text" placeholder="Search order #, customer…" value={search}
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
              <Plus size={16} /> New Sales Order
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No sales orders found.</div>
      ) : (
        <>
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    {[
                      { label: 'Order #', align: 'text-left' }, { label: 'Date', align: 'text-right' }, { label: 'Customer', align: 'text-left' },
                      { label: 'Amount', align: 'text-right' }, { label: 'Status', align: 'text-left' }, { label: 'Source', align: 'text-left' },
                      { label: 'Created By', align: 'text-left' }, { label: 'Actions', align: 'text-center' },
                    ].map((h) => (
                      <th key={h.label} className={`px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider ${h.align}`}>{h.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {items.map((order) => (
                    <tr key={order.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap text-left">
                        <button onClick={() => setViewingId(order.id)} className="hover:text-[#0066ff] hover:underline">{order.order_number}</button>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-right">{order.order_date}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-left">{order.customer_name}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">₹{order.grand_total}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-left">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[order.status]}`}>{order.status}</span>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">
                        {order.source_estimate_id ? (
                          <span className="inline-flex items-center gap-1 text-purple-600 dark:text-purple-400"><FileText size={12} /> Estimate</span>
                        ) : 'Manual'}
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
                    <p className="font-semibold text-gray-900 dark:text-white text-[15px]">{order.order_number}</p>
                    <p className="text-[13px] text-gray-500 dark:text-gray-400">{order.customer_name}</p>
                  </div>
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[order.status]}`}>{order.status}</span>
                </div>
                <p className="text-[13px] text-gray-600 dark:text-gray-300">₹{order.grand_total} · {order.order_date}</p>
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
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [orderDate, setOrderDate] = useState(new Date().toISOString().slice(0, 10));
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
    if (!customer) { showToast('Select a customer.', 'error'); return; }
    if (lines.length === 0) { showToast('Add at least one product line.', 'error'); return; }
    setIsSubmitting(true);
    try {
      await createSalesOrder({
        customer_id: customer.id,
        order_date: orderDate || null,
        shipping_address: shippingAddress || null,
        notes: notes || null,
        lines: lines.map((l) => {
          // Mirrors EstimateManagement's fix: ProductLineSelector always
          // fills both discount fields with '0' — forward only the one
          // actually entered, never both (the backend rejects both).
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
      showToast('Sales order created successfully.', 'success');
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
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><ShoppingCart size={18} /> New Sales Order</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>
        <div className="p-6">
          <CustomerSelector value={customer} onChange={setCustomer} />

          <div className="grid grid-cols-2 gap-x-4">
            <Input label="Order Date" type="date" value={orderDate} onChange={(e) => setOrderDate(e.target.value)} />
            <Input label="Shipping Address (Optional)" value={shippingAddress} onChange={(e) => setShippingAddress(e.target.value)} />
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
            Creating a sales order does not reduce inventory — stock is only affected by a future Delivery Challan or Sales Invoice.
          </p>

          <button
            onClick={handleSave} disabled={isSubmitting}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[15px] font-medium disabled:opacity-70"
          >
            {isSubmitting && <Loader2 size={18} className="animate-spin" />} Save Sales Order
          </button>
        </div>
      </div>
    </div>
  );
};

interface DetailPermissions {
  canConfirm: boolean; canCancel: boolean;
}

interface StockCheck {
  required: number;
  available: number;
}

// Converts a Sales Order line's quantity (in whatever UOM the line used)
// into the product's base-UOM equivalent, the same unit `stock_qty_cache`
// is tracked in — mirrors InventoryService._conversion_factor's own
// from_uom->base_uom lookup. Falls back to a raw (unconverted) comparison
// if no matching conversion is on file, rather than silently skipping the
// check.
function requiredBaseQuantity(line: SalesOrderLine, product: ProductDetail): number {
  const qty = Number(line.quantity);
  if (line.uom.id === product.base_uom.id) return qty;
  const conversion = product.unit_conversions.find(
    (c) => c.from_uom.id === line.uom.id && c.to_uom.id === product.base_uom.id
  );
  return conversion ? qty * Number(conversion.conversion_factor) : qty;
}

const OrderDetailModal: React.FC<{ orderId: string; onClose: () => void; onChanged: () => void; permissions: DetailPermissions }> = ({
  orderId, onClose, onChanged, permissions,
}) => {
  const { showToast } = useToast();
  const [order, setOrder] = useState<SalesOrderDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirmAction, setConfirmAction] = useState<'cancel' | null>(null);
  const [cancelReason, setCancelReason] = useState('');
  const [isActing, setIsActing] = useState(false);
  const [stockChecks, setStockChecks] = useState<Record<string, StockCheck>>({});

  const checkStock = useCallback(async (data: SalesOrderDetail) => {
    // Only DRAFT orders are still awaiting confirm — no need to check
    // stock for an order that's already CONFIRMED or CANCELLED.
    if (data.status !== 'DRAFT') {
      setStockChecks({});
      return;
    }
    try {
      const entries = await Promise.all(
        data.lines
          .filter((line): line is SalesOrderLine & { product_id: string } => Boolean(line.product_id))
          .map(async (line) => {
            const product = await getProduct(line.product_id);
            return [line.id, { required: requiredBaseQuantity(line, product), available: Number(product.stock_qty_cache) }] as const;
          })
      );
      setStockChecks(Object.fromEntries(entries) as Record<string, StockCheck>);
    } catch {
      // Best-effort — if a stock lookup fails, don't block the whole
      // screen; the Confirm button simply won't be stock-gated this time.
      setStockChecks({});
    }
  }, []);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await getSalesOrder(orderId);
      setOrder(data);
      await checkStock(data);
    } catch {
      showToast('Failed to load sales order.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId]);

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

  if (isLoading || !order) {
    return (
      <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
        <Loader2 size={28} className="animate-spin text-white" />
      </div>
    );
  }

  const allowed = (action: keyof typeof ACTION_ALLOWED_FROM) => ACTION_ALLOWED_FROM[action].includes(order.status);
  const hasInsufficientStock = Object.values(stockChecks).some((s: StockCheck) => s.available < s.required);

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <div>
            <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{order.order_number}</h3>
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{order.customer_name}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>

        <div className="p-6 space-y-5 text-[14px]">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[order.status]}`}>{order.status}</span>
            <span className="text-gray-500 dark:text-gray-400">Date: {order.order_date}</span>
            {order.source_estimate_id && (
              <span className="inline-flex items-center gap-1 text-purple-600 dark:text-purple-400 text-[12px]"><FileText size={12} /> Converted from Estimate</span>
            )}
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
                {order.lines.map((line) => {
                  const stock = stockChecks[line.id];
                  const isShort = stock && stock.available < stock.required;
                  return (
                    <tr key={line.id} className={isShort ? 'bg-red-50 dark:bg-red-900/20' : undefined}>
                      <td className="py-2 pr-2">
                        {line.description}
                        {isShort && (
                          <div className="flex items-center gap-1 text-[11px] text-red-600 dark:text-red-400 mt-0.5">
                            <AlertTriangle size={11} /> Only {stock.available} in stock — needs {stock.required}
                          </div>
                        )}
                      </td>
                      <td className="py-2 pr-2">{line.hsn_code || '—'}</td>
                      <td className={`py-2 pr-2 ${isShort ? 'text-red-600 dark:text-red-400 font-medium' : ''}`}>{line.quantity} {line.uom.code}</td>
                      <td className="py-2 pr-2">₹{line.unit_price}</td>
                      <td className="py-2 pr-2">₹{line.discount_amount}</td>
                      <td className="py-2 pr-2">₹{line.taxable_amount}</td>
                      <td className="py-2 pr-2">₹{(Number(line.cgst_amount) + Number(line.sgst_amount) + Number(line.igst_amount)).toFixed(2)}</td>
                      <td className="py-2 font-medium">₹{line.line_total}</td>
                    </tr>
                  );
                })}
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
          {order.cancellation_reason && (
            <p className="text-gray-600 dark:text-gray-300"><span className="text-gray-400 text-[12px] uppercase block">Cancellation Reason</span>{order.cancellation_reason}</p>
          )}

          <div className="flex flex-wrap gap-2 pt-2">
            {permissions.canConfirm && allowed('confirm') && (
              <button
                disabled={isActing || hasInsufficientStock}
                title={hasInsufficientStock ? 'Cannot confirm — one or more lines exceed available stock' : undefined}
                onClick={() => runAction(() => confirmSalesOrder(order.id, order.row_version), 'Sales order confirmed.')}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-green-300 dark:border-green-800 text-green-600 text-[13px] font-medium disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <CheckCircle2 size={14} /> Confirm
              </button>
            )}
            {permissions.canCancel && allowed('cancel') && (
              <button disabled={isActing} onClick={() => { setCancelReason(''); setConfirmAction('cancel'); }} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[13px] font-medium">
                <Ban size={14} /> Cancel
              </button>
            )}
          </div>
          {hasInsufficientStock && (
            <p className="flex items-center gap-1.5 text-[12px] text-red-600 dark:text-red-400">
              <AlertTriangle size={12} /> One or more lines exceed available stock — reduce the quantity or restock before confirming.
            </p>
          )}
        </div>
      </div>

      {confirmAction && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/30 shrink-0"><AlertTriangle size={20} className="text-amber-600 dark:text-amber-400" /></div>
              <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">Cancel Sales Order</h3>
            </div>
            <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-4">
              This sales order will be cancelled and can no longer be actioned. No stock was ever reserved by this order, so nothing needs to be reversed.
            </p>
            <label className="block text-[12px] font-medium text-gray-500 dark:text-gray-400 mb-1.5">Reason for cancellation</label>
            <textarea
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
              rows={3}
              placeholder="Why is this order being cancelled?"
              className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-[14px] px-3 py-2 mb-6 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => setConfirmAction(null)} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Back</button>
              <button
                disabled={isActing || !cancelReason.trim()}
                onClick={() => runAction(() => cancelSalesOrder(order.id, order.row_version, cancelReason.trim()), 'Sales order cancelled.')}
                className="py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium disabled:opacity-50 disabled:cursor-not-allowed"
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

export default SalesOrderManagement;
