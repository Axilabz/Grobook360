// Business Overview Dashboard.
//
// Deliberately a SUMMARY -> EXCEPTION -> ACTION -> DRILL-DOWN surface, not
// a report: every number here is read verbatim from the backend's own
// authoritative report/dashboard services (app/services/reports/
// dashboard_service.py) — nothing is recalculated in this file. Widget
// visibility is role-aware via the existing `reports.view_*` permission
// set (PROMPT-027) so a Salesperson (who only has view_dashboard/
// view_sales/view_inventory) doesn't see Receivables/Payables/GST
// sections at all, even though the backend response — unchanged from
// before this pass — still returns those fields alongside the ones they
// ARE authorized for. That's a pre-existing gap in how narrowly
// /reports/dashboard's own permission gate was scoped (PROMPT-027), not
// something introduced here; noted rather than silently left undocumented.
import React, { useEffect, useState, useCallback } from 'react';
import {
  TrendingUp, Users, Truck, Package, Wallet, Banknote,
  Plus, FileText, ShoppingCart, ClipboardList, RefreshCw, ChevronRight, Wifi, WifiOff,
} from 'lucide-react';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import { useNavigation } from '../context/NavigationContext';
import { ApiError } from '../api/client';
import {
  getDashboard, getDashboardAlerts, getRecentTransactions,
  DashboardData, DashboardAlert, RecentTransaction,
} from '../api/reports';
import LoadingState from '../shared/LoadingState';
import EmptyState from '../shared/EmptyState';
import { isBrowserOnline, subscribeToConnectivity } from '../pwa/connectivity';
import { dbGetAllByTenant, STORE_SYNC_QUEUE } from '../pwa/offlineDb';

function formatInr(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const n = typeof value === 'string' ? Number(value) : value;
  if (Number.isNaN(n)) return '₹0.00';
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const PERIODS: { value: string; label: string }[] = [
  { value: 'TODAY', label: 'Today' },
  { value: 'THIS_WEEK', label: 'This Week' },
  { value: 'THIS_MONTH', label: 'This Month' },
  { value: 'THIS_FY', label: 'This Financial Year' },
];

const SEVERITY_STYLE: Record<string, string> = {
  CRITICAL: 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-900/40 text-red-800 dark:text-red-400',
  WARNING: 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-900/40 text-amber-800 dark:text-amber-400',
  INFO: 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-900/40 text-blue-800 dark:text-blue-400',
  SUCCESS: 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-900/40 text-green-800 dark:text-green-400',
};

const TRANSACTION_LABEL: Record<string, string> = {
  SALES_INVOICE: 'Sales Invoice', PURCHASE_INVOICE: 'Purchase Invoice',
  CUSTOMER_RECEIPT: 'Customer Receipt', SUPPLIER_PAYMENT: 'Supplier Payment',
};

interface KpiCardProps {
  title: string; value: string; icon: React.ReactNode; color: string; onClick?: () => void;
}
const KpiCard: React.FC<KpiCardProps> = ({ title, value, icon, color, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={!onClick}
    className={`text-left p-5 rounded-xl border ${color} shadow-sm transition-colors ${onClick ? 'hover:shadow-md cursor-pointer' : 'cursor-default'}`}
  >
    <div className="flex items-center justify-between mb-2">
      <p className="text-[13px] font-medium opacity-80">{title}</p>
      {icon}
    </div>
    <p className="text-2xl font-bold">{value}</p>
  </button>
);

const SectionCard: React.FC<{ title: string; onViewAll?: () => void; children: React.ReactNode }> = ({ title, onViewAll, children }) => (
  <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm">
    <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 dark:border-gray-800">
      <h3 className="text-[15px] font-semibold text-gray-800 dark:text-gray-200">{title}</h3>
      {onViewAll && (
        <button onClick={onViewAll} className="text-[13px] text-[#0066ff] dark:text-blue-400 font-medium flex items-center gap-0.5 hover:underline">
          View All <ChevronRight size={14} />
        </button>
      )}
    </div>
    <div className="p-5">{children}</div>
  </div>
);

const Home: React.FC = () => {
  const { showToast } = useToast();
  const { hasPermission, currentTenant } = useAuth();
  const { navigate } = useNavigation();

  const [period, setPeriod] = useState('THIS_MONTH');
  const [loading, setLoading] = useState(true);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [dashboardError, setDashboardError] = useState(false);
  const [alerts, setAlerts] = useState<DashboardAlert[]>([]);
  const [alertsError, setAlertsError] = useState(false);
  const [recent, setRecent] = useState<RecentTransaction[]>([]);
  const [recentError, setRecentError] = useState(false);
  const [pendingSync, setPendingSync] = useState(0);
  const [online, setOnline] = useState(isBrowserOnline());

  const canViewReceivables = hasPermission('reports.view_receivables');
  const canViewPayables = hasPermission('reports.view_payables');
  const canViewGst = hasPermission('reports.view_gst');
  const canViewPayments = hasPermission('reports.view_payments');
  const canViewInventory = hasPermission('reports.view_inventory');
  const canViewSales = hasPermission('reports.view_sales');

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    setDashboardError(false);
    try {
      const data = await getDashboard(period);
      setDashboard(data);
    } catch (err) {
      setDashboardError(true);
      showToast(err instanceof ApiError ? err.message : 'Unable to load dashboard data.', 'error');
    } finally {
      setLoading(false);
    }
  }, [period, showToast]);

  useEffect(() => { loadDashboard(); }, [loadDashboard]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getDashboardAlerts();
        if (!cancelled) setAlerts(data);
      } catch {
        if (!cancelled) setAlertsError(true);
      }
      try {
        const data = await getRecentTransactions();
        if (!cancelled) setRecent(data);
      } catch {
        if (!cancelled) setRecentError(true);
      }
    })();
    return () => { cancelled = true; };
  }, [period]);

  useEffect(() => {
    if (!currentTenant) return;
    let cancelled = false;
    const refreshSync = async () => {
      try {
        const items = await dbGetAllByTenant<{ status: string }>(STORE_SYNC_QUEUE, currentTenant.id);
        if (!cancelled) setPendingSync(items.filter((i) => i.status === 'PENDING_SYNC' || i.status === 'SYNCING').length);
      } catch {
        // IndexedDB unavailable — sync widget just omits the pending count.
      }
    };
    refreshSync();
    const unsubscribe = subscribeToConnectivity(setOnline);
    return () => { cancelled = true; unsubscribe(); };
  }, [currentTenant]);

  const quickActions = [
    { label: 'New Sales Invoice', icon: <FileText size={15} />, view: 'Sales Invoices', permission: 'sales_invoice.create' },
    { label: 'New Customer', icon: <Users size={15} />, view: 'Customers', permission: 'customers.create' },
    { label: 'New Sales Order', icon: <ShoppingCart size={15} />, view: 'Sales Orders', permission: 'sales_order.create' },
    { label: 'New Delivery Challan', icon: <Truck size={15} />, view: 'Delivery Challans', permission: 'delivery_challan.create' },
    { label: 'New Purchase Invoice', icon: <ClipboardList size={15} />, view: 'Purchase Invoices', permission: 'purchase_invoice.create' },
    { label: 'Record Collection', icon: <Wallet size={15} />, view: 'Customer Receipts', permission: 'customer_receipt.create' },
  ].filter((a) => hasPermission(a.permission));

  const agingTotal = dashboard?.receivables.aging
    ? (Object.values(dashboard.receivables.aging) as string[]).reduce((sum: number, v: string) => sum + Number(v), 0)
    : 0;

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 flex flex-col md:flex-row justify-between items-stretch md:items-center gap-4 shadow-sm">
        <div>
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">Dashboard Overview</h2>
          <p className="text-[13px] text-gray-500 dark:text-gray-400 flex items-center gap-1.5 mt-0.5">
            {online ? <Wifi size={13} className="text-green-600" /> : <WifiOff size={13} className="text-amber-600" />}
            {online ? 'Online' : 'Offline'}
            {pendingSync > 0 && <span className="ml-1 px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 text-[11px] font-medium">{pendingSync} pending sync</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2"
          >
            {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
          <button onClick={loadDashboard} className="p-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {quickActions.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-6">
          {quickActions.map((a) => (
            <button
              key={a.label}
              onClick={() => navigate(a.view)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] font-medium hover:bg-gray-50 dark:hover:bg-gray-700"
            >
              <Plus size={13} className="text-[#0066ff]" /> {a.icon} {a.label}
            </button>
          ))}
        </div>
      )}

      {loading ? (
        <LoadingState label="Loading dashboard…" />
      ) : dashboardError || !dashboard ? (
        <EmptyState title="Unable to load dashboard data." description="Please try again." action={<button onClick={loadDashboard} className="text-[13px] text-[#0066ff] font-medium">Retry</button>} />
      ) : (
        <>
          {/* Primary KPIs */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            {canViewSales && (
              <KpiCard title="Net Sales" value={formatInr(dashboard.sales.net_sales)} icon={<TrendingUp size={16} className="opacity-60" />}
                color="bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-400"
                onClick={() => navigate('Sales Invoices')} />
            )}
            {canViewReceivables && (
              <KpiCard title="Receivables Outstanding" value={formatInr(dashboard.receivables.total_outstanding)} icon={<Wallet size={16} className="opacity-60" />}
                color="bg-purple-50 dark:bg-purple-900/20 border-purple-200 dark:border-purple-800 text-purple-700 dark:text-purple-400"
                onClick={() => navigate('Customer Receipts')} />
            )}
            {canViewPayables && (
              <KpiCard title="Payables Outstanding" value={formatInr(dashboard.payables.total_outstanding)} icon={<Banknote size={16} className="opacity-60" />}
                color="bg-orange-50 dark:bg-orange-900/20 border-orange-200 dark:border-orange-800 text-orange-700 dark:text-orange-400"
                onClick={() => navigate('Supplier Payments')} />
            )}
            {canViewInventory && (
              <KpiCard title="Low / Out of Stock" value={`${dashboard.inventory.low_stock_item_count} / ${dashboard.inventory.out_of_stock_item_count}`} icon={<Package size={16} className="opacity-60" />}
                color="bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 text-red-700 dark:text-red-400"
                onClick={() => navigate('Inventory')} />
            )}
          </div>

          {/* Action Required */}
          <SectionCard title="Action Required">
            {alertsError ? (
              <p className="text-[13px] text-gray-500 dark:text-gray-400">Unable to load alerts.</p>
            ) : alerts.length === 0 ? (
              <EmptyState title="Nothing needs your attention" description="All caught up — no critical or warning items right now." />
            ) : (
              <div className="space-y-2">
                {alerts.map((a, i) => (
                  <button
                    key={i}
                    onClick={() => navigate(a.action_view)}
                    className={`w-full text-left flex items-start justify-between gap-3 p-3 rounded-lg border ${SEVERITY_STYLE[a.severity] || SEVERITY_STYLE.INFO}`}
                  >
                    <div>
                      <p className="text-[14px] font-semibold">{a.title}</p>
                      <p className="text-[12px] opacity-80">{a.description}</p>
                    </div>
                    <ChevronRight size={16} className="shrink-0 mt-0.5" />
                  </button>
                ))}
              </div>
            )}
          </SectionCard>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
            {canViewSales && (
              <SectionCard title="Top Products" onViewAll={() => navigate('Reports')}>
                {dashboard.sales.top_products.length === 0 ? (
                  <EmptyState title="No sales in this period" />
                ) : (
                  <div className="space-y-1">
                    {dashboard.sales.top_products.map((p) => (
                      <div key={p.product_id} className="flex items-center justify-between py-2 border-b border-gray-50 dark:border-gray-800 last:border-0">
                        <div>
                          <p className="text-[14px] font-medium text-gray-900 dark:text-gray-100">{p.product_name}</p>
                          <p className="text-[12px] text-gray-500 dark:text-gray-400">Qty {p.quantity_sold}</p>
                        </div>
                        <span className="text-[14px] font-semibold text-gray-700 dark:text-gray-300">{formatInr(p.net_sales)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </SectionCard>
            )}

            {canViewReceivables && (
              <SectionCard title="Receivables Aging" onViewAll={() => navigate('Customer Receipts')}>
                {agingTotal === 0 ? (
                  <EmptyState title="No outstanding receivables" />
                ) : (
                  <>
                    <div className="flex h-3 rounded-full overflow-hidden mb-3 bg-gray-100 dark:bg-gray-800">
                      {(['current', 'days_1_30', 'days_31_60', 'days_61_90', 'days_90_plus'] as const).map((bucket, i) => {
                        const val = Number(dashboard.receivables.aging[bucket]);
                        const pct = agingTotal > 0 ? (val / agingTotal) * 100 : 0;
                        const colors = ['bg-green-500', 'bg-yellow-400', 'bg-orange-400', 'bg-red-400', 'bg-red-700'];
                        return pct > 0 ? <div key={bucket} className={colors[i]} style={{ width: `${pct}%` }} /> : null;
                      })}
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-[12px] mb-4">
                      <span>Current: <strong>{formatInr(dashboard.receivables.aging.current)}</strong></span>
                      <span>1-30d: <strong>{formatInr(dashboard.receivables.aging.days_1_30)}</strong></span>
                      <span>31-60d: <strong>{formatInr(dashboard.receivables.aging.days_31_60)}</strong></span>
                      <span>61-90d: <strong>{formatInr(dashboard.receivables.aging.days_61_90)}</strong></span>
                      <span className="text-red-600 dark:text-red-400">90+ days: <strong>{formatInr(dashboard.receivables.aging.days_90_plus)}</strong></span>
                      <span>No due date: <strong>{formatInr(dashboard.receivables.aging.no_due_date)}</strong></span>
                    </div>
                    <div className="space-y-1">
                      {dashboard.receivables.top_customers.map((c) => (
                        <div key={c.customer_id} className="flex items-center justify-between py-1.5">
                          <span className="text-[13px] text-gray-700 dark:text-gray-300">{c.customer_name}</span>
                          <span className="text-[13px] font-semibold text-gray-900 dark:text-gray-100">{formatInr(c.outstanding)}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </SectionCard>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
            {canViewPayables && (
              <SectionCard title="Supplier Outstanding" onViewAll={() => navigate('Supplier Payments')}>
                {dashboard.payables.top_suppliers.length === 0 ? (
                  <EmptyState title="No outstanding payables" />
                ) : (
                  <div className="space-y-1">
                    {dashboard.payables.top_suppliers.map((s) => (
                      <div key={s.supplier_id} className="flex items-center justify-between py-1.5">
                        <span className="text-[13px] text-gray-700 dark:text-gray-300">{s.supplier_name}</span>
                        <span className="text-[13px] font-semibold text-gray-900 dark:text-gray-100">{formatInr(s.outstanding)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </SectionCard>
            )}

            <SectionCard title="Order → Delivery → Collection Pipeline">
              <div className="grid grid-cols-3 gap-3 text-center">
                <button onClick={() => navigate('Sales Orders')} className="p-3 rounded-lg bg-gray-50 dark:bg-gray-800">
                  <p className="text-xl font-bold text-gray-900 dark:text-gray-100">{dashboard.pipeline.open_sales_orders}</p>
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1">Open Orders</p>
                </button>
                <button onClick={() => navigate('Delivery Challans')} className="p-3 rounded-lg bg-gray-50 dark:bg-gray-800">
                  <p className="text-xl font-bold text-gray-900 dark:text-gray-100">{dashboard.pipeline.pending_delivery_challans}</p>
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1">Pending DC</p>
                </button>
                <button onClick={() => navigate('Sales Invoices')} className="p-3 rounded-lg bg-gray-50 dark:bg-gray-800">
                  <p className="text-xl font-bold text-gray-900 dark:text-gray-100">{dashboard.pipeline.unpaid_invoices}</p>
                  <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1">Unpaid Invoices</p>
                </button>
              </div>
              {canViewPayments && (dashboard.payment_exceptions.unallocated_payments > 0 || dashboard.payment_exceptions.cheques_pending > 0 || dashboard.payment_exceptions.cheques_bounced > 0) && (
                <div className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-800 flex flex-wrap gap-2">
                  {dashboard.payment_exceptions.cheques_bounced > 0 && (
                    <button onClick={() => navigate('Customer Receipts')} className="text-[12px] px-2.5 py-1 rounded-full bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 font-medium">
                      {dashboard.payment_exceptions.cheques_bounced} Cheque(s) Bounced
                    </button>
                  )}
                  {dashboard.payment_exceptions.cheques_pending > 0 && (
                    <button onClick={() => navigate('Customer Receipts')} className="text-[12px] px-2.5 py-1 rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 font-medium">
                      {dashboard.payment_exceptions.cheques_pending} Cheque(s) Pending
                    </button>
                  )}
                  {dashboard.payment_exceptions.unallocated_payments > 0 && (
                    <button onClick={() => navigate('Customer Receipts')} className="text-[12px] px-2.5 py-1 rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 font-medium">
                      {dashboard.payment_exceptions.unallocated_payments} Unallocated Payment(s)
                    </button>
                  )}
                </div>
              )}
            </SectionCard>
          </div>

          {canViewGst && (
            <div className="mt-6">
              <SectionCard title={`GST Summary (${dashboard.gst.return_period})`} onViewAll={() => navigate('GST Filing')}>
                <div className="grid grid-cols-3 gap-4 text-center">
                  <div>
                    <p className="text-[12px] text-gray-500 dark:text-gray-400">Output GST</p>
                    <p className="text-[16px] font-semibold text-gray-900 dark:text-gray-100">{formatInr(dashboard.gst.output_gst)}</p>
                  </div>
                  <div>
                    <p className="text-[12px] text-gray-500 dark:text-gray-400">Input GST</p>
                    <p className="text-[16px] font-semibold text-gray-900 dark:text-gray-100">{formatInr(dashboard.gst.input_gst)}</p>
                  </div>
                  <div>
                    <p className="text-[12px] text-gray-500 dark:text-gray-400">Net GST Position</p>
                    <p className="text-[16px] font-semibold text-gray-900 dark:text-gray-100">{formatInr(dashboard.gst.net_gst_position)}</p>
                  </div>
                </div>
              </SectionCard>
            </div>
          )}

          <div className="mt-6">
            <SectionCard title="Recent Transactions">
              {recentError ? (
                <p className="text-[13px] text-gray-500 dark:text-gray-400">Unable to load recent transactions.</p>
              ) : recent.length === 0 ? (
                <EmptyState title="No recent transactions" />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-[13px]">
                    <thead>
                      <tr className="text-left text-gray-500 dark:text-gray-400 border-b border-gray-100 dark:border-gray-800">
                        <th className="pb-2 font-medium">Date</th>
                        <th className="pb-2 font-medium">Type</th>
                        <th className="pb-2 font-medium">Reference</th>
                        <th className="pb-2 font-medium">Party</th>
                        <th className="pb-2 font-medium text-right">Amount</th>
                        <th className="pb-2 font-medium text-right">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recent.map((t, i) => (
                        <tr key={i} className="border-b border-gray-50 dark:border-gray-800 last:border-0">
                          <td className="py-2 text-gray-600 dark:text-gray-400">{t.date}</td>
                          <td className="py-2 text-gray-700 dark:text-gray-300">{TRANSACTION_LABEL[t.type] || t.type}</td>
                          <td className="py-2 font-medium text-gray-900 dark:text-gray-100">{t.reference}</td>
                          <td className="py-2 text-gray-600 dark:text-gray-400">{t.party}</td>
                          <td className="py-2 text-right font-semibold text-gray-900 dark:text-gray-100">{formatInr(t.amount)}</td>
                          <td className="py-2 text-right text-gray-500 dark:text-gray-400">{t.status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </SectionCard>
          </div>
        </>
      )}
    </div>
  );
};

export default Home;
