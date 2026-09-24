import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';
import type { UnitRef } from './salesEstimates';

export interface PurchaseReturnLine {
  id: string;
  line_no: number;
  source_purchase_invoice_line_id: string;
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
  stock_movement_id: string | null;
  stock_movement_reversed: boolean;
}

export type PurchaseReturnReason =
  | 'DAMAGED'
  | 'WRONG_PRODUCT'
  | 'EXCESS_QUANTITY'
  | 'QUALITY_ISSUE'
  | 'PRICE_DISPUTE'
  | 'OTHER';

export const PURCHASE_RETURN_REASONS: { value: PurchaseReturnReason; label: string }[] = [
  { value: 'DAMAGED', label: 'Damaged goods' },
  { value: 'WRONG_PRODUCT', label: 'Wrong product supplied' },
  { value: 'EXCESS_QUANTITY', label: 'Excess quantity' },
  { value: 'QUALITY_ISSUE', label: 'Quality issue' },
  { value: 'PRICE_DISPUTE', label: 'Price dispute' },
  { value: 'OTHER', label: 'Other' },
];

export interface PurchaseReturnListItem {
  id: string;
  purchase_return_number: string;
  document_date: string;
  supplier_id: string;
  supplier_name: string;
  source_purchase_invoice_id: string;
  source_purchase_invoice_number: string;
  status: string;
  return_reason: PurchaseReturnReason;
  total_return_quantity: string;
  grand_total: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface PurchaseReturnDetail extends PurchaseReturnListItem {
  reason_description: string | null;
  subtotal: string;
  discount_total: string;
  taxable_total: string;
  cgst_total: string;
  sgst_total: string;
  igst_total: string;
  tax_total: string;
  notes: string | null;
  accounting_posting_reference: string | null;
  lines: PurchaseReturnLine[];
}

export interface PurchaseReturnLineInput {
  source_purchase_invoice_line_id: string;
  quantity: string;
}

export interface ListPurchaseReturnsParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  return_reason?: string;
  supplier_id?: string;
  source_purchase_invoice_id?: string;
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

export async function listPurchaseReturns(params: ListPurchaseReturnsParams): Promise<ApiList<PurchaseReturnListItem>> {
  return apiRequestList<PurchaseReturnListItem>(`/purchase/returns${buildQuery(params)}`);
}

export async function getPurchaseReturn(returnId: string): Promise<PurchaseReturnDetail> {
  return apiRequest<PurchaseReturnDetail>(`/purchase/returns/${returnId}`);
}

export interface CreatePurchaseReturnPayload {
  source_purchase_invoice_id: string;
  document_date?: string | null;
  return_reason: PurchaseReturnReason;
  reason_description?: string | null;
  notes?: string | null;
  lines: PurchaseReturnLineInput[];
}

export async function createPurchaseReturn(payload: CreatePurchaseReturnPayload): Promise<PurchaseReturnDetail> {
  return apiRequest<PurchaseReturnDetail>('/purchase/returns', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export interface UpdatePurchaseReturnPayload {
  document_date?: string | null;
  return_reason?: PurchaseReturnReason | null;
  reason_description?: string | null;
  notes?: string | null;
  lines?: PurchaseReturnLineInput[];
  expected_row_version: number;
}

export async function updatePurchaseReturn(returnId: string, payload: UpdatePurchaseReturnPayload): Promise<PurchaseReturnDetail> {
  return apiRequest<PurchaseReturnDetail>(`/purchase/returns/${returnId}`, { method: 'PATCH', body: payload });
}

export async function confirmPurchaseReturn(returnId: string, expectedRowVersion: number): Promise<PurchaseReturnDetail> {
  return apiRequest<PurchaseReturnDetail>(`/purchase/returns/${returnId}/confirm`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function cancelPurchaseReturn(returnId: string, expectedRowVersion: number): Promise<PurchaseReturnDetail> {
  return apiRequest<PurchaseReturnDetail>(`/purchase/returns/${returnId}/cancel`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

// --- Related documents / audit history (PROMPT-023) ---

export interface PurchaseReturnRelatedGoodsReceipt {
  id: string;
  grn_number: string;
  document_date: string;
  status: string;
}

export interface PurchaseReturnRelatedDocuments {
  purchase_return_id: string;
  source_purchase_invoice_id: string;
  source_purchase_invoice_number: string;
  source_purchase_invoice_status: string;
  source_purchase_order_id: string | null;
  source_purchase_order_number: string | null;
  goods_receipts: PurchaseReturnRelatedGoodsReceipt[];
}

export async function getPurchaseReturnRelatedDocuments(returnId: string): Promise<PurchaseReturnRelatedDocuments> {
  return apiRequest<PurchaseReturnRelatedDocuments>(`/purchase/returns/${returnId}/related-documents`);
}

export interface PurchaseReturnAuditEvent {
  id: string;
  action: string;
  actor_user_id: string | null;
  occurred_at: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface PurchaseReturnAuditHistory {
  purchase_return_id: string;
  events: PurchaseReturnAuditEvent[];
}

export async function getPurchaseReturnAuditHistory(returnId: string): Promise<PurchaseReturnAuditHistory> {
  return apiRequest<PurchaseReturnAuditHistory>(`/purchase/returns/${returnId}/audit-history`);
}
