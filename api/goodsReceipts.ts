import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';
import type { UnitRef } from './salesEstimates';
import type { PurchaseInvoiceDetail } from './purchaseInvoices';

export interface GoodsReceiptLine {
  id: string;
  line_no: number;
  source_purchase_order_line_id: string | null;
  product_id: string | null;
  description: string | null;
  hsn_code: string | null;
  ordered_quantity: string;
  previously_received_quantity: string;
  quantity: string;
  remaining_quantity: string;
  uom: UnitRef;
  unit_price: string;
  taxable_amount: string;
  gst_rate: string;
  line_total: string;
  invoiced_quantity: string;
  stock_movement_id: string | null;
  stock_movement_reversed: boolean;
}

export interface GoodsReceiptListItem {
  id: string;
  grn_number: string;
  document_date: string;
  supplier_id: string;
  supplier_name: string;
  supplier_delivery_note: string | null;
  source_purchase_order_id: string | null;
  source_purchase_order_number: string | null;
  status: string;
  total_quantity: string;
  grand_total: string;
  created_by: string | null;
  created_by_name: string | null;
  updated_by_name: string | null;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface GoodsReceiptDetail extends GoodsReceiptListItem {
  notes: string | null;
  subtotal: string;
  discount_total: string;
  taxable_total: string;
  cgst_total: string;
  sgst_total: string;
  igst_total: string;
  tax_total: string;
  lines: GoodsReceiptLine[];
}

export interface ReceiptLineInput {
  purchase_order_line_id: string;
  quantity: string;
}

export interface ListGoodsReceiptsParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  supplier_id?: string;
  purchase_order_id?: string;
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

export async function listGoodsReceipts(params: ListGoodsReceiptsParams): Promise<ApiList<GoodsReceiptListItem>> {
  return apiRequestList<GoodsReceiptListItem>(`/purchase/goods-receipts${buildQuery(params)}`);
}

export async function getGoodsReceipt(receiptId: string): Promise<GoodsReceiptDetail> {
  return apiRequest<GoodsReceiptDetail>(`/purchase/goods-receipts/${receiptId}`);
}

export interface CreateGoodsReceiptPayload {
  purchase_order_id: string;
  document_date?: string | null;
  supplier_delivery_note?: string | null;
  notes?: string | null;
  lines: ReceiptLineInput[];
}

export async function createGoodsReceipt(payload: CreateGoodsReceiptPayload): Promise<GoodsReceiptDetail> {
  return apiRequest<GoodsReceiptDetail>('/purchase/goods-receipts', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export interface UpdateGoodsReceiptPayload {
  document_date?: string | null;
  supplier_delivery_note?: string | null;
  notes?: string | null;
  lines?: ReceiptLineInput[];
  expected_row_version: number;
}

export async function updateGoodsReceipt(receiptId: string, payload: UpdateGoodsReceiptPayload): Promise<GoodsReceiptDetail> {
  return apiRequest<GoodsReceiptDetail>(`/purchase/goods-receipts/${receiptId}`, { method: 'PATCH', body: payload });
}

export async function confirmGoodsReceipt(receiptId: string, expectedRowVersion: number): Promise<GoodsReceiptDetail> {
  return apiRequest<GoodsReceiptDetail>(`/purchase/goods-receipts/${receiptId}/confirm`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function cancelGoodsReceipt(receiptId: string, expectedRowVersion: number): Promise<GoodsReceiptDetail> {
  return apiRequest<GoodsReceiptDetail>(`/purchase/goods-receipts/${receiptId}/cancel`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

// --- Invoice eligibility (Goods-Receipt-scoped) + GR-initiated invoice creation ---

export interface InvoiceEligibilityLine {
  source_goods_receipt_line_id: string;
  product_id: string | null;
  description: string | null;
  hsn_code: string | null;
  uom: UnitRef;
  received_quantity: string;
  invoiced_quantity: string;
  invoiceable_quantity: string;
  unit_price: string;
  gst_rate: string;
}

export interface InvoiceEligibility {
  source_goods_receipt_id: string;
  source_goods_receipt_number: string;
  source_goods_receipt_status: string;
  supplier_id: string;
  supplier_name: string;
  lines: InvoiceEligibilityLine[];
}

export async function getInvoiceEligibility(receiptId: string): Promise<InvoiceEligibility> {
  return apiRequest<InvoiceEligibility>(`/purchase/goods-receipts/${receiptId}/invoice-eligibility`);
}

export interface InvoiceFromReceiptLineInput {
  source_goods_receipt_line_id: string;
  quantity: string;
}

export interface CreateInvoiceFromReceiptPayload {
  document_date?: string | null;
  supplier_invoice_number?: string | null;
  notes?: string | null;
  lines: InvoiceFromReceiptLineInput[];
}

export async function createInvoiceFromReceipt(receiptId: string, payload: CreateInvoiceFromReceiptPayload): Promise<PurchaseInvoiceDetail> {
  return apiRequest<PurchaseInvoiceDetail>(`/purchase/goods-receipts/${receiptId}/create-invoice`, {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

// --- Related documents / audit history (PROMPT-021) ---

export interface GoodsReceiptRelatedInvoice {
  id: string;
  purchase_invoice_number: string;
  document_date: string;
  status: string;
  grand_total: string;
}

export interface GoodsReceiptRelatedDocuments {
  goods_receipt_id: string;
  source_purchase_order_id: string | null;
  source_purchase_order_number: string | null;
  source_purchase_order_status: string | null;
  purchase_invoices: GoodsReceiptRelatedInvoice[];
}

export async function getGoodsReceiptRelatedDocuments(receiptId: string): Promise<GoodsReceiptRelatedDocuments> {
  return apiRequest<GoodsReceiptRelatedDocuments>(`/purchase/goods-receipts/${receiptId}/related-documents`);
}

export interface GoodsReceiptAuditEvent {
  id: string;
  action: string;
  actor_user_id: string | null;
  occurred_at: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface GoodsReceiptAuditHistory {
  goods_receipt_id: string;
  events: GoodsReceiptAuditEvent[];
}

export async function getGoodsReceiptAuditHistory(receiptId: string): Promise<GoodsReceiptAuditHistory> {
  return apiRequest<GoodsReceiptAuditHistory>(`/purchase/goods-receipts/${receiptId}/audit-history`);
}
