import React, { useState, useEffect, useCallback } from 'react';
import {
  ChevronLeft, ChevronRight, Gauge, TrendingUp, TrendingDown, Boxes,
  Landmark, Wallet, BookOpen, Scale, FileText, AlertTriangle, CheckCircle2,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { ApiError, apiRequest } from '../api/client';
import * as R from '../api/reports';
import ExportButton from '../shared/ExportButton';
import LoadingState from '../shared/LoadingState';

function currentReturnPeriod(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

type MainTab = 'dashboard' | 'sales' | 'purchase' | 'inventory' | 'receivables' | 'payables' | 'payments' | 'accounting' | 'gst';

const StatCard: React.FC<{ label: string; value: string; tone?: 'default' | 'positive' | 'negative'; icon?: React.ReactNode }> = ({ label, value, tone = 'default', icon }) => (
  <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
    <div className="flex items-center justify-between">
      <p className="text-[12px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{label}</p>
      {icon}
    </div>
    <p className={`text-[20px] font-semibold mt-1 ${tone === 'positive' ? 'text-green-600' : tone === 'negative' ? 'text-red-600' : 'text-gray-900 dark:text-white'}`}>{value}</p>
  </div>
);

// Right-align date/number columns (amounts, quantities, dates), left-align
// everything else — a heuristic on the column label since DataTable's rows
// carry no per-column type metadata of their own.
const NUMERIC_DATE_COLUMN_PATTERN = /date|amount|taxable|gst|cgst|sgst|igst|total|qty|quantity|paid|outstanding|balance|debit|credit|allocated|value/i;
function columnAlign(label: string): 'text-right' | 'text-left' {
  return NUMERIC_DATE_COLUMN_PATTERN.test(label) ? 'text-right' : 'text-left';
}

const DataTable: React.FC<{ columns: string[]; rows: (string | number)[][] }> = ({ columns, rows }) => (
  <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
    <div className="overflow-x-auto">
      <table className="w-full text-left border-collapse text-[13px]">
        <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
          <tr>{columns.map((c) => <th key={c} className={`px-4 py-2.5 text-[11px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider whitespace-nowrap ${columnAlign(c)}`}>{c}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
          {rows.length === 0 ? (
            <tr><td colSpan={columns.length} className="px-4 py-8 text-center text-gray-400">No data for the selected filters.</td></tr>
          ) : rows.map((row, i) => (
            <tr key={i} className="hover:bg-blue-50 dark:hover:bg-gray-800">
              {row.map((cell, j) => <td key={j} className={`px-4 py-2.5 text-gray-700 dark:text-gray-300 whitespace-nowrap ${columnAlign(columns[j])}`}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
);

const Pager: React.FC<{ page: number; totalPages: number; totalItems: number; onChange: (p: number) => void }> = ({ page, totalPages, totalItems, onChange }) => (
  <div className="flex items-center justify-between mt-3 px-1">
    <p className="text-[12px] text-gray-500 dark:text-gray-400">{totalItems} record{totalItems === 1 ? '' : 's'}</p>
    <div className="flex items-center gap-2">
      <button onClick={() => onChange(Math.max(1, page - 1))} disabled={page === 1} className="p-1.5 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronLeft size={14} /></button>
      <span className="text-[12px] text-gray-600 dark:text-gray-400">Page {page} of {totalPages || 1}</span>
      <button onClick={() => onChange(Math.min(totalPages || 1, page + 1))} disabled={page >= totalPages} className="p-1.5 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronRight size={14} /></button>
    </div>
  </div>
);

const DateFilterBar: React.FC<{ dateFrom: string; dateTo: string; onFrom: (v: string) => void; onTo: (v: string) => void }> = ({ dateFrom, dateTo, onFrom, onTo }) => (
  <div className="flex flex-wrap items-center gap-2 mb-4">
    <label className="text-[12px] text-gray-500 dark:text-gray-400">From</label>
    <input type="date" value={dateFrom} onChange={(e) => onFrom(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] px-2.5 py-1.5" />
    <label className="text-[12px] text-gray-500 dark:text-gray-400">To</label>
    <input type="date" value={dateTo} onChange={(e) => onTo(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] px-2.5 py-1.5" />
  </div>
);

const SubTabs: React.FC<{ options: [string, string][]; active: string; onChange: (v: string) => void }> = ({ options, active, onChange }) => (
  <div className="flex gap-1.5 mb-4 overflow-x-auto">
    {options.map(([key, label]) => (
      <button key={key} onClick={() => onChange(key)} className={`px-3 py-1.5 rounded-full text-[12px] font-medium whitespace-nowrap ${active === key ? 'bg-[#0066ff] text-white' : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300'}`}>
        {label}
      </button>
    ))}
  </div>
);

const ReportsManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();

  const perms = {
    dashboard: hasPermission('reports.view_dashboard'), sales: hasPermission('reports.view_sales'), purchase: hasPermission('reports.view_purchase'),
    inventory: hasPermission('reports.view_inventory'), receivables: hasPermission('reports.view_receivables'), payables: hasPermission('reports.view_payables'),
    payments: hasPermission('reports.view_payments'), gl: hasPermission('reports.view_general_ledger'), tb: hasPermission('reports.view_trial_balance'),
    pl: hasPermission('reports.view_profit_loss'), bs: hasPermission('reports.view_balance_sheet'), gst: hasPermission('reports.view_gst'),
  };

  const availableTabs: [MainTab, string, React.ReactNode][] = [
    ...(perms.dashboard ? [['dashboard', 'Dashboard', <Gauge size={14} key="i" />] as [MainTab, string, React.ReactNode]] : []),
    ...(perms.sales ? [['sales', 'Sales', <TrendingUp size={14} key="i" />] as [MainTab, string, React.ReactNode]] : []),
    ...(perms.purchase ? [['purchase', 'Purchase', <TrendingDown size={14} key="i" />] as [MainTab, string, React.ReactNode]] : []),
    ...(perms.inventory ? [['inventory', 'Inventory', <Boxes size={14} key="i" />] as [MainTab, string, React.ReactNode]] : []),
    ...(perms.receivables ? [['receivables', 'Receivables', <Landmark size={14} key="i" />] as [MainTab, string, React.ReactNode]] : []),
    ...(perms.payables ? [['payables', 'Payables', <Landmark size={14} key="i" />] as [MainTab, string, React.ReactNode]] : []),
    ...(perms.payments ? [['payments', 'Payments', <Wallet size={14} key="i" />] as [MainTab, string, React.ReactNode]] : []),
    ...(perms.gl || perms.tb || perms.pl || perms.bs ? [['accounting', 'Accounting', <BookOpen size={14} key="i" />] as [MainTab, string, React.ReactNode]] : []),
    ...(perms.gst ? [['gst', 'GST', <FileText size={14} key="i" />] as [MainTab, string, React.ReactNode]] : []),
  ];

  const [tab, setTab] = useState<MainTab>(availableTabs[0]?.[0] || 'dashboard');

  if (availableTabs.length === 0) {
    return <div className="p-8 text-center text-gray-500 dark:text-gray-400">You do not have permission to view any reports.</div>;
  }

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 shadow-sm">
        <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight mb-3">Reports</h2>
        <div className="flex gap-2 border-b border-gray-100 dark:border-gray-800 -mb-4 overflow-x-auto">
          {availableTabs.map(([key, label, icon]) => (
            <button key={key} onClick={() => setTab(key)} className={`flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium border-b-2 whitespace-nowrap ${tab === key ? 'border-[#0066ff] text-[#0066ff]' : 'border-transparent text-gray-500 dark:text-gray-400'}`}>
              {icon} {label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'dashboard' && perms.dashboard && <DashboardTab showToast={showToast} />}
      {tab === 'sales' && perms.sales && <SalesTab showToast={showToast} />}
      {tab === 'purchase' && perms.purchase && <PurchaseTab showToast={showToast} />}
      {tab === 'inventory' && perms.inventory && <InventoryTab showToast={showToast} />}
      {tab === 'receivables' && perms.receivables && <OutstandingTab kind="receivables" showToast={showToast} />}
      {tab === 'payables' && perms.payables && <OutstandingTab kind="payables" showToast={showToast} />}
      {tab === 'payments' && perms.payments && <PaymentsTab showToast={showToast} />}
      {tab === 'accounting' && <AccountingTab perms={perms} showToast={showToast} />}
      {tab === 'gst' && perms.gst && <GstReportTab showToast={showToast} />}
    </div>
  );
};

// --- Dashboard ---------------------------------------------------------

const DashboardTab: React.FC<{ showToast: (m: string, t: 'success' | 'error') => void }> = ({ showToast }) => {
  const [period, setPeriod] = useState('THIS_MONTH');
  const [data, setData] = useState<R.DashboardData | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      setData(await R.getDashboard(period));
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load dashboard.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  useEffect(() => { load(); }, [load]);

  if (isLoading || !data) return <div className="flex items-center justify-center py-16"><LoadingState bare /></div>;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        {['TODAY', 'THIS_WEEK', 'THIS_MONTH', 'THIS_FY'].map((p) => (
          <button key={p} onClick={() => setPeriod(p)} className={`px-3 py-1.5 rounded-full text-[12px] font-medium ${period === p ? 'bg-[#0066ff] text-white' : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300'}`}>
            {p.replace(/_/g, ' ')}
          </button>
        ))}
        <span className="text-[12px] text-gray-400 ml-2">{data.period.date_from} → {data.period.date_to}</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
        <StatCard label="Net Sales" value={`₹${data.sales.net_sales}`} icon={<TrendingUp size={16} className="text-green-500" />} />
        <StatCard label="Net Purchase" value={`₹${data.purchase.net_purchase}`} icon={<TrendingDown size={16} className="text-amber-500" />} />
        <StatCard label="Receivables Outstanding" value={`₹${data.receivables.total_outstanding}`} />
        <StatCard label="Payables Outstanding" value={`₹${data.payables.total_outstanding}`} />
        <StatCard label="Output GST" value={`₹${data.gst.output_gst}`} />
        <StatCard label="Input GST" value={`₹${data.gst.input_gst}`} />
        <StatCard label="Net GST Position" value={`₹${data.gst.net_gst_position}`} />
        <StatCard label="Low Stock Items" value={String(data.inventory.low_stock_item_count)} tone={data.inventory.low_stock_item_count > 0 ? 'negative' : 'positive'} />
        <StatCard label="Customer Collections" value={`₹${data.collections.customer_collections}`} />
        <StatCard label="Supplier Payments" value={`₹${data.collections.supplier_payments}`} />
      </div>
      <p className="text-[11px] text-gray-400">GST figures reflect the current return period ({data.gst.return_period}); Inventory Value is not shown — no inventory valuation policy is approved yet (Open Decision).</p>
    </div>
  );
};

// --- Sales ---------------------------------------------------------------

const SalesTab: React.FC<{ showToast: (m: string, t: 'success' | 'error') => void }> = ({ showToast }) => {
  const [sub, setSub] = useState('summary');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [page, setPage] = useState(1);
  const [summary, setSummary] = useState<R.SalesSummary | null>(null);
  const [invoices, setInvoices] = useState<{ items: R.SalesInvoiceRegisterItem[]; total: number; pages: number }>({ items: [], total: 0, pages: 1 });
  const [customers, setCustomers] = useState<{ items: R.CustomerWiseSalesRow[]; total: number; pages: number }>({ items: [], total: 0, pages: 1 });
  const [products, setProducts] = useState<{ items: R.ProductWiseSalesRow[]; total: number; pages: number }>({ items: [], total: 0, pages: 1 });
  const [returns, setReturns] = useState<{ items: R.SalesReturnReportItem[]; total: number; pages: number }>({ items: [], total: 0, pages: 1 });
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => { setPage(1); }, [sub, dateFrom, dateTo]);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      try {
        const params = { date_from: dateFrom || undefined, date_to: dateTo || undefined, page, page_size: 10 };
        if (sub === 'summary') setSummary(await R.getSalesSummary(params));
        else if (sub === 'register') { const r = await R.listSalesInvoiceRegister(params); setInvoices({ items: r.data, total: r.pagination.total_items, pages: r.pagination.total_pages }); }
        else if (sub === 'customers') { const r = await R.getCustomerWiseSales(params); setCustomers({ items: r.data, total: r.pagination.total_items, pages: r.pagination.total_pages }); }
        else if (sub === 'products') { const r = await R.getProductWiseSales(params); setProducts({ items: r.data, total: r.pagination.total_items, pages: r.pagination.total_pages }); }
        else if (sub === 'returns') { const r = await R.listSalesReturnReport(params); setReturns({ items: r.data, total: r.pagination.total_items, pages: r.pagination.total_pages }); }
      } catch (err) {
        showToast(err instanceof ApiError ? err.message : 'Failed to load report.', 'error');
      } finally {
        setIsLoading(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, [sub, dateFrom, dateTo, page]);

  return (
    <div>
      <SubTabs options={[['summary', 'Summary'], ['register', 'Invoice Register'], ['customers', 'Customer-wise'], ['products', 'Product-wise'], ['returns', 'Returns']]} active={sub} onChange={setSub} />
      <DateFilterBar dateFrom={dateFrom} dateTo={dateTo} onFrom={setDateFrom} onTo={setDateTo} />
      {isLoading ? <div className="flex items-center justify-center py-16"><LoadingState bare /></div> : (
        <>
          {sub === 'summary' && summary && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard label="Taxable Sales" value={`₹${summary.taxable_sales}`} />
              <StatCard label="Total GST" value={`₹${summary.total_gst}`} />
              <StatCard label="Invoice Total" value={`₹${summary.invoice_total}`} />
              <StatCard label="Net Sales" value={`₹${summary.net_sales}`} />
              <StatCard label="Sales Returns" value={`₹${summary.sales_returns_total}`} />
              <StatCard label="Credit Notes" value={`₹${summary.credit_notes}`} />
              <StatCard label="Debit Notes" value={`₹${summary.debit_notes}`} />
              <StatCard label="Invoice Count" value={String(summary.invoice_count)} />
            </div>
          )}
          {sub === 'register' && (
            <>
              <DataTable columns={['Invoice #', 'Date', 'Customer', 'Taxable', 'GST', 'Total', 'Payment']} rows={invoices.items.map((i) => [i.invoice_number, i.invoice_date, i.customer_name, `₹${i.taxable_value}`, `₹${i.total_gst}`, `₹${i.invoice_total}`, i.payment_status])} />
              <Pager page={page} totalPages={invoices.pages} totalItems={invoices.total} onChange={setPage} />
            </>
          )}
          {sub === 'customers' && (
            <>
              <DataTable columns={['Customer', 'Invoices', 'Taxable', 'GST', 'Returns', 'Net Sales', 'Outstanding']} rows={customers.items.map((c) => [c.customer_name, c.invoice_count, `₹${c.taxable_sales}`, `₹${c.gst}`, `₹${c.returns}`, `₹${c.net_sales}`, `₹${c.outstanding}`])} />
              <Pager page={page} totalPages={customers.pages} totalItems={customers.total} onChange={setPage} />
            </>
          )}
          {sub === 'products' && (
            <>
              <DataTable columns={['Product', 'Qty Sold', 'Taxable', 'GST', 'Returns', 'Net Sales']} rows={products.items.map((p) => [`${p.sku} — ${p.product_name}`, p.quantity_sold, `₹${p.taxable_sales}`, `₹${p.gst}`, `₹${p.returns}`, `₹${p.net_sales}`])} />
              <Pager page={page} totalPages={products.pages} totalItems={products.total} onChange={setPage} />
            </>
          )}
          {sub === 'returns' && (
            <>
              <DataTable columns={['Return #', 'Date', 'Customer', 'Source Invoice', 'Taxable', 'GST', 'Total', 'Status']} rows={returns.items.map((r) => [r.return_number, r.return_date, r.customer_name, r.source_invoice_number, `₹${r.taxable_value}`, `₹${r.total_gst}`, `₹${r.total_return_value}`, r.status])} />
              <Pager page={page} totalPages={returns.pages} totalItems={returns.total} onChange={setPage} />
            </>
          )}
        </>
      )}
    </div>
  );
};

// --- Purchase --------------------------------------------------------------

const PurchaseTab: React.FC<{ showToast: (m: string, t: 'success' | 'error') => void }> = ({ showToast }) => {
  const [sub, setSub] = useState('summary');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [page, setPage] = useState(1);
  const [summary, setSummary] = useState<R.PurchaseSummary | null>(null);
  const [invoices, setInvoices] = useState<{ items: R.PurchaseInvoiceRegisterItem[]; total: number; pages: number }>({ items: [], total: 0, pages: 1 });
  const [suppliers, setSuppliers] = useState<{ items: R.SupplierWisePurchaseRow[]; total: number; pages: number }>({ items: [], total: 0, pages: 1 });
  const [products, setProducts] = useState<{ items: R.ProductWisePurchaseRow[]; total: number; pages: number }>({ items: [], total: 0, pages: 1 });
  const [returns, setReturns] = useState<{ items: R.PurchaseReturnReportItem[]; total: number; pages: number }>({ items: [], total: 0, pages: 1 });
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => { setPage(1); }, [sub, dateFrom, dateTo]);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      try {
        const params = { date_from: dateFrom || undefined, date_to: dateTo || undefined, page, page_size: 10 };
        if (sub === 'summary') setSummary(await R.getPurchaseSummary(params));
        else if (sub === 'register') { const r = await R.listPurchaseInvoiceRegister(params); setInvoices({ items: r.data, total: r.pagination.total_items, pages: r.pagination.total_pages }); }
        else if (sub === 'suppliers') { const r = await R.getSupplierWisePurchase(params); setSuppliers({ items: r.data, total: r.pagination.total_items, pages: r.pagination.total_pages }); }
        else if (sub === 'products') { const r = await R.getProductWisePurchase(params); setProducts({ items: r.data, total: r.pagination.total_items, pages: r.pagination.total_pages }); }
        else if (sub === 'returns') { const r = await R.listPurchaseReturnReport(params); setReturns({ items: r.data, total: r.pagination.total_items, pages: r.pagination.total_pages }); }
      } catch (err) {
        showToast(err instanceof ApiError ? err.message : 'Failed to load report.', 'error');
      } finally {
        setIsLoading(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, [sub, dateFrom, dateTo, page]);

  return (
    <div>
      <SubTabs options={[['summary', 'Summary'], ['register', 'Invoice Register'], ['suppliers', 'Supplier-wise'], ['products', 'Product-wise'], ['returns', 'Returns']]} active={sub} onChange={setSub} />
      <DateFilterBar dateFrom={dateFrom} dateTo={dateTo} onFrom={setDateFrom} onTo={setDateTo} />
      {isLoading ? <div className="flex items-center justify-center py-16"><LoadingState bare /></div> : (
        <>
          {sub === 'summary' && summary && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard label="Taxable Purchase" value={`₹${summary.taxable_purchase}`} />
              <StatCard label="Total Input GST" value={`₹${summary.total_input_gst}`} />
              <StatCard label="Net Purchase" value={`₹${summary.net_purchase}`} />
              <StatCard label="Purchase Returns" value={`₹${summary.purchase_returns}`} />
              <StatCard label="Invoice Count" value={String(summary.invoice_count)} />
            </div>
          )}
          {sub === 'register' && (
            <>
              <DataTable columns={['Invoice #', 'Supplier Inv #', 'Date', 'Supplier', 'Taxable', 'GST', 'Total', 'Payment', 'Status']} rows={invoices.items.map((i) => [i.purchase_invoice_number, i.supplier_invoice_number || '—', i.invoice_date, i.supplier_name, `₹${i.taxable_value}`, `₹${i.total_gst}`, `₹${i.invoice_total}`, i.payment_status, i.status])} />
              <Pager page={page} totalPages={invoices.pages} totalItems={invoices.total} onChange={setPage} />
            </>
          )}
          {sub === 'suppliers' && (
            <>
              <DataTable columns={['Supplier', 'Invoices', 'Taxable', 'GST', 'Returns', 'Net Purchase', 'Outstanding']} rows={suppliers.items.map((s) => [s.supplier_name, s.invoice_count, `₹${s.taxable_purchase}`, `₹${s.gst}`, `₹${s.returns}`, `₹${s.net_purchase}`, `₹${s.outstanding}`])} />
              <Pager page={page} totalPages={suppliers.pages} totalItems={suppliers.total} onChange={setPage} />
            </>
          )}
          {sub === 'products' && (
            <>
              <DataTable columns={['Product', 'Qty Purchased', 'Taxable', 'GST', 'Returns', 'Net Purchase']} rows={products.items.map((p) => [`${p.sku} — ${p.product_name}`, p.quantity_purchased, `₹${p.taxable_value}`, `₹${p.gst}`, `₹${p.returns}`, `₹${p.net_purchase}`])} />
              <Pager page={page} totalPages={products.pages} totalItems={products.total} onChange={setPage} />
            </>
          )}
          {sub === 'returns' && (
            <>
              <DataTable columns={['Return #', 'Date', 'Supplier', 'Source Invoice', 'Taxable', 'GST', 'Total', 'Status']} rows={returns.items.map((r) => [r.return_number, r.return_date, r.supplier_name, r.source_purchase_invoice_number, `₹${r.taxable_value}`, `₹${r.total_gst}`, `₹${r.total_return_value}`, r.status])} />
              <Pager page={page} totalPages={returns.pages} totalItems={returns.total} onChange={setPage} />
            </>
          )}
        </>
      )}
    </div>
  );
};

// --- Inventory -------------------------------------------------------------

const InventoryTab: React.FC<{ showToast: (m: string, t: 'success' | 'error') => void }> = ({ showToast }) => {
  const [sub, setSub] = useState('stock');
  const [page, setPage] = useState(1);
  const [stock, setStock] = useState<{ items: R.CurrentStockRow[]; total: number; pages: number }>({ items: [], total: 0, pages: 1 });
  const [movements, setMovements] = useState<{ items: R.StockMovementRow[]; total: number; pages: number }>({ items: [], total: 0, pages: 1 });
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => { setPage(1); }, [sub]);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      try {
        const params = { page, page_size: 15 };
        if (sub === 'stock') { const r = await R.getCurrentStock(params); setStock({ items: r.data, total: r.pagination.total_items, pages: r.pagination.total_pages }); }
        else { const r = await R.listStockMovements(params); setMovements({ items: r.data, total: r.pagination.total_items, pages: r.pagination.total_pages }); }
      } catch (err) {
        showToast(err instanceof ApiError ? err.message : 'Failed to load report.', 'error');
      } finally {
        setIsLoading(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, [sub, page]);

  const statusBadge = (s: string) => s === 'OUT_OF_STOCK' ? <span className="text-red-600 font-medium">{s}</span> : s === 'LOW_STOCK' ? <span className="text-amber-600 font-medium">{s}</span> : <span className="text-green-600">{s}</span>;

  return (
    <div>
      <SubTabs options={[['stock', 'Current Stock'], ['movements', 'Stock Movements']]} active={sub} onChange={setSub} />
      {isLoading ? <div className="flex items-center justify-center py-16"><LoadingState bare /></div> : (
        <>
          {sub === 'stock' && (
            <>
              <DataTable columns={['SKU', 'Product', 'UOM', 'Quantity', 'Status']} rows={stock.items.map((s) => [s.sku, s.product_name, s.uom, s.current_quantity, statusBadge(s.stock_status) as any])} />
              <Pager page={page} totalPages={stock.pages} totalItems={stock.total} onChange={setPage} />
            </>
          )}
          {sub === 'movements' && (
            <>
              <DataTable columns={['Date', 'SKU', 'Product', 'Type', 'In', 'Out', 'Source']} rows={movements.items.map((m) => [new Date(m.date).toLocaleString(), m.product_sku, m.product_name, m.movement_type, m.quantity_in !== '0' ? m.quantity_in : '—', m.quantity_out !== '0' ? m.quantity_out : '—', m.source_type.replace(/_/g, ' ')])} />
              <Pager page={page} totalPages={movements.pages} totalItems={movements.total} onChange={setPage} />
            </>
          )}
        </>
      )}
    </div>
  );
};

// --- Receivables / Payables ------------------------------------------------

const OutstandingTab: React.FC<{ kind: 'receivables' | 'payables'; showToast: (m: string, t: 'success' | 'error') => void }> = ({ kind, showToast }) => {
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<R.OutstandingItem[]>([]);
  const [summary, setSummary] = useState<R.OutstandingSummary | null>(null);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      try {
        const r = kind === 'receivables' ? await R.getReceivables({ page, page_size: 15 }) : await R.getPayables({ page, page_size: 15 });
        setItems(r.data); setSummary(r.summary); setTotalItems(r.pagination.total_items); setTotalPages(r.pagination.total_pages);
      } catch (err) {
        showToast(err instanceof ApiError ? err.message : 'Failed to load report.', 'error');
      } finally {
        setIsLoading(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, [kind, page]);

  const total = kind === 'receivables' ? summary?.total_receivables : summary?.total_payables;

  return (
    <div>
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <StatCard label={`Total ${kind === 'receivables' ? 'Receivables' : 'Payables'}`} value={`₹${total}`} />
          <StatCard label="Fully Paid" value={String(summary.fully_paid_count)} tone="positive" />
          <StatCard label="Partially Paid" value={String(summary.partially_paid_count)} />
          <StatCard label="Unpaid" value={String(summary.unpaid_count)} tone={summary.unpaid_count > 0 ? 'negative' : 'default'} />
        </div>
      )}
      {isLoading ? <div className="flex items-center justify-center py-16"><LoadingState bare /></div> : (
        <>
          <DataTable
            columns={[kind === 'receivables' ? 'Customer' : 'Supplier', 'Invoice #', 'Date', 'Due Date', 'Amount', 'Paid', 'Outstanding', 'Status']}
            rows={items.map((i) => [i.customer_name || i.supplier_name || '—', i.invoice_number, i.invoice_date, i.due_date || '—', `₹${i.invoice_amount}`, `₹${i.paid_amount}`, `₹${i.outstanding}`, i.payment_status])}
          />
          <Pager page={page} totalPages={totalPages} totalItems={totalItems} onChange={setPage} />
        </>
      )}
    </div>
  );
};

// --- Payments ----------------------------------------------------------------

const PaymentsTab: React.FC<{ showToast: (m: string, t: 'success' | 'error') => void }> = ({ showToast }) => {
  const [sub, setSub] = useState('register');
  const [page, setPage] = useState(1);
  const [payments, setPayments] = useState<{ items: R.PaymentRegisterItem[]; total: number; pages: number }>({ items: [], total: 0, pages: 1 });
  const [methodSummary, setMethodSummary] = useState<R.PaymentMethodSummaryRow[]>([]);
  const [cheques, setCheques] = useState<{ items: R.ChequeReportRow[]; total: number; pages: number }>({ items: [], total: 0, pages: 1 });
  const [dailyCollection, setDailyCollection] = useState<R.DailyCollectionDay[]>([]);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => { setPage(1); }, [sub]);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      try {
        if (sub === 'register') { const r = await R.listPayments({ page, page_size: 15 }); setPayments({ items: r.data, total: r.pagination.total_items, pages: r.pagination.total_pages }); }
        else if (sub === 'methods') setMethodSummary(await R.getPaymentMethodSummary());
        else if (sub === 'daily-collection') setDailyCollection(await R.getDailyCollectionReport({ date_from: dateFrom || undefined, date_to: dateTo || undefined }));
        else { const r = await R.listCheques({ page, page_size: 15 }); setCheques({ items: r.data, total: r.pagination.total_items, pages: r.pagination.total_pages }); }
      } catch (err) {
        showToast(err instanceof ApiError ? err.message : 'Failed to load report.', 'error');
      } finally {
        setIsLoading(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, [sub, page, dateFrom, dateTo]);

  const dailyCollectionTotal = dailyCollection.reduce((sum, d) => sum + Number(d.total_amount), 0);
  const dailyCollectionEntryCount = dailyCollection.reduce((sum, d) => sum + d.entry_count, 0);

  return (
    <div>
      <SubTabs options={[['register', 'Payment Register'], ['methods', 'Method Summary'], ['daily-collection', 'Daily Collection'], ['cheques', 'Cheque Report']]} active={sub} onChange={setSub} />

      {sub === 'daily-collection' && (
        <div className="flex flex-wrap items-end gap-3 mb-4">
          <div>
            <label className="block text-[12px] font-medium text-gray-500 dark:text-gray-400 mb-1">From</label>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] px-3 py-1.5" />
          </div>
          <div>
            <label className="block text-[12px] font-medium text-gray-500 dark:text-gray-400 mb-1">To</label>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] px-3 py-1.5" />
          </div>
          <ExportButton
            resource="daily_collection"
            exportPermission="reports.export"
            dateFrom={dateFrom || undefined}
            dateTo={dateTo || undefined}
            page={1}
            pageSize={10000}
            totalItems={dailyCollectionEntryCount}
          />
        </div>
      )}

      {isLoading ? <div className="flex items-center justify-center py-16"><LoadingState bare /></div> : (
        <>
          {sub === 'register' && (
            <>
              <DataTable columns={['Payment #', 'Date', 'Party', 'Type', 'Method', 'Amount', 'Status']} rows={payments.items.map((p) => [p.payment_number, p.payment_date, p.party_name || '—', p.party_type, p.payment_method, `₹${p.amount}`, p.status])} />
              <Pager page={page} totalPages={payments.pages} totalItems={payments.total} onChange={setPage} />
            </>
          )}
          {sub === 'methods' && <DataTable columns={['Method', 'Transactions', 'Amount']} rows={methodSummary.map((m) => [m.payment_method, m.transaction_count, `₹${m.amount}`])} />}
          {sub === 'daily-collection' && (
            dailyCollection.length === 0 ? (
              <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 px-4 py-8 text-center text-gray-400">No collections for the selected date range.</div>
            ) : (
              <div className="space-y-4">
                <div className="bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800 rounded-lg px-4 py-2.5 text-[13px] text-blue-800 dark:text-blue-300 font-medium">
                  Total: ₹{dailyCollectionTotal.toFixed(2)} across {dailyCollectionEntryCount} collection{dailyCollectionEntryCount === 1 ? '' : 's'}
                </div>
                {dailyCollection.map((day) => (
                  <div key={day.date}>
                    <div className="flex items-center justify-between mb-1.5 px-1">
                      <h4 className="text-[13px] font-semibold text-gray-700 dark:text-gray-200">{day.date}</h4>
                      <span className="text-[13px] font-medium text-gray-600 dark:text-gray-300">₹{day.total_amount} · {day.entry_count} entr{day.entry_count === 1 ? 'y' : 'ies'}</span>
                    </div>
                    <DataTable
                      columns={['Receipt #', 'Customer', 'Method', 'Collected By', 'Amount']}
                      rows={day.entries.map((e) => [e.payment_number, e.customer_name || '—', e.payment_method, e.collected_by_name || 'Unknown', `₹${e.amount}`])}
                    />
                  </div>
                ))}
              </div>
            )
          )}
          {sub === 'cheques' && (
            <>
              <DataTable columns={['Cheque #', 'Payment #', 'Party', 'Amount', 'Cheque Date', 'Bank', 'Status']} rows={cheques.items.map((c) => [c.cheque_number || '—', c.payment_number, c.party_name || '—', `₹${c.amount}`, c.cheque_date || '—', c.bank || '—', c.cheque_status || '—'])} />
              <Pager page={page} totalPages={cheques.pages} totalItems={cheques.total} onChange={setPage} />
            </>
          )}
        </>
      )}
    </div>
  );
};

// --- Accounting (GL / TB / P&L / BS) ----------------------------------------

const AccountingTab: React.FC<{ perms: Record<string, boolean>; showToast: (m: string, t: 'success' | 'error') => void }> = ({ perms, showToast }) => {
  const [sub, setSub] = useState(perms.gl ? 'gl' : perms.tb ? 'tb' : perms.pl ? 'pl' : 'bs');
  const [accounts, setAccounts] = useState<{ id: string; code: string; name: string }[]>([]);
  const [accountId, setAccountId] = useState('');
  const [gl, setGl] = useState<R.GeneralLedgerResponse | null>(null);
  const [tb, setTb] = useState<R.TrialBalanceResponse | null>(null);
  const [pl, setPl] = useState<R.ProfitLossResponse | null>(null);
  const [bs, setBs] = useState<R.BalanceSheetResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const list = await apiRequest<{ id: string; code: string; name: string }[]>('/accounting/accounts');
        setAccounts(list);
        if (list.length > 0) setAccountId(list[0].id);
      } catch { /* Chart of Accounts not accessible — GL account picker stays empty */ }
    })();
  }, []);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      try {
        if (sub === 'gl' && accountId) setGl(await R.getGeneralLedger(accountId));
        else if (sub === 'tb') setTb(await R.getTrialBalance());
        else if (sub === 'pl') setPl(await R.getProfitAndLoss());
        else if (sub === 'bs') setBs(await R.getBalanceSheet());
      } catch (err) {
        showToast(err instanceof ApiError ? err.message : 'Failed to load report.', 'error');
      } finally {
        setIsLoading(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, [sub, accountId]);

  const subOptions: [string, string][] = [
    ...(perms.gl ? [['gl', 'General Ledger'] as [string, string]] : []),
    ...(perms.tb ? [['tb', 'Trial Balance'] as [string, string]] : []),
    ...(perms.pl ? [['pl', 'Profit & Loss'] as [string, string]] : []),
    ...(perms.bs ? [['bs', 'Balance Sheet'] as [string, string]] : []),
  ];

  return (
    <div>
      <SubTabs options={subOptions} active={sub} onChange={setSub} />
      {isLoading ? <div className="flex items-center justify-center py-16"><LoadingState bare /></div> : (
        <>
          {sub === 'gl' && (
            <div className="space-y-3">
              <select value={accountId} onChange={(e) => setAccountId(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] px-3 py-2">
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
              </select>
              {gl && (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <StatCard label="Opening Balance" value={`₹${gl.opening_balance}`} />
                    <StatCard label="Closing Balance" value={`₹${gl.closing_balance}`} />
                  </div>
                  <DataTable columns={['Date', 'Journal #', 'Source', 'Description', 'Debit', 'Credit', 'Balance']} rows={gl.entries.map((e) => [e.date, e.journal_number, e.source_type.replace(/_/g, ' '), e.description || '—', e.debit !== '0.00' ? `₹${e.debit}` : '—', e.credit !== '0.00' ? `₹${e.credit}` : '—', `₹${e.running_balance}`])} />
                </>
              )}
            </div>
          )}
          {sub === 'tb' && tb && (
            <div className="space-y-3">
              <div className={`flex items-center gap-2 px-4 py-2.5 rounded-lg border text-[13px] ${tb.is_balanced ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800 text-green-700 dark:text-green-400' : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 text-red-700 dark:text-red-400'}`}>
                {tb.is_balanced ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                {tb.is_balanced ? 'Balanced' : 'TRIAL_BALANCE_OUT_OF_BALANCE — total debit does not equal total credit'}
              </div>
              <DataTable columns={['Account', 'Type', 'Debit', 'Credit']} rows={tb.accounts.map((a) => [`${a.account_code} — ${a.account_name}`, a.account_type, a.debit !== '0.00' ? `₹${a.debit}` : '—', a.credit !== '0.00' ? `₹${a.credit}` : '—'])} />
              <div className="flex justify-end gap-6 px-4 text-[13px] font-semibold text-gray-800 dark:text-gray-100"><span>Total Debit: ₹{tb.total_debit}</span><span>Total Credit: ₹{tb.total_credit}</span></div>
            </div>
          )}
          {sub === 'pl' && pl && (
            <div className="space-y-4">
              <div>
                <p className="text-[13px] font-semibold text-gray-800 dark:text-gray-100 mb-1">Revenue</p>
                <DataTable columns={['Account', 'Amount']} rows={pl.revenue_accounts.map((a) => [a.account_name, `₹${a.net_balance}`])} />
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <StatCard label="Total Revenue" value={`₹${pl.total_revenue}`} />
                <StatCard label="COGS" value={`₹${pl.total_cogs}`} />
                <StatCard label="Gross Profit" value={`₹${pl.gross_profit}`} />
                <StatCard label="Net Profit" value={`₹${pl.net_profit}`} tone={Number(pl.net_profit) >= 0 ? 'positive' : 'negative'} />
              </div>
              <div>
                <p className="text-[13px] font-semibold text-gray-800 dark:text-gray-100 mb-1">Operating Expenses</p>
                <DataTable columns={['Account', 'Amount']} rows={pl.expense_accounts.map((a) => [a.account_name, `₹${a.net_balance}`])} />
              </div>
              {pl.cogs_accounts.length === 0 && <p className="text-[11px] text-gray-400">No COGS account exists yet — inventory valuation policy is not approved (Open Decision, see PROMPT-027-NOTES.md).</p>}
            </div>
          )}
          {sub === 'bs' && bs && (
            <div className="space-y-4">
              <div className={`flex items-center gap-2 px-4 py-2.5 rounded-lg border text-[13px] ${bs.is_balanced ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800 text-green-700 dark:text-green-400' : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 text-red-700 dark:text-red-400'}`}>
                {bs.is_balanced ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                {bs.is_balanced ? 'Assets = Liabilities + Equity' : 'Accounting integrity error — the Balance Sheet does not balance'}
              </div>
              <div>
                <p className="text-[13px] font-semibold text-gray-800 dark:text-gray-100 mb-1">Assets — ₹{bs.total_assets}</p>
                <DataTable columns={['Account', 'Amount']} rows={bs.asset_accounts.map((a) => [a.account_name, `₹${a.net_balance}`])} />
              </div>
              <div>
                <p className="text-[13px] font-semibold text-gray-800 dark:text-gray-100 mb-1">Liabilities — ₹{bs.total_liabilities}</p>
                <DataTable columns={['Account', 'Amount']} rows={bs.liability_accounts.map((a) => [a.account_name, `₹${a.net_balance}`])} />
              </div>
              <div>
                <p className="text-[13px] font-semibold text-gray-800 dark:text-gray-100 mb-1">Equity — ₹{bs.total_equity}</p>
                <DataTable columns={['Account', 'Amount']} rows={[...bs.equity_accounts.map((a) => [a.account_name, `₹${a.net_balance}`]), ['Current Period Earnings (unclosed)', `₹${bs.current_period_earnings}`]]} />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

// --- GST -----------------------------------------------------------------

const GstReportTab: React.FC<{ showToast: (m: string, t: 'success' | 'error') => void }> = ({ showToast }) => {
  const [returnPeriod, setReturnPeriod] = useState(currentReturnPeriod());
  const [summary, setSummary] = useState<any>(null);
  const [hsn, setHsn] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      try {
        setSummary(await R.getGstReportSummary(returnPeriod));
        setHsn(await R.getGstHsnSummary(returnPeriod));
      } catch (err) {
        showToast(err instanceof ApiError ? err.message : 'Failed to load GST report.', 'error');
      } finally {
        setIsLoading(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, [returnPeriod]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <label className="text-[13px] text-gray-500 dark:text-gray-400">Return Period</label>
        <input type="month" value={returnPeriod} onChange={(e) => setReturnPeriod(e.target.value)} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] px-3 py-1.5" />
      </div>
      {isLoading || !summary ? <div className="flex items-center justify-center py-16"><LoadingState bare /></div> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard label="Output GST" value={`₹${summary.output_gst}`} />
            <StatCard label="Input GST" value={`₹${summary.input_gst}`} />
            <StatCard label="Net GST Position" value={`₹${summary.net_gst_position}`} />
            <StatCard label="B2B Sales" value={`₹${summary.b2b_sales}`} />
            <StatCard label="B2C Sales" value={`₹${summary.b2c_sales}`} />
            <StatCard label="Credit Notes" value={`₹${summary.credit_notes}`} />
            <StatCard label="Debit Notes" value={`₹${summary.debit_notes}`} />
          </div>
          <div>
            <p className="text-[13px] font-semibold text-gray-800 dark:text-gray-100 mb-1">HSN/SAC Summary</p>
            <DataTable columns={['HSN', 'Taxable', 'CGST', 'SGST', 'IGST']} rows={hsn.map((h) => [h.hsn_code, `₹${h.taxable_value}`, `₹${h.cgst}`, `₹${h.sgst}`, `₹${h.igst}`])} />
          </div>
          <p className="text-[11px] text-gray-400">GST figures are consumed directly from the GST Rule Engine's own reporting dataset — never recalculated here.</p>
        </>
      )}
    </div>
  );
};

export default ReportsManagement;
