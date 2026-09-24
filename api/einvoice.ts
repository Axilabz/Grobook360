import { apiRequest } from './client';

export interface EinvoiceDetail {
  id: string | null;
  sales_invoice_id: string;
  status: 'NOT_APPLICABLE' | 'READY' | 'QUEUED' | 'PROCESSING' | 'GENERATED' | 'FAILED' | 'CANCEL_REQUESTED' | 'CANCELLED' | 'STATUS_UNKNOWN';
  applicable: boolean | null;
  applicability_reason: string | null;
  irn: string | null;
  ack_number: string | null;
  ack_date: string | null;
  has_signed_qr: boolean;
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

export async function getEinvoice(invoiceId: string): Promise<EinvoiceDetail> {
  return apiRequest<EinvoiceDetail>(`/sales/invoices/${invoiceId}/einvoice`);
}

export async function generateEinvoice(invoiceId: string): Promise<EinvoiceDetail> {
  return apiRequest<EinvoiceDetail>(`/sales/invoices/${invoiceId}/einvoice/generate`, {
    method: 'POST',
    body: {},
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function refreshEinvoiceStatus(invoiceId: string): Promise<EinvoiceDetail> {
  return apiRequest<EinvoiceDetail>(`/sales/invoices/${invoiceId}/einvoice/status`, { method: 'POST', body: {} });
}

export async function cancelEinvoice(invoiceId: string, reason: string): Promise<EinvoiceDetail> {
  return apiRequest<EinvoiceDetail>(`/sales/invoices/${invoiceId}/einvoice/cancel`, {
    method: 'POST',
    body: { reason },
    idempotencyKey: newIdempotencyKey(),
  });
}
