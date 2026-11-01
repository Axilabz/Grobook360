import React, { useEffect, useState } from 'react';
import { useToast } from '../../context/ToastContext';
import { useNavigation } from '../../context/NavigationContext';
import { ApiError } from '../../api/client';
import { fetchSalesAnalysis, fetchSalesByUser, AnalysisQueryParams, SalesAnalysisData, SalesByUserRow } from '../../api/analysis';
import LoadingState from '../../shared/LoadingState';
import EmptyState from '../../shared/EmptyState';
import KpiCard from '../../shared/charts/KpiCard';
import TrendLineChart from '../../shared/charts/TrendLineChart';
import RankingBarChart from '../../shared/charts/RankingBarChart';
import InsightsPanel, { Insight } from './InsightsPanel';
import ExportButton from '../../shared/ExportButton';
import { formatInr, formatQuantity } from '../../shared/formatters';

interface Props { params: AnalysisQueryParams; refreshKey: number }

const SalesAnalysisTab: React.FC<Props> = ({ params, refreshKey }) => {
  const { showToast } = useToast();
  const { navigate } = useNavigation();
  const [data, setData] = useState<SalesAnalysisData | null>(null);
  const [byUser, setByUser] = useState<SalesByUserRow[]>([]);
  const [dateFrom, setDateFrom] = useState<string | undefined>();
  const [dateTo, setDateTo] = useState<string | undefined>();
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    Promise.all([fetchSalesAnalysis(params), fetchSalesByUser(params)])
      .then(([salesRes, byUserRes]) => {
        if (cancelled) return;
        setData(salesRes.data);
        setDateFrom(salesRes.period.date_from);
        setDateTo(salesRes.period.date_to);
        setByUser(byUserRes.data);
      })
      .catch((err) => {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : 'Failed to load sales analysis.';
        setError(msg);
        showToast(msg, 'error');
      })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.period, params.dateFrom, params.dateTo, params.compare, params.compareFrom, params.compareTo, refreshKey]);

  if (isLoading) return <LoadingState label="Loading sales analysis…" />;
  if (error) return <EmptyState title="Couldn't load this analysis" description={error} />;
  if (!data) return null;

  const insights: Insight[] = [];
  if (data.kpis.net_sales.change_percent !== null) {
    const pct = Number(data.kpis.net_sales.change_percent);
    insights.push({ text: `Net Sales ${pct >= 0 ? 'grew' : 'declined'} ${Math.abs(pct).toFixed(1)}% vs the comparison period.`, severity: pct >= 0 ? 'positive' : 'negative' });
  }
  if (data.kpis.invoice_count.change_percent !== null && data.kpis.net_sales.change_percent !== null) {
    const invoicePct = Number(data.kpis.invoice_count.change_percent);
    const salesPct = Number(data.kpis.net_sales.change_percent);
    if (Math.abs(salesPct - invoicePct) > 5) {
      insights.push({
        text: salesPct > invoicePct
          ? 'Sales growth is outpacing invoice-count growth — driven more by higher invoice values than more transactions.'
          : 'Invoice count is growing faster than sales value — driven more by transaction volume than higher invoice values.',
        severity: 'neutral',
      });
    }
  }
  const top5 = data.table.slice(0, 5);
  const top5Share = top5.reduce((sum, r) => sum + (Number(r.contribution_percent) || 0), 0);
  if (top5.length > 0) {
    insights.push({ text: `The top 5 products account for ${top5Share.toFixed(1)}% of net sales in this period.`, severity: 'neutral' });
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard title="Gross Sales" kpi={data.kpis.gross_sales} />
        <KpiCard title="Discounts" kpi={data.kpis.discounts} />
        <KpiCard title="Sales Returns" kpi={data.kpis.sales_returns} />
        <KpiCard title="Net Sales" kpi={data.kpis.net_sales} />
        <KpiCard title="Invoice Count" kpi={data.kpis.invoice_count} format="count" />
        <KpiCard title="Avg Invoice Value" kpi={data.kpis.average_invoice_value} />
        <KpiCard title="Quantity Sold" kpi={data.kpis.quantity_sold} format="quantity" />
      </div>

      <InsightsPanel insights={insights} />

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
        <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Sales Trend</h3>
        <TrendLineChart series={[{ name: 'Net Sales', color: '#0066ff', points: data.sales_trend }]} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Top 10 Products</h3>
          <RankingBarChart data={data.top_products.map((p) => ({ id: p.product_id, label: p.product_name, value: Number(p.net_sales) }))} onBarClick={(row) => navigate('Products', { id: row.id })} />
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Top 10 Customers</h3>
          <RankingBarChart data={data.top_customers.map((c) => ({ id: c.customer_id, label: c.customer_name, value: Number(c.net_sales) }))} color="#16a34a" onBarClick={(row) => navigate('Customers', { id: row.id })} />
        </div>
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
        <div className="p-5 pb-3">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200">Sales by User</h3>
          <p className="text-[12px] text-gray-400 mt-0.5">How many sales each staff member has made in this period (POSTED invoices).</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead className="bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400 text-[11px] uppercase">
              <tr>
                <th className="text-left px-5 py-2.5">User</th>
                <th className="text-right px-5 py-2.5">Invoices</th>
                <th className="text-right px-5 py-2.5">Total Amount</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {byUser.map((row) => (
                <tr key={row.user_id || row.user_name}>
                  <td className="px-5 py-2.5 text-gray-800 dark:text-gray-200">{row.user_name}</td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{row.invoice_count}</td>
                  <td className="px-5 py-2.5 text-right font-medium text-gray-800 dark:text-gray-200">{formatInr(row.total_amount)}</td>
                </tr>
              ))}
              {byUser.length === 0 && (
                <tr><td colSpan={3} className="px-5 py-8 text-center text-gray-400">No sales in this period.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between p-5 pb-0">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200">Product Sales Table</h3>
          <ExportButton resource="analysis_sales_products" exportPermission="reports.export" dateFrom={dateFrom} dateTo={dateTo} page={1} pageSize={500} totalItems={data.table.length} />
        </div>
        <div className="overflow-x-auto mt-3">
          <table className="w-full text-[13px]">
            <thead className="bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400 text-[11px] uppercase">
              <tr>
                <th className="text-left px-5 py-2.5">Product</th>
                <th className="text-right px-5 py-2.5">Qty Sold</th>
                <th className="text-right px-5 py-2.5">Net Sales</th>
                <th className="text-right px-5 py-2.5">Contribution %</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {data.table.map((row) => (
                <tr key={row.product_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer" onClick={() => navigate('Products', { id: row.product_id })}>
                  <td className="px-5 py-2.5 text-gray-800 dark:text-gray-200">{row.product_name} <span className="text-gray-400 text-[11px]">({row.sku})</span></td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{formatQuantity(row.quantity_sold)}</td>
                  <td className="px-5 py-2.5 text-right font-medium text-gray-800 dark:text-gray-200">{formatInr(row.net_sales)}</td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{row.contribution_percent !== null ? `${Number(row.contribution_percent).toFixed(1)}%` : '—'}</td>
                </tr>
              ))}
              {data.table.length === 0 && (
                <tr><td colSpan={4} className="px-5 py-8 text-center text-gray-400">No sales in this period.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default SalesAnalysisTab;
