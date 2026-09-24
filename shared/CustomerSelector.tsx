import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Search, Loader2, X } from 'lucide-react';
import { Customer, listCustomers } from '../api/customers';

/**
 * Reusable Sales & Billing foundation piece (PROMPT-011 S50): a
 * server-side, tenant-scoped customer search-select. No concrete Sales
 * document screen exists yet to mount this on — it's built now so the
 * next document-type prompt (Estimate, Sales Order, ...) doesn't each
 * reinvent customer search. Server-side search only; never loads the
 * full customer list into the browser.
 */
interface CustomerSelectorProps {
  value: Customer | null;
  onChange: (customer: Customer | null) => void;
  /** Exclude INACTIVE customers from results (default true — §17.3). */
  activeOnly?: boolean;
  label?: string;
  error?: string;
}

const CustomerSelector: React.FC<CustomerSelectorProps> = ({ value, onChange, activeOnly = true, label = 'Customer', error }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Customer[]>([]);
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
      const result = await listCustomers({
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

  const handleSelect = (customer: Customer) => {
    onChange(customer);
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
            <p className="text-[12px] text-gray-500 dark:text-gray-400">{value.customer_code} · {value.phone || 'No phone'}</p>
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
            placeholder="Search customer by name, code, phone…"
            className={`w-full pl-9 pr-3 py-2.5 rounded-md border text-[14px] bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 ${error ? 'border-red-500' : 'border-gray-300 dark:border-gray-600 focus:border-blue-500 focus:ring-blue-500'}`}
          />
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          {isOpen && (
            <div className="absolute z-30 mt-1 w-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md shadow-lg max-h-64 overflow-auto">
              {isLoading ? (
                <div className="flex justify-center py-4"><Loader2 size={18} className="animate-spin text-gray-400" /></div>
              ) : results.length === 0 ? (
                <p className="px-3 py-3 text-[13px] text-gray-400 italic">No customers found.</p>
              ) : (
                results.map((customer) => (
                  <button
                    type="button"
                    key={customer.id}
                    onClick={() => handleSelect(customer)}
                    className="w-full text-left px-3 py-2.5 hover:bg-blue-50 dark:hover:bg-gray-700 text-[13px]"
                  >
                    <p className="font-medium text-gray-900 dark:text-white">{customer.name}</p>
                    <p className="text-gray-500 dark:text-gray-400">{customer.customer_code} · {customer.phone || 'No phone'} {customer.gstin ? `· GST: ${customer.gstin}` : ''}</p>
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

export default CustomerSelector;
