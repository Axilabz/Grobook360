import React, { useEffect, useState } from 'react';
import { useToast } from '../context/ToastContext';
import { ApiError } from '../api/client';
import { getDashboard, getCurrentStock, DashboardData, CurrentStockRow } from '../api/reports';
import { listSalesInvoices, SalesInvoiceListItem } from '../api/salesInvoices';
import LoadingState from '../shared/LoadingState';
import EmptyState from '../shared/EmptyState';

function formatInr(value: string | number): string {
  const n = typeof value === 'string' ? Number(value) : value;
  if (Number.isNaN(n)) return '₹ 0.00';
  return '₹ ' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const Home: React.FC = () => {
  const { showToast } = useToast();
  const [loading, setLoading] = useState(true);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [recentInvoices, setRecentInvoices] = useState<SalesInvoiceListItem[]>([]);
  const [lowStock, setLowStock] = useState<CurrentStockRow[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [dashboardData, invoicesResult, stockResult] = await Promise.all([
          getDashboard('THIS_MONTH'),
          listSalesInvoices({ page: 1, page_size: 6 }),
          getCurrentStock({ page: 1, page_size: 6, status: 'LOW_STOCK' }),
        ]);
        if (cancelled) return;
        setDashboard(dashboardData);
        setRecentInvoices(invoicesResult.data);
        setLowStock(stockResult.data);
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : 'Failed to load dashboard data.';
        showToast(message, 'error');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [showToast]);

  const cards = dashboard
    ? [
        { title: 'Net Sales (This Month)', value: formatInr(dashboard.sales.net_sales), color: 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-400' },
        { title: 'Sales Invoices (This Month)', value: String(dashboard.sales.invoice_count), color: 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800 text-green-700 dark:text-green-400' },
        { title: 'Receivables Outstanding', value: formatInr(dashboard.receivables.total_outstanding), color: 'bg-purple-50 dark:bg-purple-900/20 border-purple-200 dark:border-purple-800 text-purple-700 dark:text-purple-400' },
        { title: 'Payables Outstanding', value: formatInr(dashboard.payables.total_outstanding), color: 'bg-orange-50 dark:bg-orange-900/20 border-orange-200 dark:border-orange-800 text-orange-700 dark:text-orange-400' },
      ]
    : [];

  return (
    <div className="p-8 animate-fade-in">
      {/* Sticky Header Section */}
      <div className="sticky top-16 z-10 bg-white dark:bg-gray-950 -mx-8 px-8 py-4 -mt-8 mb-6 border-b border-gray-100 dark:border-gray-800 transition-all">
        <h2 className="text-[22px] md:text-[26px] lg:text-[28px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight leading-tight">Dashboard Overview</h2>
      </div>

      {loading ? (
        <LoadingState label="Loading dashboard…" />
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            {cards.map((stat, index) => (
              <div key={index} className={`p-6 rounded-xl border ${stat.color} shadow-sm transition-colors`}>
                <p className="text-[14px] md:text-[15px] font-medium opacity-80 mb-2">{stat.title}</p>
                <p className="text-2xl font-bold">{stat.value}</p>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 pb-8">
            <div className="bg-white dark:bg-gray-900 p-6 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm min-h-[300px] transition-colors">
              <h3 className="text-[16px] lg:text-[18px] font-semibold text-gray-800 dark:text-gray-200 mb-4">Recent Sales Invoices</h3>
              {recentInvoices.length === 0 ? (
                <EmptyState title="No sales invoices yet" description="Invoices you create will show up here." />
              ) : (
                <div className="space-y-4">
                  {recentInvoices.map((inv) => (
                    <div key={inv.id} className="flex items-center justify-between p-3 hover:bg-gray-50 dark:hover:bg-gray-800 rounded-lg transition-colors border-b border-gray-100 dark:border-gray-700 last:border-0">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-gray-200 dark:bg-gray-600 flex items-center justify-center text-[13px] font-semibold text-gray-600 dark:text-gray-300">
                          {inv.customer_name.charAt(0).toUpperCase()}
                        </div>
                        <div>
                          <p className="text-[14px] md:text-[15px] font-medium text-gray-900 dark:text-gray-100">{inv.customer_name}</p>
                          <p className="text-[12px] md:text-[14px] text-gray-500 dark:text-gray-400">
                            {inv.invoice_number} &middot; {inv.status}
                          </p>
                        </div>
                      </div>
                      <span className="text-[14px] md:text-[15px] font-semibold text-gray-700 dark:text-gray-300">{formatInr(inv.grand_total)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="bg-white dark:bg-gray-900 p-6 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm min-h-[300px] transition-colors">
              <h3 className="text-[16px] lg:text-[18px] font-semibold text-gray-800 dark:text-gray-200 mb-4">Stock Alerts</h3>
              {lowStock.length === 0 ? (
                <EmptyState title="No low-stock items" description="Products below their reorder level will show up here." />
              ) : (
                <div className="space-y-3">
                  {lowStock.map((row) => (
                    <div key={row.product_id} className="flex items-center justify-between p-3 bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/30 rounded-lg text-red-800 dark:text-red-400 transition-colors">
                      <span className="text-[14px] md:text-[15px] font-medium">{row.product_name}</span>
                      <span className="text-[12px] md:text-[14px] bg-white dark:bg-gray-800 px-2 py-1 rounded border border-red-200 dark:border-red-800 font-bold">
                        {row.current_quantity} {row.uom} left
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default Home;
