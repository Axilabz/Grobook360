// Analysis page — an interactive BI workspace distinct from the Dashboard
// (status at a glance) and operational Reports (predefined tables). Every
// number here is computed by AnalysisService, a thin composition layer
// over the EXISTING, authoritative report services (see backend module
// docstring) — nothing is recalculated differently here. Gated by the
// same `reports.view_*` permissions Reports/Dashboard already use (no new
// RBAC codes for Phase 1 — see the approved plan's Architecture Decision #1).
import React, { useState, useEffect } from 'react';
import { BarChart3, RefreshCw, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Select from './Select';
import OverviewAnalysisTab from './analysis/OverviewAnalysisTab';
import SalesAnalysisTab from './analysis/SalesAnalysisTab';
import ProductAnalysisTab from './analysis/ProductAnalysisTab';
import CustomerAnalysisTab from './analysis/CustomerAnalysisTab';
import PurchaseAnalysisTab from './analysis/PurchaseAnalysisTab';
import InventoryAnalysisTab from './analysis/InventoryAnalysisTab';
import type { AnalysisQueryParams } from '../api/analysis';

export const PERIOD_OPTIONS: { value: string; label: string }[] = [
  { value: 'TODAY', label: 'Today' },
  { value: 'YESTERDAY', label: 'Yesterday' },
  { value: 'THIS_WEEK', label: 'This Week' },
  { value: 'LAST_WEEK', label: 'Last Week' },
  { value: 'THIS_MONTH', label: 'This Month' },
  { value: 'LAST_MONTH', label: 'Last Month' },
  { value: 'THIS_QUARTER', label: 'This Quarter' },
  { value: 'THIS_FY', label: 'This Financial Year' },
  { value: 'PREVIOUS_FY', label: 'Previous Financial Year' },
  { value: 'CUSTOM', label: 'Custom Range' },
];

const COMPARE_OPTIONS: { value: string; label: string }[] = [
  { value: 'NONE', label: 'No Comparison' },
  { value: 'PREVIOUS_PERIOD', label: 'Previous Equivalent Period' },
  { value: 'PREVIOUS_MONTH', label: 'Previous Month' },
  { value: 'PREVIOUS_QUARTER', label: 'Previous Quarter' },
  { value: 'PREVIOUS_FY', label: 'Previous Financial Year' },
  { value: 'CUSTOM', label: 'Custom Period' },
];

type TabKey = 'Overview' | 'Sales' | 'Products' | 'Customers' | 'Purchases' | 'Inventory';

// Compare To follows whichever Period is selected, matching the natural
// "vs" a business owner would ask for (This Week -> Last Week, This Month
// -> Last Month, This FY -> Previous FY, etc.) — re-applied every time the
// Period changes, but never while the user is just adjusting Compare To
// itself, so a manual override sticks until the Period changes again.
function defaultCompareForPeriod(period: string, customFrom: string, customTo: string): string {
  switch (period) {
    case 'TODAY':
    case 'YESTERDAY':
    case 'THIS_WEEK':
    case 'LAST_WEEK':
      return 'PREVIOUS_PERIOD'; // immediately preceding period of the same length (e.g. this week -> last week)
    case 'THIS_MONTH':
    case 'LAST_MONTH':
      return 'PREVIOUS_MONTH'; // same dates, one calendar month back
    case 'THIS_QUARTER':
      return 'PREVIOUS_QUARTER';
    case 'THIS_FY':
    case 'PREVIOUS_FY':
      return 'PREVIOUS_FY';
    case 'CUSTOM': {
      if (!customFrom || !customTo) return 'PREVIOUS_PERIOD';
      const spanDays = (new Date(customTo).getTime() - new Date(customFrom).getTime()) / 86400000 + 1;
      // A short/"roughly one month or less" custom range reads naturally as
      // "same dates, last month" (e.g. 10-20 Oct vs 10-20 Sep); a longer
      // range (a quarter+) reads better as "the same span, shifted back"
      // (e.g. a 3-month range vs the 3 months before it).
      return spanDays <= 45 ? 'PREVIOUS_MONTH' : 'PREVIOUS_PERIOD';
    }
    default:
      return 'NONE';
  }
}

const AnalysisManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const canViewDashboard = hasPermission('reports.view_dashboard');
  const canViewSales = hasPermission('reports.view_sales');
  const canViewPurchase = hasPermission('reports.view_purchase');
  const canViewInventory = hasPermission('reports.view_inventory');

  const allTabs: { key: TabKey; label: string; visible: boolean }[] = [
    { key: 'Overview', label: 'Overview', visible: canViewDashboard },
    { key: 'Sales', label: 'Sales', visible: canViewSales },
    { key: 'Products', label: 'Products', visible: canViewSales },
    { key: 'Customers', label: 'Customers', visible: canViewSales },
    { key: 'Purchases', label: 'Purchases', visible: canViewPurchase },
    { key: 'Inventory', label: 'Inventory', visible: canViewInventory },
  ];
  const tabs = allTabs.filter((t) => t.visible);

  const [activeTab, setActiveTab] = useState<TabKey>(tabs[0]?.key ?? 'Overview');
  const [period, setPeriod] = useState('THIS_MONTH');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [compare, setCompare] = useState(() => defaultCompareForPeriod('THIS_MONTH', '', ''));
  const [compareFrom, setCompareFrom] = useState('');
  const [compareTo, setCompareTo] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  const [lastUpdated, setLastUpdated] = useState(new Date());

  // Re-apply the natural Compare To default every time the Period changes
  // (never while the user is just adjusting Compare To itself).
  useEffect(() => {
    setCompare(defaultCompareForPeriod(period, customFrom, customTo));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period, customFrom, customTo]);

  const params: AnalysisQueryParams = {
    period, dateFrom: period === 'CUSTOM' ? customFrom : undefined, dateTo: period === 'CUSTOM' ? customTo : undefined,
    compare, compareFrom: compare === 'CUSTOM' ? compareFrom : undefined, compareTo: compare === 'CUSTOM' ? compareTo : undefined,
  };

  const handleRefresh = () => {
    setRefreshKey((k) => k + 1);
    setLastUpdated(new Date());
  };

  const handleClearFilters = () => {
    setPeriod('THIS_MONTH');
    setCustomFrom('');
    setCustomTo('');
    setCompare('NONE');
    setCompareFrom('');
    setCompareTo('');
    handleRefresh();
  };

  const activeFilterChips: { label: string; onRemove: () => void }[] = [];
  if (period !== 'THIS_MONTH') {
    activeFilterChips.push({ label: `Period: ${PERIOD_OPTIONS.find((p) => p.value === period)?.label ?? period}`, onRemove: () => setPeriod('THIS_MONTH') });
  }
  if (compare !== 'NONE') {
    activeFilterChips.push({ label: `Compare: ${COMPARE_OPTIONS.find((c) => c.value === compare)?.label ?? compare}`, onRemove: () => setCompare('NONE') });
  }

  if (tabs.length === 0) {
    return (
      <div className="max-w-7xl mx-auto p-8 text-center text-gray-500 dark:text-gray-400">
        You don't have permission to view any Analysis section.
      </div>
    );
  }

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      {/* Header */}
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 shadow-sm">
        <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4">
          <div className="flex items-center gap-3">
            <span className="bg-blue-100 dark:bg-blue-900/30 p-2 rounded-lg text-blue-600 dark:text-blue-400"><BarChart3 size={22} /></span>
            <div>
              <h2 className="text-[20px] md:text-[24px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight leading-tight">Analysis</h2>
              <p className="text-[12px] md:text-[13px] text-gray-500 dark:text-gray-400">Explore business performance and identify opportunities.</p>
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-3 w-full lg:w-auto">
            <div className="w-40">
              <Select label="Period" allowAddNew={false} options={PERIOD_OPTIONS.map((p) => p.label)} value={PERIOD_OPTIONS.find((p) => p.value === period)?.label ?? ''} onChange={(label) => setPeriod(PERIOD_OPTIONS.find((p) => p.label === label)?.value ?? 'THIS_MONTH')} />
            </div>
            {period === 'CUSTOM' && (
              <>
                <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] px-3 py-2.5 h-[42px]" />
                <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] px-3 py-2.5 h-[42px]" />
              </>
            )}

            {activeTab !== 'Inventory' && (
              <div className="w-48">
                <Select label="Compare To" allowAddNew={false} options={COMPARE_OPTIONS.map((c) => c.label)} value={COMPARE_OPTIONS.find((c) => c.value === compare)?.label ?? ''} onChange={(label) => setCompare(COMPARE_OPTIONS.find((c) => c.label === label)?.value ?? 'NONE')} />
              </div>
            )}
            {activeTab !== 'Inventory' && compare === 'CUSTOM' && (
              <>
                <input type="date" value={compareFrom} onChange={(e) => setCompareFrom(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] px-3 py-2.5 h-[42px]" />
                <input type="date" value={compareTo} onChange={(e) => setCompareTo(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] px-3 py-2.5 h-[42px]" />
              </>
            )}

            <button onClick={handleClearFilters} className="h-[42px] px-3 text-[13px] font-medium text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
              Clear All
            </button>
            <button onClick={handleRefresh} className="h-[42px] px-4 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] font-medium flex items-center gap-2 hover:bg-gray-50 dark:hover:bg-gray-700">
              <RefreshCw size={14} /> Refresh
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 mt-3">
          <div className="flex gap-2 overflow-x-auto">
            {tabs.map((t) => (
              <button
                key={t.key}
                onClick={() => setActiveTab(t.key)}
                className={`px-4 py-2 rounded-lg text-[13px] font-medium whitespace-nowrap transition-colors ${activeTab === t.key ? 'bg-[#0066ff] text-white' : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'}`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <span className="text-[11px] text-gray-400 dark:text-gray-500 whitespace-nowrap">Last updated {lastUpdated.toLocaleTimeString('en-IN')}</span>
        </div>

        {activeFilterChips.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-3">
            {activeFilterChips.map((chip) => (
              <span key={chip.label} className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 text-[12px] font-medium">
                {chip.label}
                <button onClick={chip.onRemove}><X size={12} /></button>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Active tab content */}
      {activeTab === 'Overview' && <OverviewAnalysisTab params={params} refreshKey={refreshKey} />}
      {activeTab === 'Sales' && <SalesAnalysisTab params={params} refreshKey={refreshKey} />}
      {activeTab === 'Products' && <ProductAnalysisTab params={params} refreshKey={refreshKey} />}
      {activeTab === 'Customers' && <CustomerAnalysisTab params={params} refreshKey={refreshKey} />}
      {activeTab === 'Purchases' && <PurchaseAnalysisTab params={params} refreshKey={refreshKey} />}
      {activeTab === 'Inventory' && <InventoryAnalysisTab params={params} refreshKey={refreshKey} />}
    </div>
  );
};

export default AnalysisManagement;
