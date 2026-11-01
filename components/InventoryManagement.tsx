import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Search, ChevronLeft, ChevronRight, X, Loader2, AlertTriangle, PackagePlus,
  PackageMinus, ClipboardList, History, Boxes,
} from 'lucide-react';
import Input from './Input';
import Select from './Select';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import MobileFilterToggle from '../shared/MobileFilterToggle';
import MobileAccordionCard from '../shared/MobileAccordionCard';
import { ApiError } from '../api/client';
import {
  InventoryItem,
  StockMovement,
  listInventory,
  listMovements,
  createOpeningStock,
  createStockIn,
  createStockOut,
  createAdjustment,
} from '../api/inventory';
import { getProduct, ProductDetail } from '../api/products';

const STATUS_BADGE: Record<string, string> = {
  ACTIVE: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  INACTIVE: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};

type ActionType = 'opening' | 'in' | 'out' | 'adjust';

const InventoryManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const canOpeningStock = hasPermission('inventory.opening_stock');
  const canStockIn = hasPermission('inventory.stock_in');
  const canStockOut = hasPermission('inventory.stock_out');
  const canAdjust = hasPermission('inventory.adjust');

  const [items, setItems] = useState<InventoryItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [stockStatus, setStockStatus] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [showMobileFilters, setShowMobileFilters] = useState(false);

  const [historyItem, setHistoryItem] = useState<InventoryItem | null>(null);
  const [actionState, setActionState] = useState<{ item: InventoryItem; type: ActionType } | null>(null);

  const fetchInventory = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listInventory({
        page,
        page_size: 10,
        search: search || undefined,
        stock_status: (stockStatus || undefined) as any,
      });
      setItems(result.data);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load inventory.', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [page, search, stockStatus, showToast]);

  useEffect(() => {
    fetchInventory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, stockStatus]);

  // Skip the first run: the page/status effect already loads the initial list,
  // so debouncing on mount would fire a duplicate request.
  const searchMountedRef = useRef(false);
  useEffect(() => {
    if (!searchMountedRef.current) {
      searchMountedRef.current = true;
      return;
    }
    const timer = setTimeout(() => {
      setPage(1);
      fetchInventory();
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const anyActionPermission = canOpeningStock || canStockIn || canStockOut || canAdjust;

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 flex flex-col md:flex-row justify-between items-stretch md:items-center gap-4 shadow-sm">
        <div className="flex items-center justify-between gap-3 md:block">
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">
            Inventory
          </h2>
          <MobileFilterToggle open={showMobileFilters} onClick={() => setShowMobileFilters((v) => !v)} />
        </div>

        <div className={`${showMobileFilters ? 'flex' : 'hidden'} md:flex flex-col sm:flex-row gap-3 w-full md:w-auto`}>
          <div className="relative w-full sm:w-64">
            <input
              type="text"
              placeholder="Search product, SKU…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-colors text-[14px]"
            />
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
          </div>

          <select
            value={stockStatus}
            onChange={(e) => { setStockStatus(e.target.value); setPage(1); }}
            className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2"
          >
            <option value="">All Stock</option>
            <option value="in_stock">In Stock</option>
            <option value="zero_stock">Zero Stock</option>
            <option value="low_stock">Low Stock</option>
          </select>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={28} className="animate-spin text-gray-400" />
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No inventory records found.</div>
      ) : (
        <>
          {/* Desktop / tablet table */}
          <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    {[
                      { label: 'SKU', align: 'text-left' }, { label: 'Product', align: 'text-left' }, { label: 'Unit', align: 'text-left' },
                      { label: 'Current Stock', align: 'text-right' }, { label: 'Status', align: 'text-left' }, { label: 'Last Movement', align: 'text-right' },
                      { label: 'Actions', align: 'text-center' },
                    ].map((h) => (
                      <th key={h.label} className={`px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider ${h.align}`}>{h.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {items.map((item) => (
                    <tr key={item.product_id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{item.sku}</td>
                      <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap text-left">
                        <button onClick={() => setHistoryItem(item)} className="hover:text-[#0066ff] hover:underline text-left">
                          {item.name}
                        </button>
                      </td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-left">{item.base_uom.code}</td>
                      <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">
                        <span className="flex items-center justify-end gap-1.5">
                          {item.current_stock}
                          {item.is_low_stock && <span title="Low stock"><AlertTriangle size={14} className="text-amber-500" /></span>}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-left">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[item.product_status]}`}>
                          {item.product_status}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-right">
                        {item.last_movement_at ? new Date(item.last_movement_at).toLocaleDateString() : '—'}
                      </td>
                      <td className="px-6 py-4 text-center whitespace-nowrap">
                        <div className="flex items-center justify-center gap-1.5">
                          <button onClick={() => setHistoryItem(item)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="View History">
                            <History size={16} />
                          </button>
                          {canOpeningStock && (
                            <button onClick={() => setActionState({ item, type: 'opening' })} className="p-1.5 rounded hover:bg-blue-50 dark:hover:bg-blue-900/20 text-blue-600" title="Opening Stock">
                              <Boxes size={16} />
                            </button>
                          )}
                          {canStockIn && (
                            <button onClick={() => setActionState({ item, type: 'in' })} className="p-1.5 rounded hover:bg-green-50 dark:hover:bg-green-900/20 text-green-600" title="Stock In">
                              <PackagePlus size={16} />
                            </button>
                          )}
                          {canStockOut && (
                            <button onClick={() => setActionState({ item, type: 'out' })} className="p-1.5 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500" title="Stock Out">
                              <PackageMinus size={16} />
                            </button>
                          )}
                          {canAdjust && (
                            <button onClick={() => setActionState({ item, type: 'adjust' })} className="p-1.5 rounded hover:bg-amber-50 dark:hover:bg-amber-900/20 text-amber-600" title="Adjust">
                              <ClipboardList size={16} />
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
            {items.map((item) => (
              <MobileAccordionCard
                key={item.product_id}
                title={item.name}
                subtitle={`${item.sku} · ${item.base_uom.code}`}
                badge={
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[item.product_status]}`}>
                    {item.product_status}
                  </span>
                }
              >
                <p className="text-[13px] text-gray-600 dark:text-gray-300 mb-3 flex items-center gap-1.5">
                  Stock: <span className="font-medium">{item.current_stock} {item.base_uom.code}</span>
                  {item.is_low_stock && <AlertTriangle size={12} className="text-amber-500" />}
                </p>
                {anyActionPermission && (
                  <div className="flex flex-wrap gap-2">
                    <button onClick={() => setHistoryItem(item)} className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300">
                      <History size={14} /> History
                    </button>
                    {canOpeningStock && (
                      <button onClick={() => setActionState({ item, type: 'opening' })} className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-blue-300 dark:border-blue-800 text-blue-600">
                        <Boxes size={14} /> Opening
                      </button>
                    )}
                    {canStockIn && (
                      <button onClick={() => setActionState({ item, type: 'in' })} className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-green-300 dark:border-green-800 text-green-600">
                        <PackagePlus size={14} /> In
                      </button>
                    )}
                    {canStockOut && (
                      <button onClick={() => setActionState({ item, type: 'out' })} className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-red-300 dark:border-red-800 text-red-600">
                        <PackageMinus size={14} /> Out
                      </button>
                    )}
                    {canAdjust && (
                      <button onClick={() => setActionState({ item, type: 'adjust' })} className="flex-1 flex items-center justify-center gap-1.5 text-[13px] py-2 rounded-lg border border-amber-300 dark:border-amber-800 text-amber-600">
                        <ClipboardList size={14} /> Adjust
                      </button>
                    )}
                  </div>
                )}
              </MobileAccordionCard>
            ))}
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between mt-4 px-1">
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{totalItems} product{totalItems === 1 ? '' : 's'}</p>
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

      {historyItem && (
        <StockHistoryModal item={historyItem} onClose={() => setHistoryItem(null)} />
      )}

      {actionState && (
        <StockActionModal
          item={actionState.item}
          type={actionState.type}
          onClose={() => setActionState(null)}
          onSaved={() => { setActionState(null); fetchInventory(); }}
        />
      )}
    </div>
  );
};

const MOVEMENT_LABEL: Record<string, string> = {
  OPENING_STOCK: 'Opening Stock',
  STOCK_IN: 'Stock In',
  STOCK_OUT: 'Stock Out',
  ADJUSTMENT_IN: 'Adjustment (In)',
  ADJUSTMENT_OUT: 'Adjustment (Out)',
};

const StockHistoryModal: React.FC<{ item: InventoryItem; onClose: () => void }> = ({ item, onClose }) => {
  const { showToast } = useToast();
  const [movements, setMovements] = useState<StockMovement[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    listMovements(item.product_id, { page_size: 50 })
      .then((result) => setMovements(result.data))
      .catch(() => showToast('Failed to load movement history.', 'error'))
      .finally(() => setIsLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.product_id]);

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <div>
            <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{item.name}</h3>
            <p className="text-[13px] text-gray-500 dark:text-gray-400">
              {item.sku} · Current Stock: {item.current_stock} {item.base_uom.code}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X size={20} />
          </button>
        </div>
        <div className="p-6">
          {isLoading ? (
            <div className="flex justify-center py-8"><Loader2 size={24} className="animate-spin text-gray-400" /></div>
          ) : movements.length === 0 ? (
            <p className="text-center text-gray-500 dark:text-gray-400 py-8">No stock movements recorded yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[13px]">
                <thead>
                  <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                    <th className="py-2 pr-3">Date</th>
                    <th className="py-2 pr-3">Type</th>
                    <th className="py-2 pr-3">Qty</th>
                    <th className="py-2 pr-3">Balance</th>
                    <th className="py-2">Reference</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {movements.map((m) => (
                    <tr key={m.id}>
                      <td className="py-2 pr-3 whitespace-nowrap">{new Date(m.occurred_at).toLocaleString()}</td>
                      <td className="py-2 pr-3 whitespace-nowrap">{MOVEMENT_LABEL[m.movement_type] || m.movement_type}</td>
                      <td className="py-2 pr-3 whitespace-nowrap">{m.quantity} {m.uom.code}</td>
                      <td className="py-2 pr-3 whitespace-nowrap font-medium">{m.running_balance} {item.base_uom.code}</td>
                      <td className="py-2 text-gray-500 dark:text-gray-400">{m.reason || m.source_type}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const ACTION_META: Record<ActionType, { title: string; icon: React.ReactNode; submitLabel: string }> = {
  opening: { title: 'Record Opening Stock', icon: <Boxes size={18} />, submitLabel: 'Record Opening Stock' },
  in: { title: 'Stock In', icon: <PackagePlus size={18} />, submitLabel: 'Record Stock In' },
  out: { title: 'Stock Out', icon: <PackageMinus size={18} />, submitLabel: 'Record Stock Out' },
  adjust: { title: 'Stock Adjustment', icon: <ClipboardList size={18} />, submitLabel: 'Post Adjustment' },
};

const StockActionModal: React.FC<{ item: InventoryItem; type: ActionType; onClose: () => void; onSaved: () => void }> = ({
  item,
  type,
  onClose,
  onSaved,
}) => {
  const { showToast } = useToast();
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [quantity, setQuantity] = useState('');
  const [unitCode, setUnitCode] = useState(item.base_uom.code);
  const [direction, setDirection] = useState<'IN' | 'OUT'>('IN');
  const [reason, setReason] = useState('');
  const [notes, setNotes] = useState('');
  const [unitCost, setUnitCost] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    getProduct(item.product_id).then(setProduct).catch(() => {});
  }, [item.product_id]);

  const unitOptions = product
    ? [product.base_uom.code, ...product.unit_conversions.filter((c) => c.to_uom.id === product.base_uom.id).map((c) => c.from_uom.code)]
    : [item.base_uom.code];

  const resolveUomId = (code: string): string | undefined => {
    if (!product) return item.base_uom.id;
    if (code === product.base_uom.code) return product.base_uom.id;
    return product.unit_conversions.find((c) => c.from_uom.code === code)?.from_uom.id;
  };

  const validate = (): boolean => {
    const next: Record<string, string> = {};
    if (!quantity || isNaN(Number(quantity)) || Number(quantity) <= 0) next.quantity = 'Quantity must be greater than zero';
    if (type === 'adjust' && !reason.trim()) next.reason = 'A reason is required for stock adjustments';
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSubmit = async () => {
    if (!validate()) return;
    const uomId = resolveUomId(unitCode);
    if (!uomId) {
      showToast('Select a valid unit.', 'error');
      return;
    }
    setIsSubmitting(true);
    try {
      if (type === 'opening') {
        await createOpeningStock({ product_id: item.product_id, quantity, uom_id: uomId, unit_cost: unitCost || null });
      } else if (type === 'in') {
        await createStockIn({ product_id: item.product_id, quantity, uom_id: uomId, notes: notes || null, unit_cost: unitCost || null });
      } else if (type === 'out') {
        await createStockOut({ product_id: item.product_id, quantity, uom_id: uomId, notes: notes || null });
      } else {
        await createAdjustment({
          product_id: item.product_id, quantity, uom_id: uomId, direction, reason,
          unit_cost: direction === 'IN' ? unitCost || null : null,
        });
      }
      showToast('Stock movement recorded successfully.', 'success');
      onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.code === 'INV-003') {
        showToast(err.message, 'error');
      } else if (err instanceof ApiError && err.code === 'INV-004') {
        showToast('Opening stock has already been recorded for this product.', 'error');
      } else if (err instanceof ApiError && err.code === 'INV-002') {
        showToast('Unable to convert the selected unit.', 'error');
      } else if (err instanceof ApiError && err.code === 'INV-006') {
        showToast('This product is inactive and cannot be used for this operation.', 'error');
      } else {
        showToast(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.', 'error');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const meta = ACTION_META[type];
  const resultingStock =
    quantity && !isNaN(Number(quantity))
      ? type === 'out' || (type === 'adjust' && direction === 'OUT')
        ? (Number(item.current_stock) - Number(quantity)).toString()
        : (Number(item.current_stock) + Number(quantity)).toString()
      : null;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-md max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2">
            {meta.icon} {meta.title}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X size={20} />
          </button>
        </div>
        <div className="p-6">
          <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-4">
            <span className="font-medium text-gray-900 dark:text-white">{item.name}</span> ({item.sku})
          </p>

          {type === 'adjust' && (
            <div className="mb-6">
              <label className="block text-[13px] font-medium text-gray-600 dark:text-gray-400 mb-2">Direction</label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setDirection('IN')}
                  className={`py-2 rounded-lg border text-[14px] font-medium ${direction === 'IN' ? 'bg-green-50 dark:bg-green-900/20 border-green-400 text-green-700 dark:text-green-400' : 'border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300'}`}
                >
                  Increase (+)
                </button>
                <button
                  type="button"
                  onClick={() => setDirection('OUT')}
                  className={`py-2 rounded-lg border text-[14px] font-medium ${direction === 'OUT' ? 'bg-red-50 dark:bg-red-900/20 border-red-400 text-red-700 dark:text-red-400' : 'border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300'}`}
                >
                  Decrease (−)
                </button>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-x-4">
            <Input label="Quantity" type="number" min={0} step="0.001" value={quantity} onChange={(e) => setQuantity(e.target.value)} error={errors.quantity} />
            <Select label="Unit" options={unitOptions} value={unitCode} onChange={setUnitCode} />
          </div>

          {type === 'adjust' ? (
            <Input label="Reason (e.g. Physical count correction)" value={reason} onChange={(e) => setReason(e.target.value)} error={errors.reason} />
          ) : (type === 'in' || type === 'out') ? (
            <Input label="Notes (Optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
          ) : null}

          {(type === 'opening' || type === 'in' || (type === 'adjust' && direction === 'IN')) && (
            <div className="mb-2">
              <Input
                label="Unit Cost — ₹ per base unit (Optional)"
                type="number" min={0} step="0.01"
                value={unitCost}
                onChange={(e) => setUnitCost(e.target.value)}
              />
              <p className="text-[12px] text-gray-400 mt-1">
                {product && Number(product.cost_price) > 0
                  ? `Leave blank to use the current average cost (₹${product.cost_price}/${item.base_uom.code}) — the stock still updates either way, just without a fresh accounting entry if left blank.`
                  : 'Leave blank if unknown — stock will still update, just without an accounting entry for this movement.'}
              </p>
            </div>
          )}

          {resultingStock !== null && (
            <div className="bg-gray-50 dark:bg-gray-900 rounded-lg p-4 mb-6 text-[14px] space-y-1">
              <div className="flex justify-between text-gray-500 dark:text-gray-400">
                <span>Current Stock</span><span>{item.current_stock} {item.base_uom.code}</span>
              </div>
              <div className={`flex justify-between font-semibold ${Number(resultingStock) < 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-900 dark:text-white'}`}>
                <span>Resulting Stock</span><span>{resultingStock} {item.base_uom.code}</span>
              </div>
              {Number(resultingStock) < 0 && (
                <p className="text-red-600 dark:text-red-400 text-[12px] pt-1">
                  Insufficient stock — this request will be rejected.
                </p>
              )}
            </div>
          )}

          <button
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="w-full bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] py-3 rounded-lg transition-colors disabled:opacity-70 flex items-center justify-center gap-2"
          >
            {isSubmitting && <Loader2 size={18} className="animate-spin" />}
            {meta.submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
};

export default InventoryManagement;
