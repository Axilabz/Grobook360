import React, { useEffect, useState } from 'react';
import { useToast } from '../../context/ToastContext';
import { useNavigation } from '../../context/NavigationContext';
import { ApiError } from '../../api/client';
import { fetchAnalysisOverview, AnalysisQueryParams, OverviewData } from '../../api/analysis';
import LoadingState from '../../shared/LoadingState';
import EmptyState from '../../shared/EmptyState';
import KpiCard from '../../shared/charts/KpiCard';
import TrendLineChart from '../../shared/charts/TrendLineChart';
import RankingBarChart from '../../shared/charts/RankingBarChart';
import AgingDonutChart from '../../shared/charts/AgingDonutChart';
import InsightsPanel, { Insight } from './InsightsPanel';

interface Props { params: AnalysisQueryParams; refreshKey: number }

const OverviewAnalysisTab: React.FC<Props> = ({ params, refreshKey }) => {
  const { showToast } = useToast();
  const { navigate } = useNavigation();
  const [data, setData] = useState<OverviewData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    fetchAnalysisOverview(params)
      .then((res) => { if (!cancelled) setData(res.data); })
      .catch((err) => {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : 'Failed to load overview analysis.';
        setError(msg);
        showToast(msg, 'error');
      })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.period, params.dateFrom, params.dateTo, params.compare, params.compareFrom, params.compareTo, refreshKey]);

  if (isLoading) return <LoadingState label="Loading overview…" />;
  if (error) return <EmptyState title="Couldn't load this analysis" description={error} />;
  if (!data) return null;

  const insights: Insight[] = [];
  if (data.kpis.net_sales.change_percent !== null) {
    const pct = Number(data.kpis.net_sales.change_percent);
    insights.push({
      text: `Net Sales ${pct >= 0 ? 'grew' : 'declined'} ${Math.abs(pct).toFixed(1)}% compared with the previous period.`,
      detail: `Current ₹${data.kpis.net_sales.current} vs previous ₹${data.kpis.net_sales.previous}.`,
      severity: pct >= 0 ? 'positive' : 'negative',
    });
  }
  if (data.top_products.length > 0) {
    const top = data.top_products[0];
    const totalNetSales = data.top_products.reduce((sum, p) => sum + Number(p.net_sales), 0);
    const contribution = totalNetSales > 0 ? (Number(top.net_sales) / totalNetSales) * 100 : 0;
    insights.push({ text: `${top.product_name} is the top product, contributing ${contribution.toFixed(1)}% of the top-5 net sales shown.`, severity: 'neutral' });
  }
  const overdue = Number(data.receivables_aging.days_61_90) + Number(data.receivables_aging.days_90_plus);
  if (overdue > 0) {
    insights.push({ text: `₹${overdue.toLocaleString('en-IN')} in receivables is overdue more than 60 days.`, severity: 'negative', onInvestigate: () => navigate('Customer Receipts') });
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard title="Net Sales" kpi={data.kpis.net_sales} onClick={() => navigate('Sales Invoices')} definition="Taxable Sales (posted invoices) - Sales Returns - Credit Notes + Debit Notes" />
        <KpiCard title="Purchase Value" kpi={data.kpis.purchase_value} onClick={() => navigate('Purchase Invoices')} definition="Taxable Purchase (posted invoices) - Purchase Returns" />
        <KpiCard title="Avg Invoice Value" kpi={data.kpis.average_invoice_value} definition="Total invoice value ÷ invoice count for the selected period" />
        <KpiCard title="Gross Profit" kpi={data.kpis.gross_profit} />
        <KpiCard title="Customer Outstanding" kpi={data.kpis.customer_outstanding} onClick={() => navigate('Customer Receipts')} definition="grand_total - paid_amount across POSTED sales invoices" />
        <KpiCard title="Supplier Payables" kpi={data.kpis.supplier_payables} onClick={() => navigate('Supplier Payments')} definition="grand_total - paid_amount across POSTED purchase invoices" />
        <KpiCard title="Inventory Value" kpi={data.kpis.inventory_value} />
      </div>

      <InsightsPanel insights={insights} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Sales Trend</h3>
          <TrendLineChart series={[{ name: 'Net Sales', color: '#0066ff', points: data.sales_trend }]} />
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Purchase Trend</h3>
          <TrendLineChart series={[{ name: 'Net Purchase', color: '#f97316', points: data.purchase_trend }]} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Top Products by Sales</h3>
          <RankingBarChart
            data={data.top_products.map((p) => ({ id: p.product_id, label: p.product_name, value: Number(p.net_sales) }))}
            onBarClick={(row) => navigate('Products', { id: row.id })}
          />
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Top Customers by Sales</h3>
          <RankingBarChart
            data={data.top_customers.map((c) => ({ id: c.customer_id, label: c.customer_name, value: Number(c.net_sales) }))}
            color="#16a34a"
            onBarClick={(row) => navigate('Customers', { id: row.id })}
          />
        </div>
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5 shadow-sm">
          <h3 className="text-[14px] font-semibold text-gray-700 dark:text-gray-200 mb-3">Receivables Aging</h3>
          <AgingDonutChart aging={data.receivables_aging} />
        </div>
      </div>
    </div>
  );
};

export default OverviewAnalysisTab;
