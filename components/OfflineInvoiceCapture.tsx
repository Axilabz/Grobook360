import React, { useState, useEffect, useCallback } from 'react';
import { X, Plus, Trash2, Info, Loader2, UserPlus } from 'lucide-react';
import { useToast } from '../context/ToastContext';
import { readCachedProducts, readCachedCustomers, readCachedUnits, oldestSync, CachedRecordWithFreshness } from '../pwa/masterDataCache';
import { createOfflineInvoice, calculateProvisionalLine, calculateProvisionalTotals, ProvisionalLineInput } from '../pwa/offlineInvoiceService';
import { createOfflineCustomer } from '../pwa/offlineCustomerSupplierService';
import { Product } from '../api/products';
import { Customer } from '../api/customers';
import { UnitOfMeasure } from '../api/units';

interface DraftLine {
  key: string;
  product_id: string;
  product_name: string;
  uom_id: string;
  gst_rate: number;
  quantity: string;
  unit_price: string;
  discount_percent: string;
}

const OfflineInvoiceCapture: React.FC<{ tenantId: string; userId: string; onClose: () => void; onCreated: () => void }> = ({ tenantId, userId, onClose, onCreated }) => {
  const { showToast } = useToast();
  const [products, setProducts] = useState<CachedRecordWithFreshness<Product>[]>([]);
  const [customers, setCustomers] = useState<CachedRecordWithFreshness<Customer>[]>([]);
  const [units, setUnits] = useState<CachedRecordWithFreshness<UnitOfMeasure>[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const [customerId, setCustomerId] = useState('');
  const [showQuickAdd, setShowQuickAdd] = useState(false);
  const [quickAddName, setQuickAddName] = useState('');
  const [quickAddPhone, setQuickAddPhone] = useState('');
  const [offlineCustomerQueueId, setOfflineCustomerQueueId] = useState<string | null>(null);
  const [offlineCustomerLabel, setOfflineCustomerLabel] = useState<string | null>(null);

  const [lines, setLines] = useState<DraftLine[]>([]);
  const [isSaving, setIsSaving] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const [p, c, u] = await Promise.all([readCachedProducts(tenantId), readCachedCustomers(tenantId), readCachedUnits(tenantId)]);
      setProducts(p);
      setCustomers(c);
      setUnits(u);
    } finally {
      setIsLoading(false);
    }
  }, [tenantId]);

  useEffect(() => { load(); }, [load]);

  const addLine = () => {
    setLines((prev) => [...prev, { key: `${Date.now()}-${prev.length}`, product_id: '', product_name: '', uom_id: '', gst_rate: 0, quantity: '1', unit_price: '0', discount_percent: '0' }]);
  };

  const updateLine = (key: string, patch: Partial<DraftLine>) => {
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  };

  const onSelectProduct = (key: string, productId: string) => {
    const found = products.find((p) => p.record.id === productId);
    if (!found) return;
    updateLine(key, {
      product_id: productId, product_name: found.record.name, uom_id: found.record.base_uom_id,
      gst_rate: Number(found.record.gst_rate ?? 0), unit_price: String(found.record.selling_price ?? '0'),
    });
  };

  const removeLine = (key: string) => setLines((prev) => prev.filter((l) => l.key !== key));

  const handleQuickAddCustomer = async () => {
    if (!quickAddName.trim() || !quickAddPhone.trim()) {
      showToast('Name and phone are required.', 'error');
      return;
    }
    const item = await createOfflineCustomer({ tenantId, userId, name: quickAddName.trim(), phone: quickAddPhone.trim() });
    setOfflineCustomerQueueId(item.queue_id);
    setOfflineCustomerLabel(`${quickAddName.trim()} (offline — will sync as ${item.local_reference})`);
    setCustomerId('');
    setShowQuickAdd(false);
    showToast('Customer saved offline — will sync automatically.', 'success');
  };

  const provisionalLines = lines
    .filter((l) => l.product_id && Number(l.quantity) > 0)
    .map((l) =>
      calculateProvisionalLine({
        product_id: l.product_id, product_name: l.product_name, quantity: Number(l.quantity), uom_id: l.uom_id,
        unit_price: Number(l.unit_price), gst_rate: l.gst_rate, discount_percent: Number(l.discount_percent) || 0,
      } as ProvisionalLineInput)
    );
  const totals = calculateProvisionalTotals(provisionalLines);

  const canSave = (customerId || offlineCustomerQueueId) && provisionalLines.length > 0 && !isSaving;

  const handleSave = async () => {
    if (!canSave) return;
    setIsSaving(true);
    try {
      const item = await createOfflineInvoice({
        tenantId, userId,
        customerId: offlineCustomerQueueId ? '' : customerId,
        customerIsOfflineDraft: !!offlineCustomerQueueId,
        customerDependsOnQueueId: offlineCustomerQueueId || undefined,
        lines: provisionalLines.map((l) => ({ product_id: l.product_id, product_name: l.product_name, quantity: l.quantity, uom_id: l.uom_id, unit_price: l.unit_price, gst_rate: l.gst_rate, discount_percent: l.discount_percent })),
      });
      showToast(`Saved offline as ${item.local_reference}. It will sync automatically when you're online.`, 'success');
      onCreated();
    } catch {
      showToast('Failed to save offline invoice.', 'error');
    } finally {
      setIsSaving(false);
    }
  };

  const productsFreshness = oldestSync(products);
  const customersFreshness = oldestSync(customers);

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-3xl max-h-[92vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">New Offline Sales Invoice</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
        ) : (
          <div className="p-6 space-y-5 text-[14px]">
            <div className="flex items-start gap-2 text-[12px] text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-900 rounded-md p-3">
              <Info size={14} className="shrink-0 mt-0.5" />
              Totals shown here are PROVISIONAL — the server recalculates the authoritative taxable value, GST (CGST/SGST/IGST split) and total when this invoice syncs. The invoice number shown now is a temporary reference only.
              {productsFreshness && <> Product prices last synced: {new Date(productsFreshness).toLocaleString()}.</>}
            </div>

            {products.length === 0 && (
              <div className="text-[13px] text-amber-600 dark:text-amber-400">No offline product data is cached yet. Go online and use "Refresh Offline Data" in the Sync Center before creating offline invoices.</div>
            )}

            <div>
              <label className="block text-[12px] font-medium text-gray-500 dark:text-gray-400 mb-1">Customer</label>
              {offlineCustomerLabel ? (
                <div className="flex items-center justify-between border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-blue-50 dark:bg-blue-900/20 text-[13px] text-blue-700 dark:text-blue-400">
                  {offlineCustomerLabel}
                  <button onClick={() => { setOfflineCustomerQueueId(null); setOfflineCustomerLabel(null); }} className="text-gray-400 hover:text-gray-600"><X size={14} /></button>
                </div>
              ) : (
                <div className="flex gap-2">
                  <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} className="flex-1 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] px-3 py-2">
                    <option value="">Select a customer…</option>
                    {customers.map((c) => <option key={c.record.id} value={c.record.id}>{c.record.name}</option>)}
                  </select>
                  <button onClick={() => setShowQuickAdd(true)} className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[13px] whitespace-nowrap">
                    <UserPlus size={14} /> New
                  </button>
                </div>
              )}
              {customersFreshness && <p className="text-[11px] text-gray-400 mt-1">Customer list last synced: {new Date(customersFreshness).toLocaleString()}</p>}
            </div>

            {showQuickAdd && (
              <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-3 space-y-2 bg-gray-50 dark:bg-gray-900">
                <p className="text-[12px] font-medium text-gray-600 dark:text-gray-300">Quick-add Customer (offline)</p>
                <input value={quickAddName} onChange={(e) => setQuickAddName(e.target.value)} placeholder="Name" className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-1.5 text-[13px] bg-white dark:bg-gray-800" />
                <input value={quickAddPhone} onChange={(e) => setQuickAddPhone(e.target.value)} placeholder="Phone" className="w-full border border-gray-300 dark:border-gray-600 rounded-md px-3 py-1.5 text-[13px] bg-white dark:bg-gray-800" />
                <div className="flex gap-2">
                  <button onClick={handleQuickAddCustomer} className="px-3 py-1.5 rounded-md bg-[#0066ff] text-white text-[12px] font-medium">Save Offline</button>
                  <button onClick={() => setShowQuickAdd(false)} className="px-3 py-1.5 rounded-md border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[12px]">Cancel</button>
                </div>
              </div>
            )}

            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-[12px] font-medium text-gray-500 dark:text-gray-400">Line Items</label>
                <button onClick={addLine} className="flex items-center gap-1 text-[12px] text-[#0066ff] font-medium"><Plus size={14} /> Add Line</button>
              </div>
              <div className="space-y-2">
                {lines.map((line) => (
                  <div key={line.key} className="grid grid-cols-12 gap-2 items-center border border-gray-200 dark:border-gray-700 rounded-lg p-2">
                    <select value={line.product_id} onChange={(e) => onSelectProduct(line.key, e.target.value)} className="col-span-5 border border-gray-300 dark:border-gray-600 rounded-md px-2 py-1.5 text-[13px] bg-white dark:bg-gray-800">
                      <option value="">Select product…</option>
                      {products.map((p) => <option key={p.record.id} value={p.record.id}>{p.record.sku} — {p.record.name}</option>)}
                    </select>
                    <input type="number" min="0" step="0.001" value={line.quantity} onChange={(e) => updateLine(line.key, { quantity: e.target.value })} placeholder="Qty" className="col-span-2 border border-gray-300 dark:border-gray-600 rounded-md px-2 py-1.5 text-[13px] bg-white dark:bg-gray-800" />
                    <input type="number" min="0" step="0.01" value={line.unit_price} onChange={(e) => updateLine(line.key, { unit_price: e.target.value })} placeholder="Price" className="col-span-2 border border-gray-300 dark:border-gray-600 rounded-md px-2 py-1.5 text-[13px] bg-white dark:bg-gray-800" />
                    <input type="number" min="0" max="100" step="0.01" value={line.discount_percent} onChange={(e) => updateLine(line.key, { discount_percent: e.target.value })} placeholder="Disc %" className="col-span-2 border border-gray-300 dark:border-gray-600 rounded-md px-2 py-1.5 text-[13px] bg-white dark:bg-gray-800" />
                    <button onClick={() => removeLine(line.key)} className="col-span-1 text-gray-400 hover:text-red-600 flex justify-center"><Trash2 size={16} /></button>
                  </div>
                ))}
                {lines.length === 0 && <p className="text-[13px] text-gray-400 text-center py-4">No lines added yet.</p>}
              </div>
            </div>

            <div className="bg-gray-50 dark:bg-gray-900 rounded-md p-4 space-y-1 border border-gray-200 dark:border-gray-700">
              <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Taxable (provisional)</span><span>₹{totals.taxable_total.toFixed(2)}</span></div>
              <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>GST (provisional, split TBD)</span><span>₹{totals.gst_total.toFixed(2)}</span></div>
              <div className="flex justify-between font-semibold pt-1 border-t border-gray-100 dark:border-gray-700 text-gray-900 dark:text-white"><span>Total (provisional)</span><span>₹{totals.grand_total.toFixed(2)}</span></div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <button onClick={onClose} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Cancel</button>
              <button onClick={handleSave} disabled={!canSave} className="py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium disabled:opacity-50">
                {isSaving ? 'Saving…' : 'Save Offline'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default OfflineInvoiceCapture;
