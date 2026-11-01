import { apiRequestWithMeta } from './client';

function buildQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

export interface AnalysisQueryParams {
  period: string;
  dateFrom?: string;
  dateTo?: string;
  compare?: string;
  compareFrom?: string;
  compareTo?: string;
}

function queryFor(params: AnalysisQueryParams): string {
  return buildQuery({
    period: params.period, date_from: params.dateFrom, date_to: params.dateTo,
    compare: params.compare, compare_from: params.compareFrom, compare_to: params.compareTo,
  });
}

export interface ResolvedPeriod {
  date_from: string; date_to: string; compare_from: string | null; compare_to: string | null;
}

export interface Kpi {
  current: string; previous: string | null; change: string | null; change_percent: string | null;
}

export interface UnavailableMetric {
  value: null; reason: string;
}

export interface TrendPoint { date: string; value: string }

export interface TopProductRow {
  product_id: string; sku: string; product_name: string; quantity_sold: string;
  gross_sales: string; discount: string; taxable_sales: string; gst: string; returns: string; net_sales: string;
}

export interface TopCustomerRow {
  customer_id: string; customer_name: string; invoice_count: number; gross_sales: string;
  discount: string; taxable_sales: string; gst: string; returns: string; net_sales: string; outstanding: string;
}

export interface AgingBuckets {
  current: string; days_1_30: string; days_31_60: string; days_61_90: string; days_90_plus: string; no_due_date: string;
}

export interface OverviewData {
  kpis: {
    net_sales: Kpi; purchase_value: Kpi; gross_profit: UnavailableMetric; average_invoice_value: Kpi;
    customer_outstanding: Kpi; supplier_payables: Kpi; inventory_value: UnavailableMetric;
  };
  sales_trend: TrendPoint[];
  purchase_trend: TrendPoint[];
  top_products: TopProductRow[];
  top_customers: TopCustomerRow[];
  receivables_aging: AgingBuckets;
}

export async function fetchAnalysisOverview(params: AnalysisQueryParams): Promise<{ data: OverviewData; period: ResolvedPeriod }> {
  const envelope = await apiRequestWithMeta<OverviewData, { period: ResolvedPeriod }>(`/analysis/overview${queryFor(params)}`);
  return { data: envelope.data, period: envelope.meta.period };
}

export interface SalesAnalysisTableRow extends TopProductRow {
  contribution_percent: string | null;
}

export interface SalesAnalysisData {
  kpis: {
    gross_sales: Kpi; discounts: Kpi; sales_returns: Kpi; net_sales: Kpi;
    invoice_count: Kpi; average_invoice_value: Kpi; quantity_sold: Kpi;
  };
  sales_trend: TrendPoint[];
  top_products: TopProductRow[];
  top_customers: TopCustomerRow[];
  table: SalesAnalysisTableRow[];
}

export async function fetchSalesAnalysis(params: AnalysisQueryParams): Promise<{ data: SalesAnalysisData; period: ResolvedPeriod }> {
  const envelope = await apiRequestWithMeta<SalesAnalysisData, { period: ResolvedPeriod }>(`/analysis/sales${queryFor(params)}`);
  return { data: envelope.data, period: envelope.meta.period };
}

export interface SalesByUserRow {
  user_id: string | null; user_name: string; invoice_count: number; total_amount: string;
}

// Owner/Manager get every staff member's row; a Salesperson gets only
// their own (enforced server-side, not a frontend filter — see
// backend/app/api/v1/analysis.py's get_sales_by_user).
export async function fetchSalesByUser(params: Pick<AnalysisQueryParams, 'period' | 'dateFrom' | 'dateTo'>): Promise<{ data: SalesByUserRow[]; period: ResolvedPeriod }> {
  const envelope = await apiRequestWithMeta<SalesByUserRow[], { period: ResolvedPeriod }>(`/analysis/sales-by-user${queryFor(params)}`);
  return { data: envelope.data, period: envelope.meta.period };
}

export interface ProductAnalysisRow extends TopProductRow {
  previous_net_sales: string | null; change_percent: string | null;
  current_stock: string | null; stock_status: string | null; gross_margin: UnavailableMetric;
}

export interface ProductAnalysisData {
  top_10: ProductAnalysisRow[];
  bottom_10: ProductAnalysisRow[];
  table: ProductAnalysisRow[];
  total_products_with_sales: number;
  sales_trend: TrendPoint[];
}

export async function fetchProductAnalysis(params: AnalysisQueryParams): Promise<{ data: ProductAnalysisData; period: ResolvedPeriod }> {
  const envelope = await apiRequestWithMeta<ProductAnalysisData, { period: ResolvedPeriod }>(`/analysis/products${queryFor(params)}`);
  return { data: envelope.data, period: envelope.meta.period };
}

export interface CustomerAnalysisRow extends TopCustomerRow {
  average_invoice_value: string; overdue_amount: string; previous_net_sales: string | null; change_percent: string | null;
}

export interface CustomerAnalysisData {
  kpis: { sales_to_customers: Kpi; active_customers: number; average_sales_per_customer: string };
  top_customers: CustomerAnalysisRow[];
  receivables_aging: AgingBuckets;
  table: CustomerAnalysisRow[];
  total_customers_with_sales: number;
}

export async function fetchCustomerAnalysis(params: AnalysisQueryParams): Promise<{ data: CustomerAnalysisData; period: ResolvedPeriod }> {
  const envelope = await apiRequestWithMeta<CustomerAnalysisData, { period: ResolvedPeriod }>(`/analysis/customers${queryFor(params)}`);
  return { data: envelope.data, period: envelope.meta.period };
}

export interface TopSupplierRow {
  supplier_id: string; supplier_name: string; invoice_count: number; gross_purchase: string;
  discount: string; taxable_purchase: string; gst: string; returns: string; net_purchase: string; outstanding: string;
}

export interface TopPurchaseProductRow {
  product_id: string; sku: string; product_name: string; quantity_purchased: string;
  purchase_value: string; discount: string; taxable_value: string; gst: string; returns: string; net_purchase: string;
}

export interface PurchaseAnalysisData {
  kpis: { gross_purchase: Kpi; purchase_returns: Kpi; net_purchase: Kpi; invoice_count: Kpi };
  purchase_trend: TrendPoint[];
  top_suppliers: TopSupplierRow[];
  top_products: TopPurchaseProductRow[];
}

export async function fetchPurchaseAnalysis(params: AnalysisQueryParams): Promise<{ data: PurchaseAnalysisData; period: ResolvedPeriod }> {
  const envelope = await apiRequestWithMeta<PurchaseAnalysisData, { period: ResolvedPeriod }>(`/analysis/purchases${queryFor(params)}`);
  return { data: envelope.data, period: envelope.meta.period };
}

export interface InventoryAnalysisRow {
  product_id: string; sku: string; product_name: string; uom: string; current_quantity: string;
  reorder_level: string; stock_status: string; quantity_sold_in_period: string;
}

export interface InventoryAnalysisData {
  kpis: {
    total_stock_quantity: string; low_stock_items: number; out_of_stock_items: number;
    inventory_value: UnavailableMetric; stock_turnover: UnavailableMetric;
  };
  fast_moving: InventoryAnalysisRow[];
  slow_moving: InventoryAnalysisRow[];
  table: InventoryAnalysisRow[];
  total_products: number;
}

export async function fetchInventoryAnalysis(params: Pick<AnalysisQueryParams, 'period' | 'dateFrom' | 'dateTo'>): Promise<{ data: InventoryAnalysisData; period: ResolvedPeriod }> {
  const envelope = await apiRequestWithMeta<InventoryAnalysisData, { period: ResolvedPeriod }>(`/analysis/inventory${queryFor(params)}`);
  return { data: envelope.data, period: envelope.meta.period };
}
