import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';

export interface UnitRef {
  id: string;
  code: string;
  name: string;
}

export interface EstimateLine {
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
}

export interface EstimateListItem {
  id: string;
  estimate_number: string;
  document_date: string;
  valid_until_date: string | null;
  customer_id: string;
  customer_name: string;
  status: string;
  is_expired_display: boolean;
  grand_total: string;
  created_by: string | null;
  created_by_name: string | null;
  updated_by_name: string | null;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface EstimateAuditEvent {
  id: string;
  action: string;
  actor_user_id: string | null;
  actor_name: string | null;
  occurred_at: string;
}

export interface EstimateAuditHistory {
  estimate_id: string;
  events: EstimateAuditEvent[];
}

export interface EstimateDetail extends EstimateListItem {
  customer_gstin: string | null;
  billing_address: string | null;
  place_of_supply_state_code: string | null;
  subtotal: string;
  discount_total: string;
  taxable_total: string;
  cgst_total: string;
  sgst_total: string;
  igst_total: string;
  tax_total: string;
  notes: string | null;
  converted_at: string | null;
  lines: EstimateLine[];
}

export interface EstimateLineInput {
  product_id: string;
  quantity: string;
  uom_id: string;
  unit_price: string;
  discount_percent?: string | null;
  discount_amount?: string | null;
}

export interface ListEstimatesParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
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

export async function listEstimates(params: ListEstimatesParams): Promise<ApiList<EstimateListItem>> {
  return apiRequestList<EstimateListItem>(`/sales/estimates${buildQuery(params)}`);
}

export async function getEstimate(estimateId: string): Promise<EstimateDetail> {
  return apiRequest<EstimateDetail>(`/sales/estimates/${estimateId}`);
}

export async function getEstimateAuditHistory(estimateId: string): Promise<EstimateAuditHistory> {
  return apiRequest<EstimateAuditHistory>(`/sales/estimates/${estimateId}/audit-history`);
}

export interface CreateEstimatePayload {
  customer_id: string;
  document_date?: string | null;
  valid_until_date?: string | null;
  notes?: string | null;
  lines: EstimateLineInput[];
}

export async function createEstimate(payload: CreateEstimatePayload): Promise<EstimateDetail> {
  return apiRequest<EstimateDetail>('/sales/estimates', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export interface UpdateEstimatePayload extends Partial<CreateEstimatePayload> {
  expected_row_version: number;
}

export async function updateEstimate(estimateId: string, payload: UpdateEstimatePayload): Promise<EstimateDetail> {
  return apiRequest<EstimateDetail>(`/sales/estimates/${estimateId}`, { method: 'PATCH', body: payload });
}

async function postAction(estimateId: string, action: string, expectedRowVersion: number): Promise<EstimateDetail> {
  return apiRequest<EstimateDetail>(`/sales/estimates/${estimateId}/${action}`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

export const sendEstimate = (id: string, rowVersion: number) => postAction(id, 'send', rowVersion);
export const acceptEstimate = (id: string, rowVersion: number) => postAction(id, 'accept', rowVersion);
export const rejectEstimate = (id: string, rowVersion: number) => postAction(id, 'reject', rowVersion);
export const cancelEstimate = (id: string, rowVersion: number) => postAction(id, 'cancel', rowVersion);

export interface ConversionResult {
  estimate_id: string;
  status: string;
  converted_at: string | null;
  sales_order_id: string | null;
  message: string;
}

export async function convertEstimate(estimateId: string, expectedRowVersion: number): Promise<ConversionResult> {
  return apiRequest<ConversionResult>(`/sales/estimates/${estimateId}/convert-to-sales-order`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
    idempotencyKey: newIdempotencyKey(),
  });
}
