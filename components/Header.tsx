import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Search, Bell, ChevronDown, Menu, LogOut, Building, Shield, Lock, Sun, Moon, Settings, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import ConnectivityBadge from './ConnectivityBadge';
import { listCustomers } from '../api/customers';
import { listSuppliers } from '../api/suppliers';
import { listProducts } from '../api/products';
import { listSalesInvoices } from '../api/salesInvoices';
import { listPurchaseInvoices } from '../api/purchaseInvoices';

interface HeaderProps {
  onMenuClick: () => void;
  onNavigate: (view: string, params?: Record<string, string>) => void;
  onLogout: () => void;
}

interface SearchResultItem {
  id: string;
  title: string;
  subtitle?: string;
}

// Maps each dropdown option to the module it searches, the screen it opens
// results on (NavigationContext params, consumed by that screen on mount),
// and how to fetch/shape its top results.
const SEARCH_CONFIG: Record<string, { view: string; fetch: (query: string) => Promise<SearchResultItem[]> }> = {
  Customer: {
    view: 'Customers',
    fetch: async (query) => {
      const res = await listCustomers({ search: query || undefined, page_size: 8 });
      return res.data.map((c) => ({ id: c.id, title: c.name, subtitle: c.customer_code }));
    },
  },
  Vendor: {
    view: 'Suppliers',
    fetch: async (query) => {
      const res = await listSuppliers({ search: query || undefined, page_size: 8 });
      return res.data.map((s) => ({ id: s.id, title: s.name, subtitle: s.supplier_code }));
    },
  },
  Product: {
    view: 'Products',
    fetch: async (query) => {
      const res = await listProducts({ search: query || undefined, page_size: 8 });
      return res.data.map((p) => ({ id: p.id, title: p.name, subtitle: p.sku }));
    },
  },
  'Sales Invoice': {
    view: 'Sales Invoices',
    fetch: async (query) => {
      const res = await listSalesInvoices({ search: query || undefined, page_size: 8 });
      return res.data.map((i) => ({ id: i.id, title: i.invoice_number, subtitle: i.customer_name }));
    },
  },
  'Purchase Invoice': {
    view: 'Purchase Invoices',
    fetch: async (query) => {
      const res = await listPurchaseInvoices({ search: query || undefined, page_size: 8 });
      return res.data.map((i) => ({ id: i.id, title: i.purchase_invoice_number, subtitle: i.supplier_name }));
    },
  },
};

const Header: React.FC<HeaderProps> = ({ onMenuClick, onNavigate, onLogout }) => {
  const [searchType, setSearchType] = useState('Customer');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [isResultsOpen, setIsResultsOpen] = useState(false);
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  const dropdownRef = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestIdRef = useRef(0);

  const { theme, toggleTheme } = useTheme();
  const { hasPermission, currentTenant } = useAuth();

  // The real logged-in tenant's name — was previously hardcoded to "Agin
  // Crop" regardless of who was actually signed in.
  const companyName = currentTenant?.business_name || 'Your Company';

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map((word) => word[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  // Requirement 5: Updated Dropdown Options
  const searchOptions = ['Customer', 'Vendor', 'Product', 'Sales Invoice', 'Purchase Invoice'];

  // Handle click outside to close dropdowns
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      // Close Search Dropdown
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
      // Close Profile Dropdown
      if (profileRef.current && !profileRef.current.contains(event.target as Node)) {
        setIsProfileOpen(false);
      }
      // Close Search Results
      if (searchRef.current && !searchRef.current.contains(event.target as Node)) {
        setIsResultsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const runSearch = useCallback((type: string, q: string) => {
    const thisRequestId = ++requestIdRef.current;
    setIsSearching(true);
    SEARCH_CONFIG[type]
      .fetch(q)
      .then((items) => {
        if (requestIdRef.current !== thisRequestId) return; // stale response
        setResults(items);
      })
      .catch(() => {
        if (requestIdRef.current !== thisRequestId) return;
        setResults([]);
      })
      .finally(() => {
        if (requestIdRef.current !== thisRequestId) return;
        setIsSearching(false);
      });
  }, []);

  // Debounced filter-as-you-type; fires immediately (no debounce) for the
  // initial open (empty query) so the top-5 list appears right away.
  useEffect(() => {
    if (!isResultsOpen) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.trim() === '') {
      runSearch(searchType, '');
      return;
    }
    debounceRef.current = setTimeout(() => runSearch(searchType, query.trim()), 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, searchType, isResultsOpen]);

  const openResultItem = (item: SearchResultItem) => {
    onNavigate(SEARCH_CONFIG[searchType].view, { id: item.id });
    setIsResultsOpen(false);
    setQuery('');
  };

  return (
    <header className="bg-[#0066ff] dark:bg-gray-900 h-16 flex items-center justify-between px-4 fixed top-0 w-full z-[60] shadow-sm transition-all duration-300 border-b border-transparent dark:border-gray-800">
      {/* Logo Area */}
      <div className="flex items-center w-auto md:w-64 pl-2">
        <h1 className="m-0 leading-none">
          <img src="/logo.png" alt="GroB6ok" className="h-4 md:h-[18px] w-auto block" />
        </h1>
      </div>

      {/* Search Bar Area */}
      <div className="hidden md:flex flex-1 max-w-2xl mx-4" ref={searchRef}>
        {/* Removed overflow-hidden here to allow dropdown to show */}
        <div className="flex w-full h-10 bg-white dark:bg-gray-800 rounded-md p-1 shadow-sm relative transition-colors">
          
          {/* Dropdown */}
          <div className="relative border-r border-gray-200 dark:border-gray-700" ref={dropdownRef}>
            <button
              className="h-full px-3 flex items-center gap-2 text-gray-800 dark:text-gray-200 text-[13px] md:text-[14px] font-medium hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors w-[180px] justify-between outline-none focus:outline-none focus:ring-0 rounded-l"
              onClick={() => {
                setIsDropdownOpen((open) => !open);
                setIsResultsOpen(false);
              }}
            >
              <span className="truncate max-w-[140px]">{searchType}</span>
              <div className="bg-[#0066ff] p-0.5 rounded-[4px] shrink-0">
                 <ChevronDown 
                    size={14} 
                    className={`text-white font-bold transition-transform duration-200 ${isDropdownOpen ? 'rotate-180' : ''}`} 
                    strokeWidth={3} 
                 />
              </div>
            </button>
            
            {isDropdownOpen && (
              <div className="absolute top-full -left-[1px] mt-1 w-[calc(100%+1px)] bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 rounded-md shadow-lg py-1 z-50 animate-fade-in">
                {searchOptions.map((opt) => (
                  <button
                    key={opt}
                    className="w-full text-left px-3 py-2 text-[13px] md:text-[14px] text-gray-700 dark:text-gray-200 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-blue-600 dark:hover:text-blue-400 transition-colors truncate"
                    onClick={() => {
                      setSearchType(opt);
                      setIsDropdownOpen(false);
                      setQuery('');
                      if (isResultsOpen) runSearch(opt, '');
                    }}
                    title={opt}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Input - Requirement 5: Dynamic Placeholder */}
          <input
            type="text"
            value={query}
            placeholder={`Search the ${searchType}`}
            className="flex-1 px-4 text-[14px] text-gray-700 dark:text-gray-200 outline-none placeholder-gray-400 dark:placeholder-gray-500 bg-transparent font-normal"
            onFocus={() => {
              setIsDropdownOpen(false);
              setIsResultsOpen(true);
              runSearch(searchType, query.trim());
            }}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && results.length > 0) {
                openResultItem(results[0]);
              } else if (e.key === 'Escape') {
                setIsResultsOpen(false);
              }
            }}
          />

          {/* Search Button */}
          <button
            type="button"
            className="px-1"
            onClick={() => {
              setIsDropdownOpen(false);
              setIsResultsOpen(true);
              runSearch(searchType, query.trim());
            }}
          >
             <div className="bg-[#0066ff] hover:bg-blue-700 h-8 w-8 rounded flex items-center justify-center transition-colors">
                 <Search size={18} className="text-white" strokeWidth={2.5} />
             </div>
          </button>

          {/* Results Dropdown — default view (empty query) shows the top
              items for the selected type; typing filters it. Capped at
              ~5 visible rows with the rest reachable by scrolling. */}
          {isResultsOpen && (
            <div className="absolute top-full left-0 mt-1 w-full bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 rounded-md shadow-lg z-50 animate-fade-in max-h-[220px] overflow-y-auto">
              {isSearching && results.length === 0 ? (
                <div className="px-4 py-3 text-[13px] text-gray-400 dark:text-gray-500 flex items-center gap-2">
                  <Loader2 size={14} className="animate-spin" /> Searching…
                </div>
              ) : results.length === 0 ? (
                <div className="px-4 py-3 text-[13px] text-gray-400 dark:text-gray-500">
                  No {searchType.toLowerCase()} results found.
                </div>
              ) : (
                results.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className="w-full text-left px-4 py-2 text-[13px] text-gray-700 dark:text-gray-200 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-blue-600 dark:hover:text-blue-400 transition-colors flex flex-col"
                    onClick={() => openResultItem(item)}
                  >
                    <span className="truncate font-medium">{item.title}</span>
                    {item.subtitle && (
                      <span className="truncate text-[11px] text-gray-400 dark:text-gray-500">{item.subtitle}</span>
                    )}
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      </div>

      {/* Right User Actions */}
      <div className="flex items-center justify-end gap-2 md:gap-4">

        <ConnectivityBadge onOpenSyncCenter={() => onNavigate('Sync Center')} />

        <span className="text-white text-[14px] font-medium hidden lg:block">{companyName}</span>
        
        {/* Profile Icon with Dropdown - Moved to last position (before mobile menu) */}
        <div className="relative" ref={profileRef}>
            <div 
              className="w-9 h-9 bg-white dark:bg-gray-800 rounded-full flex items-center justify-center text-[#0066ff] dark:text-blue-400 font-bold text-sm shadow-sm cursor-pointer hover:bg-blue-50 dark:hover:bg-gray-700 transition-colors"
              onClick={() => setIsProfileOpen(!isProfileOpen)}
            >
              {getInitials(companyName)}
            </div>

            {/* Profile Dropdown Menu */}
            {isProfileOpen && (
              <div className="absolute top-full right-0 mt-3 w-60 bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 rounded-lg shadow-xl py-1 z-50 animate-fade-in">
                  {/* Company Name (Text Only) */}
                  <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700 bg-gray-50/50 dark:bg-gray-900/50 rounded-t-lg">
                      <p className="text-xs text-gray-500 dark:text-gray-400 font-normal uppercase tracking-wider mb-0.5">Signed in as</p>
                      <p className="text-sm font-bold text-gray-900 dark:text-white truncate">{companyName}</p>
                  </div>
                  
                  {/* Menu Items */}
                  <div className="py-1">
                      {/* Business Profile & Settings: Owner Full, Manager
                          Limited (view-only inside the screen itself),
                          Salesperson No Access — gated by configuration.view,
                          same code the /tenant GET/PATCH API already checks. */}
                      {hasPermission('configuration.view') && (
                        <button
                          onClick={() => {
                              onNavigate('View Company');
                              setIsProfileOpen(false);
                          }}
                          className="w-full text-left px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-[#0066ff] dark:hover:text-blue-400 flex items-center gap-3 transition-colors"
                        >
                            <Building size={16} /> View Company
                        </button>
                      )}
                      {/* Role & Permission Configuration: Owner Full, Manager
                          No Access, Salesperson No Access — gated by
                          roles.view (Owner-only as of the RBAC Alignment
                          Phase, which removed it from Manager's defaults). */}
                      {hasPermission('roles.view') && (
                        <button className="w-full text-left px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-[#0066ff] dark:hover:text-blue-400 flex items-center gap-3 transition-colors">
                            <Shield size={16} /> User Permission
                        </button>
                      )}
                      {hasPermission('configuration.view') && (
                        <button
                          onClick={() => {
                              onNavigate('Configuration');
                              setIsProfileOpen(false);
                          }}
                          className="w-full text-left px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-[#0066ff] dark:hover:text-blue-400 flex items-center gap-3 transition-colors"
                        >
                            <Settings size={16} /> Configuration
                        </button>
                      )}
                      <button className="w-full text-left px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-[#0066ff] dark:hover:text-blue-400 flex items-center gap-3 transition-colors">
                          <Lock size={16} /> Change Password
                      </button>

                      <div className="border-t border-gray-100 dark:border-gray-700 my-1"></div>

                      <button 
                        onClick={() => {
                            toggleTheme();
                        }}
                        className="w-full text-left px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-[#0066ff] dark:hover:text-blue-400 flex items-center gap-3 transition-colors"
                      >
                         {theme === 'light' ? <Moon size={16} /> : <Sun size={16} />} 
                         {theme === 'light' ? 'Dark Mode' : 'Light Mode'}
                      </button>
                      
                      <div className="border-t border-gray-100 dark:border-gray-700 my-1"></div>
                      
                      <button
                        onClick={() => {
                            setIsProfileOpen(false);
                            onLogout();
                        }}
                        className="w-full text-left px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-3 transition-colors"
                      >
                          <LogOut size={16} /> Log Out
                      </button>
                  </div>
              </div>
            )}
        </div>
        
        {/* Mobile Hamburger Menu - Always last on mobile */}
        <button 
            onClick={onMenuClick}
            className="md:hidden text-white hover:text-blue-100 transition-colors"
        >
            <Menu size={24} />
        </button>
      </div>
    </header>
  );
};

export default Header;