import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';
import type { UnitRef } from './salesEstimates';

export type NoteType = 'CREDIT_NOTE' | 'DEBIT_NOTE';

export interface CreditDebitNoteLine {
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

export interface CreditDebitNoteListItem {
  id: string;
  note_number: string;
  note_type: NoteType;
  note_date: string;
  customer_id: string;
  customer_name: string;
  source_invoice_id: string;
  source_invoice_number: string;
  status: string;
  reason: string;
  grand_total: string;
  tax_total: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface CreditDebitNoteDetail extends CreditDebitNoteListItem {
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
  notes: string | null;
  accounting_posting_reference: string | null;
  gst_transaction_reference: string | null;
  lines: CreditDebitNoteLine[];
}

export interface AdjustmentLineInput {
  source_invoice_line_id: string;
  quantity: string;
}

export interface ListCreditDebitNotesParams {
  page?: number;
  page_size?: number;
  search?: string;
  note_type?: string;
  status?: string;
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

export async function listCreditDebitNotes(params: ListCreditDebitNotesParams): Promise<ApiList<CreditDebitNoteListItem>> {
  return apiRequestList<CreditDebitNoteListItem>(`/sales/credit-debit-notes${buildQuery(params)}`);
}

export async function getCreditDebitNote(noteId: string): Promise<CreditDebitNoteDetail> {
  return apiRequest<CreditDebitNoteDetail>(`/sales/credit-debit-notes/${noteId}`);
}

export interface CreateCreditDebitNotePayload {
  source_invoice_id: string;
  note_type: NoteType;
  note_date?: string | null;
  reason: string;
  notes?: string | null;
  lines: AdjustmentLineInput[];
}

export async function createCreditDebitNote(payload: CreateCreditDebitNotePayload): Promise<CreditDebitNoteDetail> {
  return apiRequest<CreditDebitNoteDetail>('/sales/credit-debit-notes', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export interface UpdateCreditDebitNotePayload {
  note_date?: string | null;
  reason?: string | null;
  notes?: string | null;
  lines?: AdjustmentLineInput[];
  expected_row_version: number;
}

export async function updateCreditDebitNote(noteId: string, payload: UpdateCreditDebitNotePayload): Promise<CreditDebitNoteDetail> {
  return apiRequest<CreditDebitNoteDetail>(`/sales/credit-debit-notes/${noteId}`, { method: 'PATCH', body: payload });
}

export async function postCreditDebitNote(noteId: string, expectedRowVersion: number): Promise<CreditDebitNoteDetail> {
  return apiRequest<CreditDebitNoteDetail>(`/sales/credit-debit-notes/${noteId}/post`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function cancelCreditDebitNote(noteId: string, expectedRowVersion: number): Promise<CreditDebitNoteDetail> {
  return apiRequest<CreditDebitNoteDetail>(`/sales/credit-debit-notes/${noteId}/cancel`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}
