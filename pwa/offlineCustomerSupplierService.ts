// Offline Customer / Supplier quick-add (PROMPT-028 §16/§17).
//
// Minimum fields mirror the EXISTING Customer/Supplier Master's own
// required fields (`name` + `phone`) — no new, separately-invented
// "offline minimal schema" (OD-006/OD-007 resolved: reuse what already
// exists rather than defining a second, looser set of mandatory fields).

import { dbPut, STORE_SYNC_QUEUE } from './offlineDb';
import { SyncQueueItem } from './offlineTypes';
import { generateLocalReference } from './offlineInvoiceService';

function generateUuid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx`.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export interface OfflinePartyQuickAddInput {
  tenantId: string;
  userId: string;
  name: string;
  phone: string;
  email?: string;
}

async function createOfflineParty(entityType: 'CUSTOMER' | 'SUPPLIER', input: OfflinePartyQuickAddInput): Promise<SyncQueueItem> {
  const now = new Date().toISOString();
  const payload: Record<string, unknown> =
    entityType === 'CUSTOMER'
      ? { name: input.name, owner_name: input.name, phone: input.phone, email: input.email || null }
      : { name: input.name, contact_person: input.name, phone: input.phone, email: input.email || null };

  const item: SyncQueueItem = {
    queue_id: generateUuid(),
    tenant_id: input.tenantId,
    user_id: input.userId,
    entity_type: entityType,
    operation_type: 'CREATE',
    client_transaction_id: generateUuid(),
    local_reference: generateLocalReference(entityType === 'CUSTOMER' ? 'CUST' : 'SUPP'),
    payload,
    depends_on: [],
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

export const createOfflineCustomer = (input: OfflinePartyQuickAddInput) => createOfflineParty('CUSTOMER', input);
export const createOfflineSupplier = (input: OfflinePartyQuickAddInput) => createOfflineParty('SUPPLIER', input);
