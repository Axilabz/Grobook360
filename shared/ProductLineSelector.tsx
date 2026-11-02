import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Search, Plus } from 'lucide-react';
import { Product, listProducts, getProduct } from '../api/products';
import Input from '../components/Input';
import Select from '../components/Select';
import LoadingState from './LoadingState';

/**
 * Reusable Sales & Billing foundation piece (PROMPT-011 S51): a
 * server-side, tenant-scoped product search + line-entry control. No
 * concrete Sales document screen exists yet — built now so the next
 * document-type prompt doesn't reinvent product search/unit-conversion
 * wiring. The gross/discount/taxable preview shown here is a client-side
 * ESTIMATE for UX only (§60) — the server independently recalculates and
 * is the sole authority once a real Sales document endpoint exists.
 */
export interface SalesLineDraft {
  product: Product;
  quantity: string;
  uomId: string;
  uomCode: string;
  unitPrice: string;
  discountPercent: string;
  discountAmount: string;
}

interface ProductLineSelectorProps {
  onAdd: (line: SalesLineDraft) => void;
}

const ProductLineSelector: React.FC<ProductLineSelectorProps> = ({ onAdd }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Product[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const [selected, setSelected] = useState<Product | null>(null);
  const [unitOptions, setUnitOptions] = useState<{ id: string; code: string }[]>([]);
  const [uomCode, setUomCode] = useState('');
  const [quantity, setQuantity] = useState('1');
  const [unitPrice, setUnitPrice] = useState('0');
  const [discountPercent, setDiscountPercent] = useState('');
  const [discountAmount, setDiscountAmount] = useState('');

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) setIsOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const search = useCallback(async (term: string) => {
    setIsLoading(true);
    try {
      const result = await listProducts({ search: term || undefined, status: 'ACTIVE', page_size: 10 });
      setResults(result.data);
    } catch {
      setResults([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    const timer = setTimeout(() => search(query), 300);
    return () => clearTimeout(timer);
  }, [query, isOpen, search]);

  const handleSelectProduct = async (product: Product) => {
    setSelected(product);
    setUnitPrice(product.selling_price);
    setUomCode(product.base_uom.code);
    setIsOpen(false);
    setQuery('');
    try {
      const detail = await getProduct(product.id);
      const options = [
        { id: detail.base_uom.id, code: detail.base_uom.code },
        ...detail.unit_conversions
          .filter((c) => c.to_uom.id === detail.base_uom.id)
          .map((c) => ({ id: c.from_uom.id, code: c.from_uom.code })),
      ];
      setUnitOptions(options);
    } catch {
      setUnitOptions([{ id: product.base_uom.id, code: product.base_uom.code }]);
    }
  };

  const gross = selected ? Number(quantity || 0) * Number(unitPrice || 0) : 0;
  const discount = discountAmount
    ? Number(discountAmount)
    : discountPercent
    ? (gross * Number(discountPercent)) / 100
    : 0;
  const taxable = Math.max(gross - discount, 0);
  const gstRate = selected?.gst_rate ? Number(selected.gst_rate) : 0;
  const estimatedTax = taxable * (gstRate / 100);
  const estimatedTotal = taxable + estimatedTax;

  const handleAdd = () => {
    if (!selected || Number(quantity) <= 0) return;
    const uom = unitOptions.find((u) => u.code === uomCode) || unitOptions[0];
    onAdd({
      product: selected,
      quantity,
      uomId: uom.id,
      uomCode: uom.code,
      unitPrice,
      discountPercent: discountPercent || '0',
      discountAmount: discountAmount || '0',
    });
    setSelected(null);
    setQuantity('1');
    setUnitPrice('0');
    setDiscountPercent('');
    setDiscountAmount('');
  };

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-gray-50 dark:bg-gray-900">
      <div className="relative mb-4" ref={containerRef}>
        <label className="block text-[13px] font-medium text-gray-600 dark:text-gray-400 mb-1.5">Add Product</label>
        <div className="relative">
          <input
            type="text"
            value={selected ? selected.name : query}
            onChange={(e) => { setQuery(e.target.value); setSelected(null); }}
            onFocus={() => { setIsOpen(true); if (results.length === 0) search(''); }}
            placeholder="Search product by name, SKU…"
            className="w-full pl-9 pr-3 py-2.5 rounded-md border border-gray-300 dark:border-gray-600 text-[14px] bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:border-blue-500 focus:ring-blue-500"
          />
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        </div>
        {isOpen && !selected && (
          <div className="absolute z-30 mt-1 w-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md shadow-lg max-h-64 overflow-auto">
            {isLoading ? (
              <div className="flex justify-center py-4"><LoadingState bare compact /></div>
            ) : results.length === 0 ? (
              <p className="px-3 py-3 text-[13px] text-gray-400 italic">No products found.</p>
            ) : (
              results.map((product) => (
                <button
                  type="button"
                  key={product.id}
                  onClick={() => handleSelectProduct(product)}
                  className="w-full text-left px-3 py-2.5 hover:bg-blue-50 dark:hover:bg-gray-700 text-[13px] flex justify-between items-center"
                >
                  <div>
                    <p className="font-medium text-gray-900 dark:text-white">{product.name}</p>
                    <p className="text-gray-500 dark:text-gray-400">{product.sku} · {product.base_uom.code}</p>
                  </div>
                  <span className="text-gray-600 dark:text-gray-300">₹{product.selling_price}</span>
                </button>
              ))
            )}
          </div>
        )}
      </div>

      {selected && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-x-3">
            <Input label="Quantity" type="number" min={0} step="0.001" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
            <Select label="Unit" options={unitOptions.map((u) => u.code)} value={uomCode} onChange={setUomCode} />
            <Input label="Unit Price (₹)" type="number" min={0} step="0.01" value={unitPrice} onChange={(e) => setUnitPrice(e.target.value)} />
            <Input
              label="Discount % or ₹"
              type="number"
              min={0}
              step="0.01"
              value={discountAmount || discountPercent}
              onChange={(e) => setDiscountAmount(e.target.value)}
            />
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-md p-3 mb-4 text-[13px] space-y-1 border border-gray-200 dark:border-gray-700">
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Gross Amount</span><span>₹{gross.toFixed(2)}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Discount</span><span>−₹{discount.toFixed(2)}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Taxable Amount</span><span>₹{taxable.toFixed(2)}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Est. GST ({gstRate}%)</span><span>₹{estimatedTax.toFixed(2)}</span></div>
            <div className="flex justify-between font-semibold text-gray-900 dark:text-white pt-1 border-t border-gray-100 dark:border-gray-700">
              <span>Estimated Line Total</span><span>₹{estimatedTotal.toFixed(2)}</span>
            </div>
            <p className="text-[11px] text-gray-400 pt-1">Estimate only — the server independently calculates and validates the final amount.</p>
          </div>

          <button
            type="button"
            onClick={handleAdd}
            disabled={Number(quantity) <= 0}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium disabled:opacity-50"
          >
            <Plus size={16} /> Add Line
          </button>
        </>
      )}
    </div>
  );
};

export default ProductLineSelector;
