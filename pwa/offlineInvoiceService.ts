// Offline Sales Invoice creation (PROMPT-028 §13/§14/§28).
//
// Provisional-only calculation for on-screen display (§14) — the exact
// same discount-before-GST / same-state-CGST+SGST-vs-IGST rule the
// server's own `gst_calculation_service.py` already implements, kept
// deliberately simple (no rounding-mode edge cases, no HSN validation)
// since the server ALWAYS recalculates authoritatively at sync time
// (§14's own explicit mandate) — this is never trusted as the final
// value, only shown to the user before they save offline.

import { dbPut, STORE_SYNC_QUEUE } from './offlineDb';
import { SyncQueueItem } from './offlineTypes';

function generateUuid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx`.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// §28: a clearly-temporary-looking reference, never mistakeable for a
// real server-assigned document number (which always looks like
// "INV-2026-27-0001").
export function generateLocalReference(entityPrefix: string): string {
  return `OFF-${entityPrefix}-${generateUuid().slice(0, 8).toUpperCase()}`;
}

export interface ProvisionalLineInput {
  product_id: string;
  product_name: string;
  quantity: number;
  uom_id: string;
  unit_price: number;
  gst_rate: number;
  discount_percent?: number;
}

export interface ProvisionalLineResult extends ProvisionalLineInput {
  gross_amount: number;
  discount_amount: number;
  taxable_amount: number;
  gst_amount: number;
  line_total: number;
}

function round2(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

// Mirrors `gst_calculation_service.calculate_line`'s discount-BEFORE-GST
// rule for the taxable value. Deliberately does NOT attempt the
// CGST+SGST-vs-IGST split offline: that split depends on comparing the
// TENANT's own state code against the customer's, and the tenant's own
// state code is not currently exposed to the frontend session context
// at all (no `GET /tenants/me`-style endpoint exists) — rather than
// GUESS a split that might be wrong, this shows one blended "Provisional
// GST" figure with an explicit "server will determine the exact CGST/
// SGST/IGST split" disclaimer (see OfflineInvoiceCapture.tsx). §14 only
// requires a PROVISIONAL total for display — never an authoritative
// tax-component breakdown — so this is a safe simplification, not a
// correctness gap in what actually gets submitted (the server ignores
// this value entirely and recalculates from scratch, split included).
export function calculateProvisionalLine(input: ProvisionalLineInput): ProvisionalLineResult {
  const gross = input.quantity * input.unit_price;
  const discount = gross * ((input.discount_percent ?? 0) / 100);
  const taxable = Math.max(0, gross - discount);
  const gstAmount = taxable * (input.gst_rate / 100);
  return {
    ...input,
    gross_amount: round2(gross), discount_amount: round2(discount), taxable_amount: round2(taxable),
    gst_amount: round2(gstAmount), line_total: round2(taxable + gstAmount),
  };
}

export function calculateProvisionalTotals(lines: ProvisionalLineResult[]) {
  const sum = (key: keyof ProvisionalLineResult) => round2(lines.reduce((total, line) => total + (line[key] as number), 0));
  return { taxable_total: sum('taxable_amount'), gst_total: sum('gst_amount'), grand_total: sum('line_total') };
}

export interface CreateOfflineInvoiceInput {
  tenantId: string;
  userId: string;
  customerId: string; // a server customer id, OR the queue_id of a not-yet-synced offline customer
  customerIsOfflineDraft: boolean;
  customerDependsOnQueueId?: string;
  lines: ProvisionalLineInput[];
  notes?: string;
}

// §13: "Save locally / Generate client_transaction_id / Assign temporary
// local reference / Mark PENDING_SYNC" — this function is that entire
// sequence.
export async function createOfflineInvoice(input: CreateOfflineInvoiceInput): Promise<SyncQueueItem> {
  const clientTransactionId = generateUuid();
  const localReference = generateLocalReference('INV');
  const now = new Date().toISOString();

  const payload: Record<string, unknown> = {
    customer_id: input.customerIsOfflineDraft ? { __local_ref: input.customerDependsOnQueueId } : input.customerId,
    notes: input.notes ?? null,
    lines: input.lines.map((line) => ({
      product_id: line.product_id,
      quantity: String(line.quantity),
      uom_id: line.uom_id,
      unit_price: String(line.unit_price),
      discount_percent: line.discount_percent ? String(line.discount_percent) : undefined,
    })),
  };

  const item: SyncQueueItem = {
    queue_id: generateUuid(),
    tenant_id: input.tenantId,
    user_id: input.userId,
    entity_type: 'SALES_INVOICE',
    operation_type: 'CREATE',
    client_transaction_id: clientTransactionId,
    local_reference: localReference,
    payload,
    depends_on: input.customerIsOfflineDraft && input.customerDependsOnQueueId ? [input.customerDependsOnQueueId] : [],
    status: 'PENDING_SYNC',
    retry_count: 0,
    max_retries: 5,
    last_attempt_at: null,
    next_retry_at: null,
    last_error: null,
    server_id: null,
    final_reference: null,
    server_response: null,
    created_at: now,
    updated_at: now,
  };

  await dbPut(STORE_SYNC_QUEUE, item as unknown as Record<string, unknown>);
  return item;
}
