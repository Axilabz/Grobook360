import React, { useEffect, useState } from 'react';
import { useToast } from '../../context/ToastContext';
import { useNavigation } from '../../context/NavigationContext';
import { ApiError } from '../../api/client';
import { fetchPurchaseAnalysis, AnalysisQueryParams, PurchaseAnalysisData } from '../../api/analysis';
import LoadingState from '../../shared/LoadingState';
import EmptyState from '../../shared/EmptyState';
import KpiCard from '../../shared/charts/KpiCard';
import TrendLineChart from '../../shared/charts/TrendLineChart';
import RankingBarChart from '../../shared/charts/RankingBarChart';
import InsightsPanel, { Insight } from './InsightsPanel';
import ExportButton from '../../shared/ExportButton';
import { formatInr } from '../../shared/formatters';

interface Props { params: AnalysisQueryParams; refreshKey: number }

const PurchaseAnalysisTab: React.FC<Props> = ({ params, refreshKey }) => {
  const { showToast } = useToast();
  const { navigate } = useNavigation();
  const [data, setData] = useState<PurchaseAnalysisData | null>(null);
  const [dateFrom, setDateFrom] = useState<string | undefined>();
  const [dateTo, setDateTo] = useState<string | undefined>();
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    fetchPurchaseAnalysis(params)
      .then((res) => { if (!cancelled) { setData(res.data); setDateFrom(res.period.date_from); setDateTo(res.period.date_to); } })
      .catch((err) => {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : 'Failed to load purchase analysis.';
        setError(msg);
        showToast(msg, 'error');
      })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.period, params.dateFrom, params.dateTo, params.compare, params.compareFrom, params.compareTo, refreshKey]);

  if (isLoading) return <LoadingState label="Loading purchase analysis…" />;
  if (error) return <EmptyState title="Couldn't load this analysis" description={error} />;
  if (!data) return null;

  const insights: Insight[] = [];
  if (data.kpis.net_purchase.change_percent !== null) {
    const pct = Number(data.kpis.net_purchase.change_percent);
    insights.push({ text: `Net Purchase ${pct >= 0 ? 'grew' : 'declined'} ${Math.abs(pct).toFixed(1)}% vs the comparison period.`, severity: pct >= 0 ? 'neutral' : 'positive' });
  }
  if (data.top_suppliers.length > 0) {
    const totalShown = data.top_suppliers.reduce((sum, s) => sum + Number(s.net_purchase), 0);
    const topShare = totalShown > 0 ? (Number(data.top_suppliers[0].net_purchase) / totalShown) * 100 : 0;
    if (topShare > 40) {
      insights.push({ text: `Purchases are concentrated: ${data.top_suppliers[0].supplier_name} accounts for ${topShare.toFixed(1)}% of purchase value among suppliers shown.`, severity: 'neutral', onInvestigate: () => navigate('Suppliers', { id: data.top_suppliers[0].supplier_id }) });
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard title="Gross Purchase" kpi={data.kpis.gross_purchase} />
        <KpiCard title="Purchase Returns" kpi={data.kpis.purchase_returns} />
        <KpiCard title="Net Purchase" kpi={data.kpis.net_purchase} />
        <KpiCard title="Invoice Count" kpi={data.kpis.invoice_count} format="count" />
      </div>

      <InsightsPanel insights={insights} />

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
        <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Purchase Trend</h3>
        <TrendLineChart series={[{ name: 'Net Purchase', color: '#f97316', points: data.purchase_trend }]} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Top Suppliers by Purchase Value</h3>
          <RankingBarChart data={data.top_suppliers.map((s) => ({ id: s.supplier_id, label: s.supplier_name, value: Number(s.net_purchase) }))} color="#f97316" onBarClick={(row) => navigate('Suppliers', { id: row.id })} />
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Top Products Purchased</h3>
          <RankingBarChart data={data.top_products.map((p) => ({ id: p.product_id, label: p.product_name, value: Number(p.net_purchase) }))} onBarClick={(row) => navigate('Products', { id: row.id })} />
        </div>
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between p-5 pb-0">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200">Supplier Purchase Table</h3>
          <ExportButton resource="analysis_purchase_suppliers" exportPermission="reports.export" dateFrom={dateFrom} dateTo={dateTo} page={1} pageSize={500} totalItems={data.top_suppliers.length} />
        </div>
        <div className="overflow-x-auto mt-3">
          <table className="w-full text-[13px]">
            <thead className="bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400 text-[11px] uppercase">
              <tr>
                <th className="text-left px-5 py-2.5">Supplier</th>
                <th className="text-right px-5 py-2.5">Invoices</th>
                <th className="text-right px-5 py-2.5">Net Purchase</th>
                <th className="text-right px-5 py-2.5">Returns</th>
                <th className="text-right px-5 py-2.5">Outstanding</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {data.top_suppliers.map((row) => (
                <tr key={row.supplier_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer" onClick={() => navigate('Suppliers', { id: row.supplier_id })}>
                  <td className="px-5 py-2.5 text-gray-800 dark:text-gray-200">{row.supplier_name}</td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{row.invoice_count}</td>
                  <td className="px-5 py-2.5 text-right font-medium text-gray-800 dark:text-gray-200">{formatInr(row.net_purchase)}</td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{formatInr(row.returns)}</td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{formatInr(row.outstanding)}</td>
                </tr>
              ))}
              {data.top_suppliers.length === 0 && (
                <tr><td colSpan={5} className="px-5 py-8 text-center text-gray-400">No purchases in this period.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default PurchaseAnalysisTab;
