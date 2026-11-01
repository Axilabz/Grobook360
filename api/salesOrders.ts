import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';
import type { UnitRef } from './salesEstimates';

export interface SalesOrderLine {
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

export interface SalesOrderListItem {
  id: string;
  order_number: string;
  order_date: string;
  customer_id: string;
  customer_name: string;
  status: string;
  source_estimate_id: string | null;
  grand_total: string;
  created_by: string | null;
  created_by_name: string | null;
  updated_by_name: string | null;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface SalesOrderDetail extends SalesOrderListItem {
  customer_gstin: string | null;
  billing_address: string | null;
  shipping_address: string | null;
  place_of_supply_state_code: string | null;
  subtotal: string;
  discount_total: string;
  taxable_total: string;
  cgst_total: string;
  sgst_total: string;
  igst_total: string;
  tax_total: string;
  notes: string | null;
  cancellation_reason: string | null;
  lines: SalesOrderLine[];
}

export interface SalesOrderLineInput {
  product_id: string;
  quantity: string;
  uom_id: string;
  unit_price: string;
  discount_percent?: string | null;
  discount_amount?: string | null;
}

export interface ListSalesOrdersParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  customer_id?: string;
  date_from?: string;
  date_to?: string;
  from_estimate?: boolean;
  [key: string]: string | number | boolean | undefined;
}

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
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

export async function listSalesOrders(params: ListSalesOrdersParams): Promise<ApiList<SalesOrderListItem>> {
  return apiRequestList<SalesOrderListItem>(`/sales/orders${buildQuery(params)}`);
}

export async function getSalesOrder(orderId: string): Promise<SalesOrderDetail> {
  return apiRequest<SalesOrderDetail>(`/sales/orders/${orderId}`);
}

export interface CreateSalesOrderPayload {
  customer_id: string;
  order_date?: string | null;
  shipping_address?: string | null;
  notes?: string | null;
  lines: SalesOrderLineInput[];
}

export async function createSalesOrder(payload: CreateSalesOrderPayload): Promise<SalesOrderDetail> {
  return apiRequest<SalesOrderDetail>('/sales/orders', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export interface UpdateSalesOrderPayload extends Partial<CreateSalesOrderPayload> {
  expected_row_version: number;
}

export async function updateSalesOrder(orderId: string, payload: UpdateSalesOrderPayload): Promise<SalesOrderDetail> {
  return apiRequest<SalesOrderDetail>(`/sales/orders/${orderId}`, { method: 'PATCH', body: payload });
}

async function postAction(orderId: string, action: string, body: Record<string, unknown>): Promise<SalesOrderDetail> {
  return apiRequest<SalesOrderDetail>(`/sales/orders/${orderId}/${action}`, { method: 'POST', body });
}

export const confirmSalesOrder = (id: string, rowVersion: number) =>
  postAction(id, 'confirm', { expected_row_version: rowVersion });
export const cancelSalesOrder = (id: string, rowVersion: number, cancellationReason: string) =>
  postAction(id, 'cancel', { expected_row_version: rowVersion, cancellation_reason: cancellationReason });
