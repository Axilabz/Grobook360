import React, { useEffect, useState } from 'react';
import { useToast } from '../../context/ToastContext';
import { useNavigation } from '../../context/NavigationContext';
import { ApiError } from '../../api/client';
import { fetchProductAnalysis, AnalysisQueryParams, ProductAnalysisData } from '../../api/analysis';
import LoadingState from '../../shared/LoadingState';
import EmptyState from '../../shared/EmptyState';
import TrendLineChart from '../../shared/charts/TrendLineChart';
import RankingBarChart from '../../shared/charts/RankingBarChart';
import InsightsPanel, { Insight } from './InsightsPanel';
import ExportButton from '../../shared/ExportButton';
import { formatInr, formatQuantity, formatPercent } from '../../shared/formatters';

interface Props { params: AnalysisQueryParams; refreshKey: number }

const STOCK_BADGE: Record<string, string> = {
  IN_STOCK: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  LOW_STOCK: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  OUT_OF_STOCK: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
};

const ProductAnalysisTab: React.FC<Props> = ({ params, refreshKey }) => {
  const { showToast } = useToast();
  const { navigate } = useNavigation();
  const [data, setData] = useState<ProductAnalysisData | null>(null);
  const [dateFrom, setDateFrom] = useState<string | undefined>();
  const [dateTo, setDateTo] = useState<string | undefined>();
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    fetchProductAnalysis(params)
      .then((res) => { if (!cancelled) { setData(res.data); setDateFrom(res.period.date_from); setDateTo(res.period.date_to); } })
      .catch((err) => {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : 'Failed to load product analysis.';
        setError(msg);
        showToast(msg, 'error');
      })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.period, params.dateFrom, params.dateTo, params.compare, params.compareFrom, params.compareTo, refreshKey]);

  if (isLoading) return <LoadingState label="Loading product analysis…" />;
  if (error) return <EmptyState title="Couldn't load this analysis" description={error} />;
  if (!data) return null;

  const insights: Insight[] = [];
  const declining = data.table.filter((r) => r.change_percent !== null && Number(r.change_percent) < -10);
  if (declining.length > 0) {
    insights.push({ text: `${declining.length} product(s) declined more than 10% vs the comparison period — e.g. ${declining[0].product_name}.`, severity: 'negative' });
  }
  const highStockLowSales = data.table.filter((r) => r.current_stock !== null && Number(r.current_stock) > 500 && Number(r.quantity_sold) < 10);
  if (highStockLowSales.length > 0) {
    insights.push({ text: `${highStockLowSales.length} product(s) have high stock relative to recent sales — may be worth reviewing for overstock.`, severity: 'neutral' });
  }
  const returned = data.table.filter((r) => Number(r.returns) > 0).sort((a, b) => Number(b.returns) - Number(a.returns));
  if (returned.length > 0) {
    insights.push({ text: `${returned[0].product_name} has the highest return value this period (${formatInr(returned[0].returns)}).`, severity: 'neutral' });
  }

  return (
    <div className="space-y-6">
      <InsightsPanel insights={insights} />

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
        <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Product Sales Trend</h3>
        <TrendLineChart series={[{ name: 'Net Sales', color: '#0066ff', points: data.sales_trend }]} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Top 10 Products</h3>
          <RankingBarChart data={data.top_10.map((p) => ({ id: p.product_id, label: p.product_name, value: Number(p.net_sales) }))} onBarClick={(row) => navigate('Products', { id: row.id })} />
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Bottom 10 Products</h3>
          <RankingBarChart data={data.bottom_10.map((p) => ({ id: p.product_id, label: p.product_name, value: Number(p.net_sales) }))} color="#ef4444" onBarClick={(row) => navigate('Products', { id: row.id })} />
        </div>
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between p-5 pb-0">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200">Product Performance Table</h3>
          <ExportButton resource="analysis_sales_products" exportPermission="reports.export" dateFrom={dateFrom} dateTo={dateTo} page={1} pageSize={500} totalItems={data.table.length} />
        </div>
        <div className="overflow-x-auto mt-3">
          <table className="w-full text-[13px]">
            <thead className="bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400 text-[11px] uppercase">
              <tr>
                <th className="text-left px-5 py-2.5">Product</th>
                <th className="text-right px-5 py-2.5">Qty Sold</th>
                <th className="text-right px-5 py-2.5">Net Sales</th>
                <th className="text-right px-5 py-2.5">Current Stock</th>
                <th className="text-center px-5 py-2.5">Status</th>
                <th className="text-right px-5 py-2.5">Returns</th>
                <th className="text-right px-5 py-2.5">Period Change</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {data.table.map((row) => (
                <tr key={row.product_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer" onClick={() => navigate('Products', { id: row.product_id })}>
                  <td className="px-5 py-2.5 text-gray-800 dark:text-gray-200">{row.product_name} <span className="text-gray-400 text-[11px]">({row.sku})</span></td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{formatQuantity(row.quantity_sold)}</td>
                  <td className="px-5 py-2.5 text-right font-medium text-gray-800 dark:text-gray-200">{formatInr(row.net_sales)}</td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{row.current_stock !== null ? formatQuantity(row.current_stock) : '—'}</td>
                  <td className="px-5 py-2.5 text-center">
                    {row.stock_status && <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${STOCK_BADGE[row.stock_status] || ''}`}>{row.stock_status.replace('_', ' ')}</span>}
                  </td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{formatInr(row.returns)}</td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{formatPercent(row.change_percent)}</td>
                </tr>
              ))}
              {data.table.length === 0 && (
                <tr><td colSpan={7} className="px-5 py-8 text-center text-gray-400">No product sales in this period.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default ProductAnalysisTab;
