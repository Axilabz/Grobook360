// Offline sync engine (PROMPT-028 §11/§18/§21-§25/§44).
//
// Architecture decision (documented, not silently assumed): this engine
// does NOT call a generic `POST /sync` endpoint. It REPLAYS the SAME
// REST endpoints the online UI already uses (`POST /customers`,
// `POST /suppliers`, `POST /sales/invoices`), sending the record's own
// `client_transaction_id` as the `Idempotency-Key` header on every
// attempt. §46 explicitly permits "the existing API architecture's
// equivalent" — reusing already-built, already-tested idempotent
// endpoints is safer than adding a second, parallel creation path with
// its own bugs to find. See PROMPT-028-NOTES.md §1 for the full
// rationale.

import { apiRequest, ApiError } from '../api/client';
import {
  dbGetAllByTenant, dbPut, STORE_SYNC_QUEUE,
} from './offlineDb';
import {
  SyncQueueItem, SyncStatus, SyncError, SyncFailureClass,
  RETRY_BASE_DELAY_MS, RETRY_MAX_DELAY_MS,
} from './offlineTypes';
import { checkRealConnectivity } from './connectivity';

// --- pure logic (unit-testable without a browser/IndexedDB) --------------

const ENDPOINT_BY_ENTITY: Record<SyncQueueItem['entity_type'], string> = {
  CUSTOMER: '/customers',
  SUPPLIER: '/suppliers',
  SALES_INVOICE: '/sales/invoices',
};

// §54: maps a sync outcome to a failure class + whether the engine
// should keep retrying automatically or hand it to the user.
export function classifySyncFailure(httpStatus: number | null, errorCode: string | undefined, message: string): SyncError {
  if (httpStatus === null) {
    return { class: 'TRANSIENT', code: 'NETWORK_ERROR', message, http_status: null };
  }
  if (httpStatus >= 500) {
    return { class: 'TRANSIENT', code: errorCode ?? 'SERVER_ERROR', message, http_status: httpStatus };
  }
  if (httpStatus === 401) {
    return { class: 'AUTHORIZATION', code: errorCode ?? 'AUTHENTICATION_REQUIRED', message, http_status: httpStatus };
  }
  if (httpStatus === 403) {
    return { class: 'AUTHORIZATION', code: errorCode ?? 'AUTHORIZATION_ERROR', message, http_status: httpStatus };
  }
  if (httpStatus === 409) {
    // §24 D vs E: a business/stock conflict (409) and an idempotent
    // duplicate replay both surface as 409 at the HTTP layer in this
    // codebase's own conventions (e.g. INVENTORY_INSUFFICIENT_STOCK vs
    // REG_IDEMPOTENCY_CONFLICT) — callers of this function are expected
    // to have already short-circuited a true duplicate via the
    // idempotent-replay 2xx path (§11); a 409 reaching here is always a
    // genuine business conflict, never "already processed".
    return { class: 'BUSINESS_CONFLICT', code: errorCode ?? 'CONFLICT', message, http_status: httpStatus };
  }
  if (httpStatus === 400 || httpStatus === 422) {
    return { class: 'VALIDATION', code: errorCode ?? 'VALIDATION_ERROR', message, http_status: httpStatus };
  }
  if (httpStatus === 404) {
    return { class: 'DEPENDENCY_FAILURE', code: errorCode ?? 'DEPENDENCY_NOT_FOUND', message, http_status: httpStatus };
  }
  return { class: 'TRANSIENT', code: errorCode ?? 'UNKNOWN_ERROR', message, http_status: httpStatus };
}

// §22/§23: only TRANSIENT failures are auto-retried; everything else
// needs user/system action (REQUIRES_ACTION or CONFLICT).
export function statusForFailure(failure: SyncError, retryCount: number, maxRetries: number): SyncStatus {
  if (failure.class === 'BUSINESS_CONFLICT') return 'CONFLICT';
  if (failure.class === 'VALIDATION' || failure.class === 'AUTHORIZATION' || failure.class === 'DEPENDENCY_FAILURE') return 'REQUIRES_ACTION';
  // TRANSIENT
  return retryCount >= maxRetries ? 'SYNC_FAILED' : 'PENDING_SYNC';
}

// §22: exponential backoff with jitter, capped (OD-012 resolved for M1).
export function computeBackoffMs(retryCount: number): number {
  const exponential = RETRY_BASE_DELAY_MS * Math.pow(2, retryCount);
  const capped = Math.min(exponential, RETRY_MAX_DELAY_MS);
  const jitter = capped * (0.85 + Math.random() * 0.3); // +/-15%
  return Math.round(jitter);
}

// §18/§44: orders queue items so a dependency always syncs before its
// dependents. Returns items that are eligible to attempt THIS pass —
// an item whose dependency hasn't reached SYNCED yet is simply omitted
// (it stays PENDING_SYNC and is picked up on a later pass once its
// dependency succeeds), never submitted with an unresolved reference.
export function selectEligibleItems(allItems: SyncQueueItem[]): SyncQueueItem[] {
  const byId = new Map(allItems.map((item) => [item.queue_id, item]));
  const eligible: SyncQueueItem[] = [];

  for (const item of allItems) {
    if (item.status !== 'PENDING_SYNC') continue;
    const unmetDependency = item.depends_on.find((depId) => {
      const dep = byId.get(depId);
      return dep ? dep.status !== 'SYNCED' : false; // an unknown dep id is treated as already resolved/removed
    });
    if (!unmetDependency) eligible.push(item);
  }
  return eligible;
}

// Replaces `{ __local_ref: "<queue_id>" }` placeholders in a payload
// (at any top-level field) with the now-known server id of that
// dependency. Called only for items whose dependencies are ALL synced
// (guaranteed by `selectEligibleItems`), so every placeholder is
// resolvable — never sent with a dangling local reference (§18's own
// explicit "do not submit the invoice with an invalid server ID" rule).
export function resolveDependencyReferences(payload: Record<string, unknown>, resolvedIds: Map<string, string>): Record<string, unknown> {
  const resolved: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(payload)) {
    if (value && typeof value === 'object' && '__local_ref' in (value as Record<string, unknown>)) {
      const localRef = (value as { __local_ref: string }).__local_ref;
      const serverId = resolvedIds.get(localRef);
      resolved[key] = serverId ?? value;
    } else {
      resolved[key] = value;
    }
  }
  return resolved;
}

// --- orchestration (browser/IndexedDB/network side-effects) --------------

export interface SyncRunResult {
  attempted: number;
  synced: number;
  failed: number;
  conflicts: number;
  requiresAction: number;
  skippedUnresolvedDependency: number;
}

async function markItem(item: SyncQueueItem, patch: Partial<SyncQueueItem>): Promise<SyncQueueItem> {
  const updated: SyncQueueItem = { ...item, ...patch, updated_at: new Date().toISOString() };
  await dbPut(STORE_SYNC_QUEUE, updated as unknown as Record<string, unknown>);
  return updated;
}

async function syncOneItem(item: SyncQueueItem, resolvedIds: Map<string, string>): Promise<SyncQueueItem> {
  const endpoint = ENDPOINT_BY_ENTITY[item.entity_type];
  const payload = resolveDependencyReferences(item.payload, resolvedIds);
  await markItem(item, { status: 'SYNCING', last_attempt_at: new Date().toISOString() });

  try {
    const response = await apiRequest<Record<string, unknown>>(endpoint, {
      method: 'POST',
      body: payload,
      idempotencyKey: item.client_transaction_id,
    });
    const serverId = (response as { id?: string }).id ?? null;
    const finalReference =
      (response as { invoice_number?: string; customer_code?: string; supplier_code?: string }).invoice_number ??
      (response as { customer_code?: string }).customer_code ??
      (response as { supplier_code?: string }).supplier_code ??
      null;
    return await markItem(item, {
      status: 'SYNCED', server_id: serverId, final_reference: finalReference, server_response: response,
      last_error: null, payload,
    });
  } catch (err) {
    const isApiError = err instanceof ApiError;
    const httpStatus = isApiError ? err.status : null;
    const code = isApiError ? err.code : undefined;
    const message = err instanceof Error ? err.message : 'Sync failed for an unknown reason.';
    const failure = classifySyncFailure(httpStatus, code, message);
    const nextRetryCount = item.retry_count + 1;
    const nextStatus = statusForFailure(failure, nextRetryCount, item.max_retries);
    const backoffMs = computeBackoffMs(nextRetryCount);
    return await markItem(item, {
      status: nextStatus,
      retry_count: nextRetryCount,
      last_error: failure,
      next_retry_at: nextStatus === 'PENDING_SYNC' ? new Date(Date.now() + backoffMs).toISOString() : null,
      payload, // keep the resolved payload so a manual retry doesn't need to re-resolve
    });
  }
}

// §21: the single entry point the ConnectivityBadge / Sync Center /
// periodic timer all call. Never assumes `navigator.onLine` alone is
// sufficient — always performs a real health check first.
export async function runSync(tenantId: string): Promise<SyncRunResult | null> {
  const reallyOnline = await checkRealConnectivity();
  if (!reallyOnline) return null;

  const allItems = await dbGetAllByTenant<SyncQueueItem>(STORE_SYNC_QUEUE, tenantId);
  const now = Date.now();
  const isDue = (item: SyncQueueItem) => !item.next_retry_at || new Date(item.next_retry_at).getTime() <= now;

  // `selectEligibleItems` needs the FULL list to correctly look up each
  // dependency's status; the due-for-retry backoff filter is applied
  // afterward, only to narrow which of the dependency-eligible items are
  // actually attempted this pass.
  const eligible = selectEligibleItems(allItems).filter(isDue);
  const resolvedIds = new Map<string, string>();
  for (const item of allItems) {
    if (item.status === 'SYNCED' && item.server_id) resolvedIds.set(item.queue_id, item.server_id);
  }

  const result: SyncRunResult = { attempted: 0, synced: 0, failed: 0, conflicts: 0, requiresAction: 0, skippedUnresolvedDependency: allItems.filter((i) => i.status === 'PENDING_SYNC').length - eligible.length };

  // §44: dependency-ordered — CUSTOMER/SUPPLIER items never depend on
  // anything else offline-writable, so processing eligible items in the
  // order returned (deps-first, by construction of selectEligibleItems)
  // already satisfies "customer syncs before its dependent invoice"
  // within a single pass; a second pass (see Sync Center's own repeated
  // `runSync` calls) picks up invoices whose customer just got its
  // server id in THIS pass.
  for (const item of eligible) {
    result.attempted += 1;
    const outcome = await syncOneItem(item, resolvedIds);
    if (outcome.status === 'SYNCED' && outcome.server_id) {
      resolvedIds.set(outcome.queue_id, outcome.server_id);
      result.synced += 1;
    } else if (outcome.status === 'CONFLICT') {
      result.conflicts += 1;
    } else if (outcome.status === 'REQUIRES_ACTION') {
      result.requiresAction += 1;
    } else {
      result.failed += 1;
    }
  }

  // A second pass lets any invoice that depended on a customer synced
  // in THIS run go out in the SAME `runSync` call, instead of waiting
  // for the next periodic trigger.
  if (result.synced > 0) {
    const secondPass = await runSync(tenantId);
    if (secondPass) {
      result.attempted += secondPass.attempted;
      result.synced += secondPass.synced;
      result.failed += secondPass.failed;
      result.conflicts += secondPass.conflicts;
      result.requiresAction += secondPass.requiresAction;
    }
  }

  return result;
}

export async function retryItem(item: SyncQueueItem): Promise<SyncQueueItem> {
  const reset = await markItem(item, { status: 'PENDING_SYNC', next_retry_at: null });
  const tenantAllItems = await dbGetAllByTenant<SyncQueueItem>(STORE_SYNC_QUEUE, item.tenant_id);
  const resolvedIds = new Map<string, string>();
  for (const other of tenantAllItems) {
    if (other.status === 'SYNCED' && other.server_id) resolvedIds.set(other.queue_id, other.server_id);
  }
  return syncOneItem(reset, resolvedIds);
}

export async function cancelQueueItem(item: SyncQueueItem): Promise<void> {
  // §43/OD-015: only a not-yet-posted local transaction can be
  // cancelled — a SYNCED (server-posted) record is immutable here,
  // matching every other document type's own "cannot edit a posted
  // financial transaction" rule established throughout this codebase.
  if (item.status === 'SYNCED' || item.status === 'SYNCING') {
    throw new Error('A synced or in-progress transaction cannot be cancelled locally.');
  }
  await markItem(item, { status: 'REQUIRES_ACTION', last_error: { class: 'VALIDATION', code: 'CANCELLED_BY_USER', message: 'Cancelled by user before sync.', http_status: null } });
}
