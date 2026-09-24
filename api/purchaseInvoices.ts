import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';
import type { UnitRef } from './salesEstimates';

export interface PurchaseInvoiceLine {
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
  source_goods_receipt_line_id: string | null;
  source_purchase_order_line_id: string | null;
  returned_quantity: string;
  stock_movement_id: string | null;
  stock_movement_reversed: boolean;
}

export type PurchaseInvoiceType = 'DIRECT_PURCHASE_INVOICE' | 'GOODS_RECEIPT_PURCHASE_INVOICE' | 'PURCHASE_ORDER_PURCHASE_INVOICE';

export type PurchaseInvoiceStockImpact = 'STOCK_IN_REQUIRED' | 'STOCK_ALREADY_RECEIVED';

export interface PurchaseInvoiceListItem {
  id: string;
  purchase_invoice_number: string;
  supplier_invoice_number: string | null;
  document_date: string;
  supplier_invoice_date: string | null;
  due_date: string | null;
  invoice_type: PurchaseInvoiceType;
  supplier_id: string;
  supplier_name: string;
  status: string;
  source_goods_receipt_id: string | null;
  source_goods_receipt_number: string | null;
  source_purchase_order_id: string | null;
  source_purchase_order_number: string | null;
  stock_impact: PurchaseInvoiceStockImpact;
  grand_total: string;
  tax_total: string;
  paid_amount: string;
  payment_status: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface PurchaseInvoiceDetail extends PurchaseInvoiceListItem {
  supplier_gstin: string | null;
  place_of_supply_state_code: string | null;
  subtotal: string;
  discount_total: string;
  taxable_total: string;
  cgst_total: string;
  sgst_total: string;
  igst_total: string;
  notes: string | null;
  duplicate_supplier_invoice_warning: boolean;
  accounting_posting_reference: string | null;
  lines: PurchaseInvoiceLine[];
}

export interface DirectPurchaseInvoiceLineInput {
  product_id: string;
  quantity: string;
  uom_id: string;
  unit_price: string;
  discount_percent?: string | null;
  discount_amount?: string | null;
}

export interface ListPurchaseInvoicesParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  invoice_type?: string;
  supplier_id?: string;
  source_goods_receipt_id?: string;
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

export async function listPurchaseInvoices(params: ListPurchaseInvoicesParams): Promise<ApiList<PurchaseInvoiceListItem>> {
  return apiRequestList<PurchaseInvoiceListItem>(`/purchase/invoices${buildQuery(params)}`);
}

export async function getPurchaseInvoice(invoiceId: string): Promise<PurchaseInvoiceDetail> {
  return apiRequest<PurchaseInvoiceDetail>(`/purchase/invoices/${invoiceId}`);
}

export interface CreateDirectPurchaseInvoicePayload {
  supplier_id: string;
  document_date?: string | null;
  supplier_invoice_number?: string | null;
  supplier_invoice_date?: string | null;
  due_date?: string | null;
  notes?: string | null;
  lines: DirectPurchaseInvoiceLineInput[];
}

export async function createDirectPurchaseInvoice(payload: CreateDirectPurchaseInvoicePayload): Promise<PurchaseInvoiceDetail> {
  return apiRequest<PurchaseInvoiceDetail>('/purchase/invoices', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export interface UpdatePurchaseInvoicePayload {
  document_date?: string | null;
  supplier_invoice_number?: string | null;
  supplier_invoice_date?: string | null;
  due_date?: string | null;
  notes?: string | null;
  lines?: DirectPurchaseInvoiceLineInput[];
  expected_row_version: number;
}

export async function updatePurchaseInvoice(invoiceId: string, payload: UpdatePurchaseInvoicePayload): Promise<PurchaseInvoiceDetail> {
  return apiRequest<PurchaseInvoiceDetail>(`/purchase/invoices/${invoiceId}`, { method: 'PATCH', body: payload });
}

export async function postPurchaseInvoice(invoiceId: string, expectedRowVersion: number): Promise<PurchaseInvoiceDetail> {
  return apiRequest<PurchaseInvoiceDetail>(`/purchase/invoices/${invoiceId}/post`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function cancelPurchaseInvoice(invoiceId: string, expectedRowVersion: number): Promise<PurchaseInvoiceDetail> {
  return apiRequest<PurchaseInvoiceDetail>(`/purchase/invoices/${invoiceId}/cancel`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

// --- Return eligibility (Purchase-Invoice-scoped) ---

export interface PurchaseReturnEligibilityLine {
  source_purchase_invoice_line_id: string;
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

export interface PurchaseReturnEligibility {
  source_purchase_invoice_id: string;
  source_purchase_invoice_number: string;
  source_purchase_invoice_status: string;
  supplier_id: string;
  supplier_name: string;
  lines: PurchaseReturnEligibilityLine[];
}

export async function getPurchaseReturnEligibility(invoiceId: string): Promise<PurchaseReturnEligibility> {
  return apiRequest<PurchaseReturnEligibility>(`/purchase/invoices/${invoiceId}/return-eligibility`);
}

// --- Related documents / audit history (PROMPT-022) ---

export interface PurchaseInvoiceRelatedGoodsReceipt {
  id: string;
  grn_number: string;
  document_date: string;
  status: string;
}

export interface PurchaseInvoiceRelatedReturn {
  id: string;
  purchase_return_number: string;
  document_date: string;
  status: string;
  grand_total: string;
}

export interface PurchaseInvoiceRelatedDocuments {
  purchase_invoice_id: string;
  source_purchase_order_id: string | null;
  source_purchase_order_number: string | null;
  source_purchase_order_status: string | null;
  goods_receipts: PurchaseInvoiceRelatedGoodsReceipt[];
  purchase_returns: PurchaseInvoiceRelatedReturn[];
}

export async function getPurchaseInvoiceRelatedDocuments(invoiceId: string): Promise<PurchaseInvoiceRelatedDocuments> {
  return apiRequest<PurchaseInvoiceRelatedDocuments>(`/purchase/invoices/${invoiceId}/related-documents`);
}

export interface PurchaseInvoiceAuditEvent {
  id: string;
  action: string;
  actor_user_id: string | null;
  occurred_at: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface PurchaseInvoiceAuditHistory {
  purchase_invoice_id: string;
  events: PurchaseInvoiceAuditEvent[];
}

export async function getPurchaseInvoiceAuditHistory(invoiceId: string): Promise<PurchaseInvoiceAuditHistory> {
  return apiRequest<PurchaseInvoiceAuditHistory>(`/purchase/invoices/${invoiceId}/audit-history`);
}

// --- PO-linked invoicing ("Supported Flow 2") ---

export interface PurchaseOrderInvoiceEligibilityLine {
  purchase_order_line_id: string;
  product_id: string | null;
  description: string | null;
  hsn_code: string | null;
  uom: UnitRef;
  unit_price: string;
  gst_rate: string;
  ordered_quantity: string;
  received_quantity: string;
  invoiced_quantity: string;
  invoiceable_quantity: string;
}

export interface PurchaseOrderInvoiceEligibility {
  purchase_order_id: string;
  purchase_order_number: string;
  purchase_order_status: string;
  supplier_id: string;
  supplier_name: string;
  lines: PurchaseOrderInvoiceEligibilityLine[];
}

export async function getPurchaseOrderInvoiceEligibility(purchaseOrderId: string): Promise<PurchaseOrderInvoiceEligibility> {
  return apiRequest<PurchaseOrderInvoiceEligibility>(`/purchase/orders/${purchaseOrderId}/invoiceable-items`);
}

export interface InvoiceFromPurchaseOrderLineInput {
  purchase_order_line_id: string;
  quantity: string;
}

export interface CreateInvoiceFromPurchaseOrderPayload {
  document_date?: string | null;
  supplier_invoice_number?: string | null;
  supplier_invoice_date?: string | null;
  due_date?: string | null;
  notes?: string | null;
  lines: InvoiceFromPurchaseOrderLineInput[];
}

export async function createInvoiceFromPurchaseOrder(
  purchaseOrderId: string, payload: CreateInvoiceFromPurchaseOrderPayload
): Promise<PurchaseInvoiceDetail> {
  return apiRequest<PurchaseInvoiceDetail>(`/purchase/orders/${purchaseOrderId}/create-invoice`, {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}
