import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';
import type { UnitRef } from './salesEstimates';

export interface SalesInvoiceLine {
  id: string;
  line_no: number;
  product_id: string | null;
  description: string | null;
  hsn_code: string | null;
  quantity: string;
  uom: UnitRef;
  unit_price: string;
  discount_amount: string;
  taxable_amount: string;
  gst_rate: string;
  cgst_amount: string;
  sgst_amount: string;
  igst_amount: string;
  line_total: string;
  source_delivery_challan_line_id: string | null;
}

export interface SalesInvoiceListItem {
  id: string;
  invoice_number: string;
  invoice_date: string;
  invoice_type: 'DIRECT_SALES_INVOICE' | 'DELIVERY_CHALLAN_SALES_INVOICE';
  customer_id: string;
  customer_name: string;
  status: string;
  source_delivery_challan_id: string | null;
  source_delivery_challan_number: string | null;
  grand_total: string;
  tax_total: string;
  paid_amount: string;
  payment_status: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface SalesInvoiceDetail extends SalesInvoiceListItem {
  customer_gstin: string | null;
  customer_type: string;
  billing_address: string | null;
  shipping_address: string | null;
  place_of_supply_state_code: string | null;
  source_sales_order_id: string | null;
  subtotal: string;
  discount_total: string;
  taxable_total: string;
  cgst_total: string;
  sgst_total: string;
  igst_total: string;
  notes: string | null;
  accounting_posting_reference: string | null;
  gst_transaction_reference: string | null;
  irn: string | null;
  ack_number: string | null;
  ack_date: string | null;
  einvoice_status: string | null;
  lines: SalesInvoiceLine[];
}

export interface DirectInvoiceLineInput {
  product_id: string;
  quantity: string;
  uom_id: string;
  unit_price: string;
  discount_percent?: string | null;
  discount_amount?: string | null;
}

export interface ListSalesInvoicesParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  invoice_type?: string;
  customer_id?: string;
  date_from?: string;
  date_to?: string;
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

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export async function listSalesInvoices(params: ListSalesInvoicesParams): Promise<ApiList<SalesInvoiceListItem>> {
  return apiRequestList<SalesInvoiceListItem>(`/sales/invoices${buildQuery(params)}`);
}

export async function getSalesInvoice(invoiceId: string): Promise<SalesInvoiceDetail> {
  return apiRequest<SalesInvoiceDetail>(`/sales/invoices/${invoiceId}`);
}

export interface CreateDirectInvoicePayload {
  customer_id: string;
  invoice_date?: string | null;
  shipping_address?: string | null;
  notes?: string | null;
  lines: DirectInvoiceLineInput[];
}

export async function createDirectInvoice(payload: CreateDirectInvoicePayload): Promise<SalesInvoiceDetail> {
  return apiRequest<SalesInvoiceDetail>('/sales/invoices', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export interface UpdateSalesInvoicePayload {
  invoice_date?: string | null;
  shipping_address?: string | null;
  notes?: string | null;
  lines?: DirectInvoiceLineInput[];
  expected_row_version: number;
}

export async function updateSalesInvoice(invoiceId: string, payload: UpdateSalesInvoicePayload): Promise<SalesInvoiceDetail> {
  return apiRequest<SalesInvoiceDetail>(`/sales/invoices/${invoiceId}`, { method: 'PATCH', body: payload });
}

export async function postSalesInvoice(invoiceId: string, expectedRowVersion: number): Promise<SalesInvoiceDetail> {
  return apiRequest<SalesInvoiceDetail>(`/sales/invoices/${invoiceId}/post`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function cancelSalesInvoice(invoiceId: string, expectedRowVersion: number): Promise<SalesInvoiceDetail> {
  return apiRequest<SalesInvoiceDetail>(`/sales/invoices/${invoiceId}/cancel`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

// --- Invoice eligibility + creation from Delivery Challan ---

export interface InvoiceEligibilityLine {
  source_delivery_challan_line_id: string;
  product_id: string | null;
  description: string | null;
  hsn_code: string | null;
  uom: UnitRef;
  delivered_quantity: string;
  invoiced_quantity: string;
  invoiceable_quantity: string;
  unit_price: string;
  gst_rate: string;
}

export interface InvoiceEligibility {
  source_delivery_challan_id: string;
  source_delivery_challan_number: string;
  source_delivery_challan_status: string;
  customer_id: string;
  customer_name: string;
  billing_address: string | null;
  shipping_address: string | null;
  place_of_supply_state_code: string | null;
  lines: InvoiceEligibilityLine[];
}

export async function getInvoiceEligibility(challanId: string): Promise<InvoiceEligibility> {
  return apiRequest<InvoiceEligibility>(`/sales/delivery-challans/${challanId}/invoice-eligibility`);
}

export interface InvoiceFromChallanLineInput {
  source_delivery_challan_line_id: string;
  quantity: string;
}

export interface CreateInvoiceFromChallanPayload {
  invoice_date?: string | null;
  notes?: string | null;
  lines: InvoiceFromChallanLineInput[];
}

export async function createInvoiceFromChallan(
  challanId: string,
  payload: CreateInvoiceFromChallanPayload
): Promise<SalesInvoiceDetail> {
  return apiRequest<SalesInvoiceDetail>(`/sales/delivery-challans/${challanId}/create-invoice`, {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

// --- Return eligibility (PROMPT-016) ---

export interface ReturnEligibilityLine {
  source_invoice_line_id: string;
  product_id: string | null;
  description: string | null;
  hsn_code: string | null;
  uom: UnitRef;
  original_quantity: string;
  previously_returned_quantity: string;
  returnable_quantity: string;
  unit_price: string;
  gst_rate: string;
}

export interface ReturnEligibility {
  source_invoice_id: string;
  source_invoice_number: string;
  source_invoice_status: string;
  customer_id: string;
  customer_name: string;
  customer_gstin: string | null;
  billing_address: string | null;
  shipping_address: string | null;
  place_of_supply_state_code: string | null;
  lines: ReturnEligibilityLine[];
}

export async function getReturnEligibility(invoiceId: string): Promise<ReturnEligibility> {
  return apiRequest<ReturnEligibility>(`/sales/invoices/${invoiceId}/return-eligibility`);
}

// --- Adjustment eligibility (PROMPT-017 — Credit/Debit Note) ---

export interface AdjustmentEligibilityLine {
  source_invoice_line_id: string;
  product_id: string | null;
  description: string | null;
  hsn_code: string | null;
  uom: UnitRef;
  original_quantity: string;
  previously_credited_quantity: string;
  previously_debited_quantity: string;
  creditable_quantity: string;
  debitable_quantity: string;
  unit_price: string;
  gst_rate: string;
}

export interface AdjustmentEligibility {
  source_invoice_id: string;
  source_invoice_number: string;
  source_invoice_status: string;
  customer_id: string;
  customer_name: string;
  customer_gstin: string | null;
  billing_address: string | null;
  shipping_address: string | null;
  place_of_supply_state_code: string | null;
  lines: AdjustmentEligibilityLine[];
}

export async function getAdjustmentEligibility(invoiceId: string): Promise<AdjustmentEligibility> {
  return apiRequest<AdjustmentEligibility>(`/sales/invoices/${invoiceId}/adjustment-eligibility`);
}
