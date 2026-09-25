import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';

function buildQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

// --- Dashboard ---------------------------------------------------------

export interface TopProductRow {
  product_id: string; sku: string; product_name: string; quantity_sold: string; net_sales: string;
}

export interface TopPartyOutstandingRow {
  customer_id?: string; supplier_id?: string; customer_name?: string; supplier_name?: string; outstanding: string;
}

export interface ReceivablesAging {
  current: string; days_1_30: string; days_31_60: string; days_61_90: string; days_90_plus: string; no_due_date: string;
}

export interface DashboardData {
  period: { date_from: string; date_to: string };
  sales: { net_sales: string; invoice_total: string; invoice_count: number; top_products: TopProductRow[] };
  purchase: { net_purchase: string; invoice_count: number };
  receivables: { total_outstanding: string; aging: ReceivablesAging; top_customers: TopPartyOutstandingRow[] };
  payables: { total_outstanding: string; top_suppliers: TopPartyOutstandingRow[] };
  inventory: { low_stock_item_count: number; out_of_stock_item_count: number; inventory_value: string | null };
  gst: { return_period: string; output_gst: string; input_gst: string; net_gst_position: string };
  collections: { customer_collections: string; supplier_payments: string };
  pipeline: { open_sales_orders: number; pending_delivery_challans: number; unpaid_invoices: number };
  payment_exceptions: { unallocated_payments: number; cheques_pending: number; cheques_bounced: number };
}

export async function getDashboard(period: string, dateFrom?: string, dateTo?: string): Promise<DashboardData> {
  return apiRequest<DashboardData>(`/reports/dashboard${buildQuery({ period, date_from: dateFrom, date_to: dateTo })}`);
}

export interface DashboardAlert {
  severity: 'CRITICAL' | 'WARNING' | 'INFO' | 'SUCCESS';
  category: string;
  title: string;
  description: string;
  source_module: string;
  action_view: string;
}

export async function getDashboardAlerts(): Promise<DashboardAlert[]> {
  return apiRequest<DashboardAlert[]>('/reports/dashboard/alerts');
}

export interface RecentTransaction {
  type: 'SALES_INVOICE' | 'PURCHASE_INVOICE' | 'CUSTOMER_RECEIPT' | 'SUPPLIER_PAYMENT';
  reference: string; date: string; party: string; amount: string; status: string;
}

export async function getRecentTransactions(): Promise<RecentTransaction[]> {
  return apiRequest<RecentTransaction[]>('/reports/dashboard/recent-transactions');
}

// --- Sales reports -------------------------------------------------------

export interface SalesSummary {
  gross_sales: string; discount: string; taxable_sales: string; cgst: string; sgst: string; igst: string; total_gst: string;
  invoice_total: string; invoice_count: number; sales_returns: string; sales_returns_total: string; credit_notes: string; debit_notes: string; net_sales: string;
}

export interface SalesInvoiceRegisterItem {
  invoice_id: string; invoice_number: string; invoice_date: string; customer_name: string; gstin: string | null;
  taxable_value: string; cgst: string; sgst: string; igst: string; total_gst: string; invoice_total: string;
  payment_status: string; einvoice_status: string | null; created_by: string | null;
}

export interface CustomerWiseSalesRow {
  customer_id: string; customer_name: string; invoice_count: number; gross_sales: string; discount: string;
  taxable_sales: string; gst: string; returns: string; net_sales: string; outstanding: string;
}

export interface ProductWiseSalesRow {
  product_id: string; sku: string; product_name: string; quantity_sold: string; gross_sales: string;
  discount: string; taxable_sales: string; gst: string; returns: string; net_sales: string;
}

export interface SalesReturnReportItem {
  return_id: string; return_number: string; return_date: string; customer_name: string; source_invoice_number: string;
  taxable_value: string; total_gst: string; total_return_value: string; reason: string; status: string;
}

export interface ReportParams {
  page?: number; page_size?: number; date_from?: string; date_to?: string;
  [key: string]: string | number | undefined;
}

export async function getSalesSummary(params: ReportParams = {}): Promise<SalesSummary> {
  return apiRequest<SalesSummary>(`/reports/sales/summary${buildQuery(params)}`);
}
export async function listSalesInvoiceRegister(params: ReportParams = {}): Promise<ApiList<SalesInvoiceRegisterItem>> {
  return apiRequestList<SalesInvoiceRegisterItem>(`/reports/sales/invoices${buildQuery(params)}`);
}
export async function getCustomerWiseSales(params: ReportParams = {}): Promise<ApiList<CustomerWiseSalesRow>> {
  return apiRequestList<CustomerWiseSalesRow>(`/reports/sales/customers${buildQuery(params)}`);
}
export async function getProductWiseSales(params: ReportParams = {}): Promise<ApiList<ProductWiseSalesRow>> {
  return apiRequestList<ProductWiseSalesRow>(`/reports/sales/products${buildQuery(params)}`);
}
export async function listSalesReturnReport(params: ReportParams = {}): Promise<ApiList<SalesReturnReportItem>> {
  return apiRequestList<SalesReturnReportItem>(`/reports/sales/returns${buildQuery(params)}`);
}

// --- Purchase reports ------------------------------------------------------

export interface PurchaseSummary {
  gross_purchase: string; discount: string; taxable_purchase: string; input_cgst: string; input_sgst: string;
  input_igst: string; total_input_gst: string; invoice_count: number; purchase_returns: string; net_purchase: string;
}

export interface PurchaseInvoiceRegisterItem {
  invoice_id: string; purchase_invoice_number: string; supplier_invoice_number: string | null; invoice_date: string;
  supplier_name: string; gstin: string | null; taxable_value: string; cgst: string; sgst: string; igst: string;
  total_gst: string; invoice_total: string; payment_status: string; status: string; created_by: string | null;
}

export interface SupplierWisePurchaseRow {
  supplier_id: string; supplier_name: string; invoice_count: number; gross_purchase: string; discount: string;
  taxable_purchase: string; gst: string; returns: string; net_purchase: string; outstanding: string;
}

export interface ProductWisePurchaseRow {
  product_id: string; sku: string; product_name: string; quantity_purchased: string; purchase_value: string;
  discount: string; taxable_value: string; gst: string; returns: string; net_purchase: string;
}

export interface PurchaseReturnReportItem {
  return_id: string; return_number: string; return_date: string; supplier_name: string; source_purchase_invoice_number: string;
  taxable_value: string; total_gst: string; total_return_value: string; reason: string; status: string;
}

export async function getPurchaseSummary(params: ReportParams = {}): Promise<PurchaseSummary> {
  return apiRequest<PurchaseSummary>(`/reports/purchase/summary${buildQuery(params)}`);
}
export async function listPurchaseInvoiceRegister(params: ReportParams = {}): Promise<ApiList<PurchaseInvoiceRegisterItem>> {
  return apiRequestList<PurchaseInvoiceRegisterItem>(`/reports/purchase/invoices${buildQuery(params)}`);
}
export async function getSupplierWisePurchase(params: ReportParams = {}): Promise<ApiList<SupplierWisePurchaseRow>> {
  return apiRequestList<SupplierWisePurchaseRow>(`/reports/purchase/suppliers${buildQuery(params)}`);
}
export async function getProductWisePurchase(params: ReportParams = {}): Promise<ApiList<ProductWisePurchaseRow>> {
  return apiRequestList<ProductWisePurchaseRow>(`/reports/purchase/products${buildQuery(params)}`);
}
export async function listPurchaseReturnReport(params: ReportParams = {}): Promise<ApiList<PurchaseReturnReportItem>> {
  return apiRequestList<PurchaseReturnReportItem>(`/reports/purchase/returns${buildQuery(params)}`);
}

// --- Inventory reports -------------------------------------------------------

export interface CurrentStockRow {
  product_id: string; sku: string; product_name: string; uom: string; current_quantity: string; reorder_level: string; stock_status: string;
}

export interface StockMovementRow {
  date: string; product_sku: string; product_name: string; movement_type: string; quantity_in: string; quantity_out: string;
  source_type: string; source_id: string; created_by: string | null;
}

export async function getCurrentStock(params: ReportParams = {}): Promise<ApiList<CurrentStockRow>> {
  return apiRequestList<CurrentStockRow>(`/reports/inventory/current-stock${buildQuery(params)}`);
}
export async function listStockMovements(params: ReportParams = {}): Promise<ApiList<StockMovementRow>> {
  return apiRequestList<StockMovementRow>(`/reports/inventory/movements${buildQuery(params)}`);
}
export async function getProductStockHistory(productId: string, dateFrom?: string, dateTo?: string): Promise<{ opening_balance: string; movements: any[] }> {
  return apiRequest(`/reports/inventory/history${buildQuery({ product_id: productId, date_from: dateFrom, date_to: dateTo })}`);
}

// --- Receivables / Payables ----------------------------------------------

export interface OutstandingItem {
  customer_id?: string; customer_name?: string; supplier_id?: string; supplier_name?: string; invoice_id: string;
  invoice_number: string; invoice_date: string; due_date: string | null; invoice_amount: string; paid_amount: string;
  outstanding: string; payment_status: string;
}

export interface OutstandingSummary {
  total_receivables?: string; total_payables?: string; fully_paid_count: number; partially_paid_count: number; unpaid_count: number;
}

export interface OutstandingResponse extends ApiList<OutstandingItem> {
  summary: OutstandingSummary;
}

// `apiRequestList` returns the raw payload cast to `ApiList<T>`; the
// reports envelope additionally carries a `summary` object alongside
// `data`/`pagination` — present on the real JSON at runtime, just not
// part of `ApiList<T>`'s own declared shape, hence the widening cast.
export async function getReceivables(params: ReportParams = {}): Promise<OutstandingResponse> {
  return (await apiRequestList<OutstandingItem>(`/reports/receivables${buildQuery(params)}`)) as unknown as OutstandingResponse;
}
export async function getPayables(params: ReportParams = {}): Promise<OutstandingResponse> {
  return (await apiRequestList<OutstandingItem>(`/reports/payables${buildQuery(params)}`)) as unknown as OutstandingResponse;
}

// --- Payments --------------------------------------------------------------

export interface PaymentRegisterItem {
  payment_id: string; payment_number: string; payment_date: string; party_type: string; party_name: string | null;
  payment_method: string; amount: string; allocated_amount: string; unallocated_amount: string; status: string; reference_number: string | null;
}

export interface PaymentMethodSummaryRow {
  payment_method: string; transaction_count: number; amount: string;
}

export interface ChequeReportRow {
  cheque_number: string | null; payment_number: string; party_name: string | null; amount: string; cheque_date: string | null;
  bank: string | null; cheque_status: string | null; cleared_date: string | null;
}

export async function listPayments(params: ReportParams = {}): Promise<ApiList<PaymentRegisterItem>> {
  return apiRequestList<PaymentRegisterItem>(`/reports/payments${buildQuery(params)}`);
}
export async function getPaymentMethodSummary(params: ReportParams = {}): Promise<PaymentMethodSummaryRow[]> {
  return apiRequest<PaymentMethodSummaryRow[]>(`/reports/payments/method-summary${buildQuery(params)}`);
}
export async function listCheques(params: ReportParams = {}): Promise<ApiList<ChequeReportRow>> {
  return apiRequestList<ChequeReportRow>(`/reports/payments/cheques${buildQuery(params)}`);
}

// --- Accounting --------------------------------------------------------------

export interface GeneralLedgerEntry {
  date: string; journal_number: string; source_type: string; source_id: string; source_number: string | null;
  description: string | null; debit: string; credit: string; running_balance: string;
}

export interface GeneralLedgerResponse {
  account_id: string; account_code: string; account_name: string; account_type: string;
  opening_balance: string; closing_balance: string; entries: GeneralLedgerEntry[];
}

export interface TrialBalanceAccount {
  account_id: string; account_code: string; account_name: string; account_type: string; debit: string; credit: string;
}

export interface TrialBalanceResponse {
  as_of_date: string; is_balanced: boolean; total_debit: string; total_credit: string; accounts: TrialBalanceAccount[];
}

export interface AccountBalanceRow {
  account_id: string; account_code: string; account_name: string; net_balance: string;
}

export interface ProfitLossResponse {
  period: { date_from: string | null; date_to: string };
  revenue_accounts: AccountBalanceRow[]; total_revenue: string;
  cogs_accounts: AccountBalanceRow[]; total_cogs: string; gross_profit: string;
  expense_accounts: AccountBalanceRow[]; total_expenses: string; net_profit: string;
}

export interface BalanceSheetResponse {
  as_of_date: string;
  asset_accounts: AccountBalanceRow[]; total_assets: string;
  liability_accounts: AccountBalanceRow[]; total_liabilities: string;
  equity_accounts: AccountBalanceRow[]; total_equity_posted: string;
  current_period_earnings: string; total_equity: string; is_balanced: boolean; difference: string;
}

export async function getGeneralLedger(accountId: string, dateFrom?: string, dateTo?: string): Promise<GeneralLedgerResponse> {
  return apiRequest<GeneralLedgerResponse>(`/reports/accounting/general-ledger${buildQuery({ account_id: accountId, date_from: dateFrom, date_to: dateTo })}`);
}
export async function getTrialBalance(dateTo?: string): Promise<TrialBalanceResponse> {
  return apiRequest<TrialBalanceResponse>(`/reports/accounting/trial-balance${buildQuery({ date_to: dateTo })}`);
}
export async function getProfitAndLoss(dateFrom?: string, dateTo?: string): Promise<ProfitLossResponse> {
  return apiRequest<ProfitLossResponse>(`/reports/accounting/profit-loss${buildQuery({ date_from: dateFrom, date_to: dateTo })}`);
}
export async function getBalanceSheet(asOfDate?: string): Promise<BalanceSheetResponse> {
  return apiRequest<BalanceSheetResponse>(`/reports/accounting/balance-sheet${buildQuery({ as_of_date: asOfDate })}`);
}

// --- GST reporting views -----------------------------------------------------

export async function getGstReportSummary(returnPeriod: string): Promise<any> {
  return apiRequest(`/reports/gst/summary${buildQuery({ return_period: returnPeriod })}`);
}
export async function listGstReportTransactions(returnPeriod: string, params: ReportParams = {}): Promise<ApiList<any>> {
  return apiRequestList(`/reports/gst/transactions${buildQuery({ return_period: returnPeriod, ...params })}`);
}
export async function getGstHsnSummary(returnPeriod: string): Promise<any[]> {
  return apiRequest(`/reports/gst/hsn-summary${buildQuery({ return_period: returnPeriod })}`);
}
