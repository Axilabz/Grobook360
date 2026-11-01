import React, { useEffect, useState } from 'react';
import { useToast } from '../../context/ToastContext';
import { useNavigation } from '../../context/NavigationContext';
import { ApiError } from '../../api/client';
import { fetchInventoryAnalysis, AnalysisQueryParams, InventoryAnalysisData } from '../../api/analysis';
import LoadingState from '../../shared/LoadingState';
import EmptyState from '../../shared/EmptyState';
import KpiCard from '../../shared/charts/KpiCard';
import RankingBarChart from '../../shared/charts/RankingBarChart';
import InsightsPanel, { Insight } from './InsightsPanel';
import ExportButton from '../../shared/ExportButton';
import { formatQuantity } from '../../shared/formatters';

interface Props { params: AnalysisQueryParams; refreshKey: number }

const STOCK_BADGE: Record<string, string> = {
  IN_STOCK: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  LOW_STOCK: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  OUT_OF_STOCK: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
};

const InventoryAnalysisTab: React.FC<Props> = ({ params, refreshKey }) => {
  const { showToast } = useToast();
  const { navigate } = useNavigation();
  const [data, setData] = useState<InventoryAnalysisData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    fetchInventoryAnalysis(params)
      .then((res) => { if (!cancelled) setData(res.data); })
      .catch((err) => {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : 'Failed to load inventory analysis.';
        setError(msg);
        showToast(msg, 'error');
      })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.period, params.dateFrom, params.dateTo, refreshKey]);

  if (isLoading) return <LoadingState label="Loading inventory analysis…" />;
  if (error) return <EmptyState title="Couldn't load this analysis" description={error} />;
  if (!data) return null;

  const insights: Insight[] = [];
  if (data.kpis.low_stock_items > 0) {
    insights.push({ text: `${data.kpis.low_stock_items} product(s) are low on stock.`, severity: 'negative', onInvestigate: () => navigate('Inventory') });
  }
  if (data.kpis.out_of_stock_items > 0) {
    insights.push({ text: `${data.kpis.out_of_stock_items} product(s) are out of stock.`, severity: 'negative', onInvestigate: () => navigate('Inventory') });
  }
  const noMovement = data.table.filter((r) => Number(r.quantity_sold_in_period) === 0 && Number(r.current_quantity) > 0);
  if (noMovement.length > 0) {
    insights.push({ text: `${noMovement.length} product(s) in stock had no sales activity in this period.`, severity: 'neutral' });
  }
  const highStockLowSales = data.slow_moving.filter((r) => Number(r.current_quantity) > 500);
  if (highStockLowSales.length > 0) {
    insights.push({ text: `${highStockLowSales[0].product_name} has high stock (${formatQuantity(highStockLowSales[0].current_quantity)}) relative to recent sales — may warrant review.`, severity: 'neutral', onInvestigate: () => navigate('Products', { id: highStockLowSales[0].product_id }) });
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4 shadow-sm">
          <span className="text-[12px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Total Stock Qty</span>
          <p className="text-[22px] font-bold text-gray-900 dark:text-gray-100 mt-2">{formatQuantity(data.kpis.total_stock_quantity)}</p>
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4 shadow-sm cursor-pointer" onClick={() => navigate('Inventory')}>
          <span className="text-[12px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Low Stock Items</span>
          <p className="text-[22px] font-bold text-amber-600 dark:text-amber-400 mt-2">{data.kpis.low_stock_items}</p>
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4 shadow-sm cursor-pointer" onClick={() => navigate('Inventory')}>
          <span className="text-[12px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Out of Stock Items</span>
          <p className="text-[22px] font-bold text-red-600 dark:text-red-400 mt-2">{data.kpis.out_of_stock_items}</p>
        </div>
        <KpiCard title="Inventory Value" kpi={data.kpis.inventory_value} />
        <KpiCard title="Stock Turnover" kpi={data.kpis.stock_turnover} />
      </div>

      <InsightsPanel insights={insights} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Fast-Moving Products</h3>
          <RankingBarChart
            data={data.fast_moving.map((p) => ({ id: p.product_id, label: p.product_name, value: Number(p.quantity_sold_in_period) }))}
            color="#16a34a"
            onBarClick={(row) => navigate('Products', { id: row.id })}
          />
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Slow-Moving Products (high stock, low recent sales)</h3>
          <RankingBarChart
            data={data.slow_moving.map((p) => ({ id: p.product_id, label: p.product_name, value: Number(p.current_quantity) }))}
            color="#ef4444"
            onBarClick={(row) => navigate('Products', { id: row.id })}
          />
        </div>
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between p-5 pb-0">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200">Inventory Table</h3>
          <ExportButton resource="analysis_inventory" exportPermission="reports.export" page={1} pageSize={1000} totalItems={data.table.length} />
        </div>
        <div className="overflow-x-auto mt-3">
          <table className="w-full text-[13px]">
            <thead className="bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400 text-[11px] uppercase">
              <tr>
                <th className="text-left px-5 py-2.5">Product</th>
                <th className="text-right px-5 py-2.5">Current Stock</th>
                <th className="text-center px-5 py-2.5">Status</th>
                <th className="text-right px-5 py-2.5">Qty Sold (Period)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {data.table.map((row) => (
                <tr key={row.product_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer" onClick={() => navigate('Products', { id: row.product_id })}>
                  <td className="px-5 py-2.5 text-gray-800 dark:text-gray-200">{row.product_name} <span className="text-gray-400 text-[11px]">({row.sku})</span></td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{formatQuantity(row.current_quantity)} {row.uom}</td>
                  <td className="px-5 py-2.5 text-center">
                    <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${STOCK_BADGE[row.stock_status] || ''}`}>{row.stock_status.replace('_', ' ')}</span>
                  </td>
                  <td className="px-5 py-2.5 text-right text-gray-600 dark:text-gray-300">{formatQuantity(row.quantity_sold_in_period)}</td>
                </tr>
              ))}
              {data.table.length === 0 && (
                <tr><td colSpan={4} className="px-5 py-8 text-center text-gray-400">No products found.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default InventoryAnalysisTab;
