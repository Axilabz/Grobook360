import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';

export interface GstTransactionLineItem {
  line_no: number;
  hsn_code: string | null;
  quantity: string;
  unit_price: string;
  gst_rate: string;
  taxable_value: string;
  cgst_amount: string;
  sgst_amount: string;
  igst_amount: string;
  cess_amount: string;
  line_total: string;
}

export interface GstTransactionListItem {
  id: string;
  source_type: string;
  source_id: string;
  source_number: string | null;
  event_type: 'ORIGINAL' | 'REVERSAL';
  direction: 'OUTWARD' | 'INWARD';
  classification: 'B2B' | 'B2C';
  party_name: string | null;
  party_gstin: string | null;
  place_of_supply_state_code: string | null;
  document_date: string;
  financial_year_label: string;
  return_period: string;
  taxable_value: string;
  cgst_amount: string;
  sgst_amount: string;
  igst_amount: string;
  cess_amount: string;
  total_gst: string;
  total_amount: string;
}

export interface GstTransactionDetail extends GstTransactionListItem {
  lines: GstTransactionLineItem[];
}

export interface GstTotals {
  taxable_value: string;
  cgst: string;
  sgst: string;
  igst: string;
  cess: string;
  total_gst: string;
}

export interface GstrBucket {
  count: number;
  totals: GstTotals;
  transactions: GstTransactionListItem[];
}

export interface HsnSummaryEntry {
  hsn_code: string;
  taxable_value: string;
  cgst: string;
  sgst: string;
  igst: string;
  cess: string;
  quantity: string;
}

export interface Gstr1Dataset {
  return_period: string;
  b2b: GstrBucket;
  b2c: GstrBucket;
  credit_notes: GstrBucket;
  debit_notes: GstrBucket;
  hsn_summary: HsnSummaryEntry[];
}

export interface Gstr3bDataset {
  return_period: string;
  outward_taxable_supplies: GstTotals;
  output_cgst: string;
  output_sgst: string;
  output_igst: string;
  inward_supplies: GstTotals;
  input_tax_credit_cgst: string;
  input_tax_credit_sgst: string;
  input_tax_credit_igst: string;
  net_gst_payable: string;
}

export interface ValidationIssueItem {
  code: string;
  severity: 'ERROR' | 'WARNING' | 'INFO';
  message: string;
  source_type: string;
  source_id: string;
  field: string;
  suggested_action: string;
}

export interface ValidationResult {
  return_period: string;
  is_valid: boolean;
  error_count: number;
  warning_count: number;
  issues: ValidationIssueItem[];
}

export interface ReconciliationResult {
  return_period: string;
  gst_engine_output_gst: string;
  accounting_output_gst: string;
  output_gst_difference: string;
  gst_engine_input_gst: string;
  accounting_input_gst: string;
  input_gst_difference: string;
}

export interface GstDashboard {
  return_period: string;
  output_gst: string;
  input_gst: string;
  net_gst_position: string;
  b2b_sales: string;
  b2c_sales: string;
  credit_notes: string;
  debit_notes: string;
  validation_error_count: number;
}

export interface ListGstTransactionsParams {
  page?: number;
  page_size?: number;
  return_period?: string;
  source_type?: string;
  classification?: string;
  party_gstin?: string;
  direction?: string;
  [key: string]: string | number | undefined;
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

export async function listGstTransactions(params: ListGstTransactionsParams): Promise<ApiList<GstTransactionListItem>> {
  return apiRequestList<GstTransactionListItem>(`/gst/transactions${buildQuery(params)}`);
}

export async function getGstTransaction(transactionId: string): Promise<GstTransactionDetail> {
  return apiRequest<GstTransactionDetail>(`/gst/transactions/${transactionId}`);
}

export async function getGstDashboard(returnPeriod: string): Promise<GstDashboard> {
  return apiRequest<GstDashboard>(`/gst/dashboard${buildQuery({ return_period: returnPeriod })}`);
}

export async function getGstr1(returnPeriod: string): Promise<Gstr1Dataset> {
  return apiRequest<Gstr1Dataset>(`/gst/returns/gstr1${buildQuery({ return_period: returnPeriod })}`);
}

export async function validateGstr1(returnPeriod: string): Promise<ValidationResult> {
  return apiRequest<ValidationResult>(`/gst/returns/gstr1/validate${buildQuery({ return_period: returnPeriod })}`, { method: 'POST', body: {} });
}

export async function getGstr3b(returnPeriod: string): Promise<Gstr3bDataset> {
  return apiRequest<Gstr3bDataset>(`/gst/returns/gstr3b${buildQuery({ return_period: returnPeriod })}`);
}

export async function validateGstr3b(returnPeriod: string): Promise<ValidationResult> {
  return apiRequest<ValidationResult>(`/gst/returns/gstr3b/validate${buildQuery({ return_period: returnPeriod })}`, { method: 'POST', body: {} });
}

export async function getGstReconciliation(returnPeriod: string): Promise<ReconciliationResult> {
  return apiRequest<ReconciliationResult>(`/gst/reconciliation${buildQuery({ return_period: returnPeriod })}`);
}
