import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';
import type { UnitRef } from './salesEstimates';

export interface PurchaseOrderLine {
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
  received_quantity: string;
  remaining_quantity: string;
}

export interface PurchaseOrderListItem {
  id: string;
  po_number: string;
  document_date: string;
  supplier_id: string;
  supplier_name: string;
  supplier_reference: string | null;
  expected_delivery_date: string | null;
  status: string;
  total_ordered_quantity: string;
  total_received_quantity: string;
  total_remaining_quantity: string;
  grand_total: string;
  tax_total: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface PurchaseOrderDetail extends PurchaseOrderListItem {
  supplier_gstin: string | null;
  billing_address: string | null;
  shipping_address: string | null;
  place_of_supply_state_code: string | null;
  payment_terms: string | null;
  delivery_terms: string | null;
  subtotal: string;
  discount_total: string;
  taxable_total: string;
  cgst_total: string;
  sgst_total: string;
  igst_total: string;
  notes: string | null;
  lines: PurchaseOrderLine[];
}

export interface PurchaseOrderLineInput {
  product_id: string;
  quantity: string;
  uom_id: string;
  unit_price: string;
  discount_percent?: string | null;
  discount_amount?: string | null;
}

export interface ListPurchaseOrdersParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  supplier_id?: string;
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

export async function listPurchaseOrders(params: ListPurchaseOrdersParams): Promise<ApiList<PurchaseOrderListItem>> {
  return apiRequestList<PurchaseOrderListItem>(`/purchase/orders${buildQuery(params)}`);
}

export async function getPurchaseOrder(orderId: string): Promise<PurchaseOrderDetail> {
  return apiRequest<PurchaseOrderDetail>(`/purchase/orders/${orderId}`);
}

export interface CreatePurchaseOrderPayload {
  supplier_id: string;
  document_date?: string | null;
  supplier_reference?: string | null;
  expected_delivery_date?: string | null;
  payment_terms?: string | null;
  delivery_terms?: string | null;
  shipping_address?: string | null;
  notes?: string | null;
  lines: PurchaseOrderLineInput[];
}

export async function createPurchaseOrder(payload: CreatePurchaseOrderPayload): Promise<PurchaseOrderDetail> {
  return apiRequest<PurchaseOrderDetail>('/purchase/orders', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export interface UpdatePurchaseOrderPayload extends Partial<CreatePurchaseOrderPayload> {
  expected_row_version: number;
}

export async function updatePurchaseOrder(orderId: string, payload: UpdatePurchaseOrderPayload): Promise<PurchaseOrderDetail> {
  return apiRequest<PurchaseOrderDetail>(`/purchase/orders/${orderId}`, { method: 'PATCH', body: payload });
}

async function postAction(orderId: string, action: string, expectedRowVersion: number): Promise<PurchaseOrderDetail> {
  return apiRequest<PurchaseOrderDetail>(`/purchase/orders/${orderId}/${action}`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

export const confirmPurchaseOrder = (id: string, rowVersion: number) => postAction(id, 'confirm', rowVersion);
export const cancelPurchaseOrder = (id: string, rowVersion: number) => postAction(id, 'cancel', rowVersion);

// --- Receipt eligibility (Purchase-Order-scoped) ---

export interface ReceiptEligibilityLine {
  purchase_order_line_id: string;
  product_id: string | null;
  description: string | null;
  hsn_code: string | null;
  uom: UnitRef;
  unit_price: string;
  gst_rate: string;
  ordered_quantity: string;
  received_quantity: string;
  remaining_quantity: string;
}

export interface ReceiptEligibility {
  purchase_order_id: string;
  purchase_order_number: string;
  purchase_order_status: string;
  supplier_id: string;
  supplier_name: string;
  billing_address: string | null;
  shipping_address: string | null;
  place_of_supply_state_code: string | null;
  lines: ReceiptEligibilityLine[];
}

export async function getReceiptEligibility(purchaseOrderId: string): Promise<ReceiptEligibility> {
  return apiRequest<ReceiptEligibility>(`/purchase/orders/${purchaseOrderId}/receipt-eligibility`);
}

// --- Related documents / receiving summary / audit history (PROMPT-020) ---

export interface PurchaseOrderRelatedGoodsReceipt {
  id: string;
  grn_number: string;
  document_date: string;
  status: string;
  total_quantity: string;
  created_at: string;
}

export interface PurchaseOrderRelatedInvoice {
  id: string;
  purchase_invoice_number: string;
  document_date: string;
  status: string;
  grand_total: string;
  source_goods_receipt_id: string | null;
}

export interface PurchaseOrderRelatedDocuments {
  purchase_order_id: string;
  goods_receipts: PurchaseOrderRelatedGoodsReceipt[];
  purchase_invoices: PurchaseOrderRelatedInvoice[];
}

export async function getRelatedDocuments(orderId: string): Promise<PurchaseOrderRelatedDocuments> {
  return apiRequest<PurchaseOrderRelatedDocuments>(`/purchase/orders/${orderId}/related-documents`);
}

export interface PurchaseOrderReceivingSummaryLine {
  purchase_order_line_id: string;
  product_id: string | null;
  description: string | null;
  uom: UnitRef;
  ordered_quantity: string;
  received_quantity: string;
  remaining_quantity: string;
}

export interface PurchaseOrderReceivingSummary {
  purchase_order_id: string;
  po_number: string;
  status: string;
  total_ordered_quantity: string;
  total_received_quantity: string;
  total_remaining_quantity: string;
  lines: PurchaseOrderReceivingSummaryLine[];
}

export async function getReceivingSummary(orderId: string): Promise<PurchaseOrderReceivingSummary> {
  return apiRequest<PurchaseOrderReceivingSummary>(`/purchase/orders/${orderId}/receiving-summary`);
}

export interface PurchaseOrderAuditEvent {
  id: string;
  action: string;
  actor_user_id: string | null;
  occurred_at: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface PurchaseOrderAuditHistory {
  purchase_order_id: string;
  events: PurchaseOrderAuditEvent[];
}

export async function getAuditHistory(orderId: string): Promise<PurchaseOrderAuditHistory> {
  return apiRequest<PurchaseOrderAuditHistory>(`/purchase/orders/${orderId}/audit-history`);
}
