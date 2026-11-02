import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Search, X } from 'lucide-react';
import { Supplier, listSuppliers } from '../api/suppliers';
import LoadingState from './LoadingState';

/**
 * Purchase Management Foundation's counterpart to `CustomerSelector.tsx`
 * (PROMPT-011/012) — a server-side, tenant-scoped supplier search-select,
 * reused by Purchase Order and direct Purchase Invoice creation. Mirrors
 * that component's structure exactly. Server-side search only; never
 * loads the full supplier list into the browser.
 */
interface SupplierSelectorProps {
  value: Supplier | null;
  onChange: (supplier: Supplier | null) => void;
  /** Exclude INACTIVE suppliers from results (default true). */
  activeOnly?: boolean;
  label?: string;
  error?: string;
}

const SupplierSelector: React.FC<SupplierSelectorProps> = ({ value, onChange, activeOnly = true, label = 'Supplier', error }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Supplier[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const search = useCallback(async (term: string) => {
    setIsLoading(true);
    try {
      const result = await listSuppliers({
        search: term || undefined,
        status: activeOnly ? 'ACTIVE' : undefined,
        page_size: 10,
      });
      setResults(result.data);
    } catch {
      setResults([]);
    } finally {
      setIsLoading(false);
    }
  }, [activeOnly]);

  useEffect(() => {
    if (!isOpen) return;
    const timer = setTimeout(() => search(query), 300);
    return () => clearTimeout(timer);
  }, [query, isOpen, search]);

  const handleFocus = () => {
    setIsOpen(true);
    if (results.length === 0) search('');
  };

  const handleSelect = (supplier: Supplier) => {
    onChange(supplier);
    setIsOpen(false);
    setQuery('');
  };

  return (
    <div className="relative mb-6 w-full" ref={containerRef}>
      <label className="block text-[13px] font-medium text-gray-600 dark:text-gray-400 mb-1.5">{label}</label>
      {value ? (
        <div className="flex items-center justify-between px-3 py-2.5 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800">
          <div>
            <p className="text-[14px] font-medium text-gray-900 dark:text-white">{value.name}</p>
            <p className="text-[12px] text-gray-500 dark:text-gray-400">{value.supplier_code} · {value.phone || 'No phone'}</p>
          </div>
          <button type="button" onClick={() => onChange(null)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X size={16} />
          </button>
        </div>
      ) : (
        <div className="relative">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={handleFocus}
            placeholder="Search supplier by name, code, phone…"
            className={`w-full pl-9 pr-3 py-2.5 rounded-md border text-[14px] bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 ${error ? 'border-red-500' : 'border-gray-300 dark:border-gray-600 focus:border-blue-500 focus:ring-blue-500'}`}
          />
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          {isOpen && (
            <div className="absolute z-30 mt-1 w-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md shadow-lg max-h-64 overflow-auto">
              {isLoading ? (
                <div className="flex justify-center py-4"><LoadingState bare compact /></div>
              ) : results.length === 0 ? (
                <p className="px-3 py-3 text-[13px] text-gray-400 italic">No suppliers found.</p>
              ) : (
                results.map((supplier) => (
                  <button
                    type="button"
                    key={supplier.id}
                    onClick={() => handleSelect(supplier)}
                    className="w-full text-left px-3 py-2.5 hover:bg-blue-50 dark:hover:bg-gray-700 text-[13px]"
                  >
                    <p className="font-medium text-gray-900 dark:text-white">{supplier.name}</p>
                    <p className="text-gray-500 dark:text-gray-400">{supplier.supplier_code} · {supplier.phone || 'No phone'} {supplier.gstin ? `· GST: ${supplier.gstin}` : ''}</p>
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      )}
      {error && <p className="text-[12px] text-red-500 mt-1">{error}</p>}
    </div>
  );
};

export default SupplierSelector;
