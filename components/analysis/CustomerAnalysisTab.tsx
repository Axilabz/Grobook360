import React, { useEffect, useState } from 'react';
import { useToast } from '../../context/ToastContext';
import { useNavigation } from '../../context/NavigationContext';
import { ApiError } from '../../api/client';
import { fetchCustomerAnalysis, AnalysisQueryParams, CustomerAnalysisData } from '../../api/analysis';
import LoadingState from '../../shared/LoadingState';
import EmptyState from '../../shared/EmptyState';
import KpiCard from '../../shared/charts/KpiCard';
import RankingBarChart from '../../shared/charts/RankingBarChart';
import AgingDonutChart from '../../shared/charts/AgingDonutChart';
import InsightsPanel, { Insight } from './InsightsPanel';
import ExportButton from '../../shared/ExportButton';
import { formatInr, formatPercent } from '../../shared/formatters';

interface Props { params: AnalysisQueryParams; refreshKey: number }

const CustomerAnalysisTab: React.FC<Props> = ({ params, refreshKey }) => {
  const { showToast } = useToast();
  const { navigate } = useNavigation();
  const [data, setData] = useState<CustomerAnalysisData | null>(null);
  const [dateFrom, setDateFrom] = useState<string | undefined>();
  const [dateTo, setDateTo] = useState<string | undefined>();
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    fetchCustomerAnalysis(params)
      .then((res) => { if (!cancelled) { setData(res.data); setDateFrom(res.period.date_from); setDateTo(res.period.date_to); } })
      .catch((err) => {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : 'Failed to load customer analysis.';
        setError(msg);
        showToast(msg, 'error');
      })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.period, params.dateFrom, params.dateTo, params.compare, params.compareFrom, params.compareTo, refreshKey]);

  if (isLoading) return <LoadingState label="Loading customer analysis…" />;
  if (error) return <EmptyState title="Couldn't load this analysis" description={error} />;
  if (!data) return null;

  const insights: Insight[] = [];
  const declining = data.table.filter((r) => r.change_percent !== null && Number(r.change_percent) < -10);
  if (declining.length > 0) {
    insights.push({ text: `${declining.length} customer(s) reduced purchasing more than 10% vs the comparison period.`, severity: 'negative' });
  }
  const highOverdue = [...data.table].filter((r) => Number(r.overdue_amount) > 0).sort((a, b) => Number(b.overdue_amount) - Number(a.overdue_amount));
  if (highOverdue.length > 0) {
    insights.push({ text: `${highOverdue[0].customer_name} has the highest overdue balance (${formatInr(highOverdue[0].overdue_amount)}).`, severity: 'negative', onInvestigate: () => navigate('Customers', { id: highOverdue[0].customer_id }) });
  }
  if (data.top_customers.length > 0) {
    const top3Share = data.top_customers.slice(0, 3).reduce((sum, c) => sum + Number(c.net_sales), 0);
    const totalShown = data.top_customers.reduce((sum, c) => sum + Number(c.net_sales), 0);
    if (totalShown > 0) {
      insights.push({ text: `The top 3 customers account for ${((top3Share / totalShown) * 100).toFixed(1)}% of sales among customers shown.`, severity: 'neutral' });
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <KpiCard title="Sales to Customers" kpi={data.kpis.sales_to_customers} />
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4 shadow-sm">
          <span className="text-[12px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Active Customers</span>
          <p className="text-[22px] font-bold text-gray-900 dark:text-gray-100 mt-2">{data.kpis.active_customers}</p>
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4 shadow-sm">
          <span className="text-[12px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Avg Sales / Customer</span>
          <p className="text-[22px] font-bold text-gray-900 dark:text-gray-100 mt-2">{formatInr(data.kpis.average_sales_per_customer)}</p>
        </div>
      </div>

      <InsightsPanel insights={insights} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Top Customers by Sales</h3>
          <RankingBarChart data={data.top_customers.map((c) => ({ id: c.customer_id, label: c.customer_name, value: Number(c.net_sales) }))} color="#16a34a" onBarClick={(row) => navigate('Customers', { id: row.id })} />
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Receivables Aging</h3>
          <AgingDonutChart aging={data.receivables_aging} />
        </div>
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between p-5 pb-0">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200">Customer Analysis Table</h3>
          <ExportButton resource="analysis_customers" exportPermission="reports.export" dateFrom={dateFrom} dateTo={dateTo} page={1} pageSize={500} totalItems={data.table.length} />
        </div>
        <div className="overflow-x-auto mt-3">
          <table className="w-full text-[13px]">
            <thead className="bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400 text-[11px] uppercase">
              <tr>
                <th className="text-left px-5 py-2.5">Customer</th>
                <th className="text-right px-5 py-2.5">Invoices</th>
                <th className="text-right px-5 py-2.5">Net Sales</th>
                <th className="text-right px-5 py-2.5">Avg Invoice</th>
                <th className="text-right px-5 py-2.5">Outstanding</th>
                <th className="text-right px-5 py-2.5">Overdue</th>
                <th className="text-right px-5 py-2.5">Period Change</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {data.table.map((row) => (
                <tr key={row.customer_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer" onClick={() => navigate('Customers', { id: row.customer_id })}>
                  <td className="px-5 py-2.5 text-gray-800 dark:text-gray-200">{row.customer_name}</td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{row.invoice_count}</td>
                  <td className="px-5 py-2.5 text-right font-medium text-gray-800 dark:text-gray-200">{formatInr(row.net_sales)}</td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{formatInr(row.average_invoice_value)}</td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{formatInr(row.outstanding)}</td>
                  <td className={`px-5 py-2.5 text-right ${Number(row.overdue_amount) > 0 ? 'text-red-600 dark:text-red-400 font-medium' : 'text-gray-600 dark:text-gray-300'}`}>{formatInr(row.overdue_amount)}</td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{formatPercent(row.change_percent)}</td>
                </tr>
              ))}
              {data.table.length === 0 && (
                <tr><td colSpan={7} className="px-5 py-8 text-center text-gray-400">No customer sales in this period.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default CustomerAnalysisTab;
