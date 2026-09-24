import { apiRequest } from './client';

export type EwayBillStatus =
  | 'NOT_APPLICABLE' | 'READY' | 'QUEUED' | 'PROCESSING' | 'GENERATED' | 'FAILED'
  | 'CANCEL_REQUESTED' | 'CANCELLED' | 'STATUS_UNKNOWN';

export interface EwayBillDetail {
  id: string | null;
  sales_invoice_id: string;
  status: EwayBillStatus;
  applicable: boolean | null;
  applicability_reason: string | null;
  eway_bill_number: string | null;
  valid_from: string | null;
  valid_until: string | null;
  transport_mode: string | null;
  vehicle_number: string | null;
  transporter_id: string | null;
  transporter_name: string | null;
  distance_km: string | null;
  provider_reference: string | null;
  provider_response_message: string | null;
  generated_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  row_version: number | null;
  updated_at: string | null;
}

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export async function getEwayBillByInvoice(invoiceId: string): Promise<EwayBillDetail> {
  return apiRequest<EwayBillDetail>(`/sales/invoices/${invoiceId}/eway-bill`);
}

export async function getEwayBill(ewayBillId: string): Promise<EwayBillDetail> {
  return apiRequest<EwayBillDetail>(`/eway-bills/${ewayBillId}`);
}

export interface GenerateEwayBillPayload {
  invoice_id: string;
  transport_mode?: string | null;
  vehicle_number?: string | null;
  transporter_id?: string | null;
  transporter_name?: string | null;
  distance_km?: string | null;
}

export async function generateEwayBill(payload: GenerateEwayBillPayload): Promise<EwayBillDetail> {
  return apiRequest<EwayBillDetail>('/eway-bills/generate', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function refreshEwayBillStatus(ewayBillId: string): Promise<EwayBillDetail> {
  return apiRequest<EwayBillDetail>(`/eway-bills/${ewayBillId}/status`, { method: 'POST', body: {} });
}

export async function cancelEwayBill(ewayBillId: string, reason: string): Promise<EwayBillDetail> {
  return apiRequest<EwayBillDetail>(`/eway-bills/${ewayBillId}/cancel`, {
    method: 'POST',
    body: { reason },
    idempotencyKey: newIdempotencyKey(),
  });
}
