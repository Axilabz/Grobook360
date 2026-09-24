import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';
import type { UnitRef } from './salesEstimates';

export interface DeliveryChallanLine {
  id: string;
  line_no: number;
  source_sales_order_line_id: string;
  product_id: string | null;
  description: string | null;
  hsn_code: string | null;
  uom: UnitRef;
  ordered_quantity: string;
  previously_delivered_quantity: string;
  current_delivery_quantity: string;
  remaining_quantity: string;
}

export interface DeliveryChallanListItem {
  id: string;
  challan_number: string;
  challan_date: string;
  source_sales_order_id: string;
  source_sales_order_number: string;
  customer_id: string;
  customer_name: string;
  status: string;
  total_quantity: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface DeliveryChallanDetail extends DeliveryChallanListItem {
  billing_address: string | null;
  shipping_address: string | null;
  place_of_supply_state_code: string | null;
  notes: string | null;
  lines: DeliveryChallanLine[];
}

export interface DeliveryLineInput {
  sales_order_line_id: string;
  quantity: string;
}

export interface ListDeliveryChallansParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  customer_id?: string;
  sales_order_id?: string;
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

export async function listDeliveryChallans(params: ListDeliveryChallansParams): Promise<ApiList<DeliveryChallanListItem>> {
  return apiRequestList<DeliveryChallanListItem>(`/sales/delivery-challans${buildQuery(params)}`);
}

export async function getDeliveryChallan(challanId: string): Promise<DeliveryChallanDetail> {
  return apiRequest<DeliveryChallanDetail>(`/sales/delivery-challans/${challanId}`);
}

export interface CreateDeliveryChallanPayload {
  sales_order_id: string;
  challan_date?: string | null;
  shipping_address?: string | null;
  notes?: string | null;
  lines: DeliveryLineInput[];
}

export async function createDeliveryChallan(payload: CreateDeliveryChallanPayload): Promise<DeliveryChallanDetail> {
  return apiRequest<DeliveryChallanDetail>('/sales/delivery-challans', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export interface UpdateDeliveryChallanPayload {
  challan_date?: string | null;
  shipping_address?: string | null;
  notes?: string | null;
  lines?: DeliveryLineInput[];
  expected_row_version: number;
}

export async function updateDeliveryChallan(
  challanId: string,
  payload: UpdateDeliveryChallanPayload
): Promise<DeliveryChallanDetail> {
  return apiRequest<DeliveryChallanDetail>(`/sales/delivery-challans/${challanId}`, { method: 'PATCH', body: payload });
}

export async function confirmDeliveryChallan(challanId: string, expectedRowVersion: number): Promise<DeliveryChallanDetail> {
  return apiRequest<DeliveryChallanDetail>(`/sales/delivery-challans/${challanId}/confirm`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function cancelDeliveryChallan(challanId: string, expectedRowVersion: number): Promise<DeliveryChallanDetail> {
  return apiRequest<DeliveryChallanDetail>(`/sales/delivery-challans/${challanId}/cancel`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

// --- Delivery eligibility (Sales Order-scoped) ---

export interface DeliveryEligibilityLine {
  sales_order_line_id: string;
  product_id: string | null;
  description: string | null;
  hsn_code: string | null;
  uom: UnitRef;
  ordered_quantity: string;
  delivered_quantity: string;
  remaining_quantity: string;
}

export interface DeliveryEligibility {
  sales_order_id: string;
  sales_order_number: string;
  sales_order_status: string;
  customer_id: string;
  customer_name: string;
  billing_address: string | null;
  shipping_address: string | null;
  place_of_supply_state_code: string | null;
  lines: DeliveryEligibilityLine[];
}

export async function getDeliveryEligibility(salesOrderId: string): Promise<DeliveryEligibility> {
  return apiRequest<DeliveryEligibility>(`/sales/orders/${salesOrderId}/delivery-eligibility`);
}
