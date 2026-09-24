import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';
import type { UnitRef } from './salesEstimates';

export interface SalesReturnLine {
  id: string;
  line_no: number;
  source_invoice_line_id: string;
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
}

export type ReturnReason =
  | 'DAMAGED'
  | 'WRONG_PRODUCT'
  | 'EXCESS_QUANTITY'
  | 'QUALITY_ISSUE'
  | 'CUSTOMER_REJECTION'
  | 'OTHER';

export const RETURN_REASONS: { value: ReturnReason; label: string }[] = [
  { value: 'DAMAGED', label: 'Damaged goods' },
  { value: 'WRONG_PRODUCT', label: 'Wrong product supplied' },
  { value: 'EXCESS_QUANTITY', label: 'Excess quantity' },
  { value: 'QUALITY_ISSUE', label: 'Quality issue' },
  { value: 'CUSTOMER_REJECTION', label: 'Customer rejection' },
  { value: 'OTHER', label: 'Other' },
];

export interface SalesReturnListItem {
  id: string;
  return_number: string;
  return_date: string;
  customer_id: string;
  customer_name: string;
  source_invoice_id: string;
  source_invoice_number: string;
  status: string;
  return_reason: ReturnReason;
  total_return_quantity: string;
  grand_total: string;
  tax_total: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface SalesReturnDetail extends SalesReturnListItem {
  customer_gstin: string | null;
  billing_address: string | null;
  shipping_address: string | null;
  place_of_supply_state_code: string | null;
  reason_description: string | null;
  subtotal: string;
  discount_total: string;
  taxable_total: string;
  cgst_total: string;
  sgst_total: string;
  igst_total: string;
  notes: string | null;
  accounting_posting_reference: string | null;
  gst_transaction_reference: string | null;
  lines: SalesReturnLine[];
}

export interface ReturnLineInput {
  source_invoice_line_id: string;
  quantity: string;
}

export interface ListSalesReturnsParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  return_reason?: string;
  customer_id?: string;
  source_invoice_id?: string;
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

export async function listSalesReturns(params: ListSalesReturnsParams): Promise<ApiList<SalesReturnListItem>> {
  return apiRequestList<SalesReturnListItem>(`/sales/returns${buildQuery(params)}`);
}

export async function getSalesReturn(returnId: string): Promise<SalesReturnDetail> {
  return apiRequest<SalesReturnDetail>(`/sales/returns/${returnId}`);
}

export interface CreateSalesReturnPayload {
  source_invoice_id: string;
  return_date?: string | null;
  return_reason: ReturnReason;
  reason_description?: string | null;
  notes?: string | null;
  lines: ReturnLineInput[];
}

export async function createSalesReturn(payload: CreateSalesReturnPayload): Promise<SalesReturnDetail> {
  return apiRequest<SalesReturnDetail>('/sales/returns', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export interface UpdateSalesReturnPayload {
  return_date?: string | null;
  return_reason?: ReturnReason | null;
  reason_description?: string | null;
  notes?: string | null;
  lines?: ReturnLineInput[];
  expected_row_version: number;
}

export async function updateSalesReturn(returnId: string, payload: UpdateSalesReturnPayload): Promise<SalesReturnDetail> {
  return apiRequest<SalesReturnDetail>(`/sales/returns/${returnId}`, { method: 'PATCH', body: payload });
}

export async function confirmSalesReturn(returnId: string, expectedRowVersion: number): Promise<SalesReturnDetail> {
  return apiRequest<SalesReturnDetail>(`/sales/returns/${returnId}/confirm`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function cancelSalesReturn(returnId: string, expectedRowVersion: number): Promise<SalesReturnDetail> {
  return apiRequest<SalesReturnDetail>(`/sales/returns/${returnId}/cancel`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}
