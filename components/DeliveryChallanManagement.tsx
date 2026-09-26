import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, Plus, X, Loader2, AlertTriangle, Truck, CheckCircle2,
  Ban, ChevronLeft, ChevronRight, Eye, FileText, Receipt,
} from 'lucide-react';
import Input from './Input';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import MobileFilterToggle from '../shared/MobileFilterToggle';
import { ApiError } from '../api/client';
import {
  DeliveryChallanListItem,
  DeliveryChallanDetail,
  DeliveryEligibility,
  listDeliveryChallans,
  getDeliveryChallan,
  createDeliveryChallan,
  confirmDeliveryChallan,
  cancelDeliveryChallan,
  getDeliveryEligibility,
} from '../api/deliveryChallans';
import { listSalesOrders, SalesOrderListItem } from '../api/salesOrders';
import { InvoiceEligibility, getInvoiceEligibility, createInvoiceFromChallan } from '../api/salesInvoices';

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  CONFIRMED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  CANCELLED: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
};

const ELIGIBLE_SO_STATUSES = new Set(['CONFIRMED', 'PARTIALLY_FULFILLED']);

const DeliveryChallanManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const canCreate = hasPermission('delivery_challan.create');
  const canConfirm = hasPermission('delivery_challan.confirm');
  const canCancel = hasPermission('delivery_challan.cancel');
  const canCreateInvoice = hasPermission('sales_invoice.create');

  const [items, setItems] = useState<DeliveryChallanListItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showMobileFilters, setShowMobileFilters] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [viewingId, setViewingId] = useState<string | null>(null);

  const fetchChallans = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listDeliveryChallans({ page, page_size: 10, search: search || undefined, status: statusFilter || undefined });
      setItems(result.data);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load delivery challans.', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [page, search, statusFilter, showToast]);

  useEffect(() => { fetchChallans(); /* eslint-disable-next-line */ }, [page, statusFilter]);
  useEffect(() => {
    const timer = setTimeout(() => { setPage(1); fetchChallans(); }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 flex flex-col md:flex-row justify-between items-stretch md:items-center gap-4 shadow-sm">
        <div className="flex items-center justify-between gap-3 md:block">
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">Delivery Challans</h2>
          <MobileFilterToggle open={showMobileFilters} onClick={() => setShowMobileFilters((v) => !v)} />
        </div>

        <div className={`${showMobileFilters ? 'flex' : 'hidden'} md:flex flex-col sm:flex-row gap-3 w-full md:w-auto`}>
          <div className="relative w-full sm:w-64">
            <input
              type="text" placeholder="Search challan #, order, customer…" value={search}
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
              <Plus size={16} /> New Delivery Challan
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No delivery challans found.</div>
      ) : (
        <>
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    {[
                      { label: 'Challan #', align: 'text-left' }, { label: 'Date', align: 'text-right' }, { label: 'Sales Order', align: 'text-left' },
                      { label: 'Customer', align: 'text-left' }, { label: 'Total Qty', align: 'text-right' }, { label: 'Status', align: 'text-left' },
                      { label: 'Created By', align: 'text-left' }, { label: 'Actions', align: 'text-center' },
                    ].map((h) => (
                      <th key={h.label} className={`px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider ${h.align}`}>{h.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {items.map((dc) => (
                    <tr key={dc.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap text-left">
                        <button onClick={() => setViewingId(dc.id)} className="hover:text-[#0066ff] hover:underline">{dc.challan_number}</button>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-right">{dc.challan_date}</td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">
                        <span className="inline-flex items-center gap-1"><FileText size={12} /> {dc.source_sales_order_number}</span>
                      </td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-left">{dc.customer_name}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">{dc.total_quantity}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-left">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[dc.status]}`}>{dc.status}</span>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{dc.created_by_name || '—'}</td>
                      <td className="px-6 py-4 text-center whitespace-nowrap">
                        <button onClick={() => setViewingId(dc.id)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="View">
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
            {items.map((dc) => (
              <button key={dc.id} onClick={() => setViewingId(dc.id)} className="w-full text-left bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <p className="font-semibold text-gray-900 dark:text-white text-[15px]">{dc.challan_number}</p>
                    <p className="text-[13px] text-gray-500 dark:text-gray-400">{dc.customer_name} · {dc.source_sales_order_number}</p>
                  </div>
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[dc.status]}`}>{dc.status}</span>
                </div>
                <p className="text-[13px] text-gray-600 dark:text-gray-300">Qty {dc.total_quantity} · {dc.challan_date}</p>
              </button>
            ))}
          </div>

          <div className="flex items-center justify-between mt-4 px-1">
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{totalItems} challan{totalItems === 1 ? '' : 's'}</p>
            <div className="flex items-center gap-2">
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronLeft size={16} /></button>
              <span className="text-[13px] text-gray-600 dark:text-gray-400">Page {page} of {totalPages}</span>
              <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronRight size={16} /></button>
            </div>
          </div>
        </>
      )}

      {showCreateModal && (
        <ChallanFormModal onClose={() => setShowCreateModal(false)} onSaved={() => { setShowCreateModal(false); fetchChallans(); }} />
      )}

      {viewingId && (
        <ChallanDetailModal
          challanId={viewingId}
          onClose={() => setViewingId(null)}
          onChanged={fetchChallans}
          permissions={{ canConfirm, canCancel, canCreateInvoice }}
        />
      )}
    </div>
  );
};

const ChallanFormModal: React.FC<{ onClose: () => void; onSaved: () => void }> = ({ onClose, onSaved }) => {
  const { showToast } = useToast();
  const [soQuery, setSoQuery] = useState('');
  const [soResults, setSoResults] = useState<SalesOrderListItem[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedSo, setSelectedSo] = useState<SalesOrderListItem | null>(null);
  const [eligibility, setEligibility] = useState<DeliveryEligibility | null>(null);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [challanDate, setChallanDate] = useState(new Date().toISOString().slice(0, 10));
  const [shippingAddress, setShippingAddress] = useState('');
  const [notes, setNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoadingEligibility, setIsLoadingEligibility] = useState(false);

  useEffect(() => {
    if (!soQuery || selectedSo) { setSoResults([]); return; }
    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const result = await listSalesOrders({ search: soQuery, page_size: 10 });
        setSoResults(result.data.filter((o) => ELIGIBLE_SO_STATUSES.has(o.status)));
      } catch {
        setSoResults([]);
      } finally {
        setIsSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [soQuery, selectedSo]);

  const handleSelectSo = async (order: SalesOrderListItem) => {
    setSelectedSo(order);
    setSoQuery('');
    setSoResults([]);
    setIsLoadingEligibility(true);
    try {
      const data = await getDeliveryEligibility(order.id);
      setEligibility(data);
      setShippingAddress(data.shipping_address || '');
      const initialQuantities: Record<string, string> = {};
      data.lines.forEach((line) => { initialQuantities[line.sales_order_line_id] = ''; });
      setQuantities(initialQuantities);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load delivery eligibility.', 'error');
      setSelectedSo(null);
    } finally {
      setIsLoadingEligibility(false);
    }
  };

  const handleSave = async () => {
    if (!eligibility) return;
    const lines: { sales_order_line_id: string; quantity: string }[] = Object.entries(quantities)
      .filter(([, qty]) => qty && Number(qty) > 0)
      .map(([sales_order_line_id, quantity]) => ({ sales_order_line_id, quantity: quantity as string }));

    if (lines.length === 0) { showToast('Enter a delivery quantity for at least one line.', 'error'); return; }

    for (const [lineId, qty] of Object.entries(quantities)) {
      const line = eligibility.lines.find((l) => l.sales_order_line_id === lineId);
      if (line && qty && Number(qty) > Number(line.remaining_quantity)) {
        showToast(`Delivery quantity for ${line.description} exceeds remaining quantity (${line.remaining_quantity}).`, 'error');
        return;
      }
    }

    setIsSubmitting(true);
    try {
      await createDeliveryChallan({
        sales_order_id: eligibility.sales_order_id,
        challan_date: challanDate || null,
        shipping_address: shippingAddress || null,
        notes: notes || null,
        lines,
      });
      showToast('Delivery challan created successfully.', 'success');
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
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><Truck size={18} /> New Delivery Challan</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>
        <div className="p-6">
          {!selectedSo ? (
            <div className="relative mb-6">
              <label className="block text-[13px] font-medium text-gray-600 dark:text-gray-400 mb-1.5">Sales Order</label>
              <div className="relative">
                <input
                  type="text" value={soQuery} onChange={(e) => setSoQuery(e.target.value)}
                  placeholder="Search sales order number or customer…"
                  className="w-full pl-9 pr-3 py-2.5 rounded-md border border-gray-300 dark:border-gray-600 text-[14px] bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:border-blue-500 focus:ring-blue-500"
                />
                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              </div>
              {soQuery && (
                <div className="absolute z-30 mt-1 w-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md shadow-lg max-h-64 overflow-auto">
                  {isSearching ? (
                    <div className="flex justify-center py-4"><Loader2 size={18} className="animate-spin text-gray-400" /></div>
                  ) : soResults.length === 0 ? (
                    <p className="px-3 py-3 text-[13px] text-gray-400 italic">No eligible sales orders found (must be CONFIRMED or PARTIALLY_FULFILLED).</p>
                  ) : (
                    soResults.map((order) => (
                      <button
                        type="button" key={order.id} onClick={() => handleSelectSo(order)}
                        className="w-full text-left px-3 py-2.5 hover:bg-blue-50 dark:hover:bg-gray-700 text-[13px] flex justify-between items-center"
                      >
                        <div>
                          <p className="font-medium text-gray-900 dark:text-white">{order.order_number}</p>
                          <p className="text-gray-500 dark:text-gray-400">{order.customer_name} · {order.status}</p>
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
                  <p className="text-[14px] font-medium text-gray-900 dark:text-white">{eligibility.sales_order_number}</p>
                  <p className="text-[12px] text-gray-500 dark:text-gray-400">{eligibility.customer_name}</p>
                </div>
                <button onClick={() => { setSelectedSo(null); setEligibility(null); }} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
                  <X size={16} />
                </button>
              </div>

              <div className="grid grid-cols-2 gap-x-4">
                <Input label="Challan Date" type="date" value={challanDate} onChange={(e) => setChallanDate(e.target.value)} />
                <Input label="Shipping Address (Optional)" value={shippingAddress} onChange={(e) => setShippingAddress(e.target.value)} />
              </div>

              <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 mt-2">Delivery Quantities</h4>
              <div className="overflow-x-auto mb-4">
                <table className="w-full text-left text-[13px]">
                  <thead>
                    <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                      <th className="py-2 pr-2">Product</th>
                      <th className="py-2 pr-2">Ordered</th>
                      <th className="py-2 pr-2">Delivered</th>
                      <th className="py-2 pr-2">Remaining</th>
                      <th className="py-2">Deliver Now</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                    {eligibility.lines.map((line) => (
                      <tr key={line.sales_order_line_id}>
                        <td className="py-2 pr-2 text-gray-900 dark:text-white">{line.description}</td>
                        <td className="py-2 pr-2 text-gray-500 dark:text-gray-400">{line.ordered_quantity} {line.uom.code}</td>
                        <td className="py-2 pr-2 text-gray-500 dark:text-gray-400">{line.delivered_quantity}</td>
                        <td className="py-2 pr-2 font-medium text-gray-700 dark:text-gray-200">{line.remaining_quantity}</td>
                        <td className="py-2">
                          <input
                            type="number" min="0" step="0.001" max={line.remaining_quantity}
                            disabled={Number(line.remaining_quantity) <= 0}
                            value={quantities[line.sales_order_line_id] || ''}
                            onChange={(e) => setQuantities((prev) => ({ ...prev, [line.sales_order_line_id]: e.target.value }))}
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
                Saving as Draft does not affect inventory — stock is only reduced when the challan is confirmed.
              </p>

              <button
                onClick={handleSave} disabled={isSubmitting}
                className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[15px] font-medium disabled:opacity-70"
              >
                {isSubmitting && <Loader2 size={18} className="animate-spin" />} Save Delivery Challan
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

const ChallanDetailModal: React.FC<{ challanId: string; onClose: () => void; onChanged: () => void; permissions: DetailPermissions }> = ({
  challanId, onClose, onChanged, permissions,
}) => {
  const { showToast } = useToast();
  const [challan, setChallan] = useState<DeliveryChallanDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirmAction, setConfirmAction] = useState<'confirm' | 'cancel' | null>(null);
  const [isActing, setIsActing] = useState(false);
  const [showInvoiceModal, setShowInvoiceModal] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await getDeliveryChallan(challanId);
      setChallan(data);
    } catch {
      showToast('Failed to load delivery challan.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [challanId]);

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

  if (isLoading || !challan) {
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
            <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{challan.challan_number}</h3>
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{challan.customer_name} · {challan.source_sales_order_number}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>

        <div className="p-6 space-y-5 text-[14px]">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[challan.status]}`}>{challan.status}</span>
            <span className="text-gray-500 dark:text-gray-400">Date: {challan.challan_date}</span>
          </div>

          {(challan.billing_address || challan.shipping_address) && (
            <div className="grid grid-cols-2 gap-4 text-[13px]">
              <div>
                <span className="text-gray-400 text-[11px] uppercase block">Billing Address</span>
                <p className="text-gray-600 dark:text-gray-300">{challan.billing_address || '—'}</p>
              </div>
              <div>
                <span className="text-gray-400 text-[11px] uppercase block">Shipping Address</span>
                <p className="text-gray-600 dark:text-gray-300">{challan.shipping_address || '—'}</p>
              </div>
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                  <th className="py-2 pr-2">Product</th><th className="py-2 pr-2">HSN</th>
                  <th className="py-2 pr-2">Ordered</th><th className="py-2 pr-2">Prev. Delivered</th>
                  <th className="py-2 pr-2">This Delivery</th><th className="py-2">Remaining</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {challan.lines.map((line) => (
                  <tr key={line.id}>
                    <td className="py-2 pr-2">{line.description}</td>
                    <td className="py-2 pr-2">{line.hsn_code || '—'}</td>
                    <td className="py-2 pr-2">{line.ordered_quantity} {line.uom.code}</td>
                    <td className="py-2 pr-2">{line.previously_delivered_quantity}</td>
                    <td className="py-2 pr-2 font-medium">{line.current_delivery_quantity}</td>
                    <td className="py-2">{line.remaining_quantity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {challan.notes && <p className="text-gray-600 dark:text-gray-300"><span className="text-gray-400 text-[12px] uppercase block">Notes</span>{challan.notes}</p>}

          <div className="flex flex-wrap gap-2 pt-2">
            {permissions.canConfirm && challan.status === 'DRAFT' && (
              <button disabled={isActing} onClick={() => setConfirmAction('confirm')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium">
                <CheckCircle2 size={14} /> Confirm Delivery
              </button>
            )}
            {permissions.canCancel && challan.status === 'DRAFT' && (
              <button disabled={isActing} onClick={() => setConfirmAction('cancel')} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[13px] font-medium">
                <Ban size={14} /> Cancel
              </button>
            )}
            {permissions.canCreateInvoice && challan.status === 'CONFIRMED' && (
              <button disabled={isActing} onClick={() => setShowInvoiceModal(true)} className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium ml-auto">
                <Receipt size={14} /> Create Sales Invoice
              </button>
            )}
          </div>
        </div>
      </div>

      {showInvoiceModal && (
        <CreateInvoiceFromChallanModal
          challanId={challan.id}
          onClose={() => setShowInvoiceModal(false)}
          onSaved={() => { setShowInvoiceModal(false); onChanged(); }}
        />
      )}

      {confirmAction && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
            <div className="flex items-center gap-3 mb-3">
              <div className={`flex h-10 w-10 items-center justify-center rounded-full shrink-0 ${confirmAction === 'confirm' ? 'bg-blue-100 dark:bg-blue-900/30' : 'bg-amber-100 dark:bg-amber-900/30'}`}>
                <AlertTriangle size={20} className={confirmAction === 'confirm' ? 'text-blue-600 dark:text-blue-400' : 'text-amber-600 dark:text-amber-400'} />
              </div>
              <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">
                {confirmAction === 'confirm' ? 'Confirm Delivery' : 'Cancel Delivery Challan'}
              </h3>
            </div>
            <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-6">
              {confirmAction === 'confirm'
                ? 'This action will reduce inventory. Stock will be dispatched for every line on this challan and cannot be undone.'
                : 'This draft delivery challan will be cancelled. No stock has been affected yet.'}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => setConfirmAction(null)} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Back</button>
              <button
                onClick={() => {
                  if (confirmAction === 'confirm') runAction(() => confirmDeliveryChallan(challan.id, challan.row_version), 'Delivery confirmed — stock updated.');
                  else runAction(() => cancelDeliveryChallan(challan.id, challan.row_version), 'Delivery challan cancelled.');
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

const CreateInvoiceFromChallanModal: React.FC<{ challanId: string; onClose: () => void; onSaved: () => void }> = ({
  challanId, onClose, onSaved,
}) => {
  const { showToast } = useToast();
  const [eligibility, setEligibility] = useState<InvoiceEligibility | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [invoiceDate, setInvoiceDate] = useState(new Date().toISOString().slice(0, 10));
  const [notes, setNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      try {
        const data = await getInvoiceEligibility(challanId);
        setEligibility(data);
        const initial: Record<string, string> = {};
        data.lines.forEach((line) => { initial[line.source_delivery_challan_line_id] = line.invoiceable_quantity; });
        setQuantities(initial);
      } catch (err) {
        showToast(err instanceof ApiError ? err.message : 'Failed to load invoice eligibility.', 'error');
        onClose();
      } finally {
        setIsLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [challanId]);

  const handleSave = async () => {
    if (!eligibility) return;
    const lines: { source_delivery_challan_line_id: string; quantity: string }[] = [];
    for (const line of eligibility.lines) {
      const qty = quantities[line.source_delivery_challan_line_id];
      if (qty && Number(qty) > 0) {
        if (Number(qty) > Number(line.invoiceable_quantity)) {
          showToast(`Invoice quantity for ${line.description} exceeds invoiceable quantity (${line.invoiceable_quantity}).`, 'error');
          return;
        }
        lines.push({ source_delivery_challan_line_id: line.source_delivery_challan_line_id, quantity: qty });
      }
    }
    if (lines.length === 0) { showToast('Enter an invoice quantity for at least one line.', 'error'); return; }

    setIsSubmitting(true);
    try {
      await createInvoiceFromChallan(challanId, {
        invoice_date: invoiceDate || null,
        notes: notes || null,
        lines,
      });
      showToast('Sales invoice created successfully.', 'success');
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
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><Receipt size={18} /> Create Sales Invoice</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>
        <div className="p-6">
          {isLoading || !eligibility ? (
            <div className="flex justify-center py-8"><Loader2 size={24} className="animate-spin text-gray-400" /></div>
          ) : (
            <>
              <div className="flex items-center justify-between px-3 py-2.5 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 mb-4">
                <div>
                  <p className="text-[14px] font-medium text-gray-900 dark:text-white">{eligibility.source_delivery_challan_number}</p>
                  <p className="text-[12px] text-gray-500 dark:text-gray-400">{eligibility.customer_name}</p>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-x-4">
                <Input label="Invoice Date" type="date" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} />
              </div>

              <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3 mt-2">Invoice Quantities</h4>
              <div className="overflow-x-auto mb-4">
                <table className="w-full text-left text-[13px]">
                  <thead>
                    <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                      <th className="py-2 pr-2">Product</th>
                      <th className="py-2 pr-2">Delivered</th>
                      <th className="py-2 pr-2">Invoiced</th>
                      <th className="py-2 pr-2">Invoiceable</th>
                      <th className="py-2">Invoice Now</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                    {eligibility.lines.map((line) => (
                      <tr key={line.source_delivery_challan_line_id}>
                        <td className="py-2 pr-2 text-gray-900 dark:text-white">{line.description}</td>
                        <td className="py-2 pr-2 text-gray-500 dark:text-gray-400">{line.delivered_quantity} {line.uom.code}</td>
                        <td className="py-2 pr-2 text-gray-500 dark:text-gray-400">{line.invoiced_quantity}</td>
                        <td className="py-2 pr-2 font-medium text-gray-700 dark:text-gray-200">{line.invoiceable_quantity}</td>
                        <td className="py-2">
                          <input
                            type="number" min="0" step="0.001" max={line.invoiceable_quantity}
                            disabled={Number(line.invoiceable_quantity) <= 0}
                            value={quantities[line.source_delivery_challan_line_id] || ''}
                            onChange={(e) => setQuantities((prev) => ({ ...prev, [line.source_delivery_challan_line_id]: e.target.value }))}
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
                Inventory was already reduced when this delivery challan was confirmed — creating and posting this invoice will NOT reduce inventory again.
              </p>

              <button
                onClick={handleSave} disabled={isSubmitting}
                className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[15px] font-medium disabled:opacity-70"
              >
                {isSubmitting && <Loader2 size={18} className="animate-spin" />} Save Sales Invoice
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default DeliveryChallanManagement;
