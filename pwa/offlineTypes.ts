// Offline sync domain types (PROMPT-028 §8/§9/§19/§20).
//
// The full PROMPT-028 §8 category list (READ CACHE / OFFLINE DRAFT / SYNC
// QUEUE / SYNCED / FAILED / CONFLICT) is implemented as ONE store
// (`sync_queue`, see offlineDb.ts) whose `status` field IS the state
// machine (§20) — a record moves through LOCAL_DRAFT -> PENDING_SYNC ->
// SYNCING -> SYNCED (or SYNC_FAILED / CONFLICT / REQUIRES_ACTION) in
// place, rather than being physically relocated between separate stores.
// This is a deliberate simplification over six separate object stores:
// the status field alone is sufficient to answer every query the six
// categories imply ("show me pending", "show me synced", ...), and a
// single store makes dependency lookups (an invoice depending on an
// offline-created customer) a single-store query instead of a join
// across stores that IndexedDB doesn't support natively.

export type SyncStatus =
  | 'LOCAL_DRAFT'
  | 'PENDING_SYNC'
  | 'SYNCING'
  | 'SYNCED'
  | 'SYNC_FAILED'
  | 'CONFLICT'
  | 'REQUIRES_ACTION';

// §2: the ONLY three offline-writable entity types in this MVP (OD-001,
// resolved to the prompt's own explicit minimum — Stock Movement is NOT
// directly offline-writable, OD-002 resolved: it only ever happens
// indirectly, server-side, as a consequence of a synced Sales Invoice).
export type OfflineEntityType = 'SALES_INVOICE' | 'CUSTOMER' | 'SUPPLIER';

export type OperationType = 'CREATE';

// §24: not every sync failure is a "conflict" — this is the taxonomy the
// sync engine classifies every non-success response into.
export type SyncFailureClass =
  | 'TRANSIENT'
  | 'VALIDATION'
  | 'AUTHORIZATION'
  | 'BUSINESS_CONFLICT'
  | 'DUPLICATE_ALREADY_PROCESSED'
  | 'DEPENDENCY_FAILURE';

export interface SyncError {
  class: SyncFailureClass;
  code: string;
  message: string;
  http_status: number | null;
}

// §9/§19: local record / queue item metadata. One row per offline
// CREATE operation (Sales Invoice, Customer quick-add, Supplier
// quick-add) — see the module docstring above for why this doubles as
// both the "offline draft" and the "sync queue" the prompt describes
// as conceptually separate categories.
export interface SyncQueueItem {
  queue_id: string; // local primary key (uuid) — stable for the record's whole lifetime
  tenant_id: string;
  user_id: string;
  entity_type: OfflineEntityType;
  operation_type: OperationType;
  // §10/§11: THE idempotency key. Generated once, sent as the
  // `Idempotency-Key` header on every sync attempt, unchanged across
  // retries/app-restarts/browser-restarts (§10's own explicit mandate).
  client_transaction_id: string;
  // §28: what the UI shows before sync ("OFF-ab12cd34"), distinct from
  // the server's own final authoritative document number.
  local_reference: string;
  // The request body to POST once synced. May contain a `__local_ref`
  // placeholder (see resolveDependencies in syncEngine.ts) in place of
  // a field like `customer_id` when this record depends on another
  // not-yet-synced offline record.
  payload: Record<string, unknown>;
  // queue_ids of OTHER SyncQueueItems that must reach SYNCED before this
  // one may be submitted (§18/§44 dependency ordering).
  depends_on: string[];
  status: SyncStatus;
  retry_count: number;
  max_retries: number;
  last_attempt_at: string | null;
  next_retry_at: string | null;
  last_error: SyncError | null;
  // Populated once SYNCED.
  server_id: string | null;
  final_reference: string | null; // e.g. the real invoice_number
  server_response: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

// §15/§36: cached read-only master data, one store per entity, always
// tagged with when it was last refreshed (§37 "Last synchronized" label
// — freshness must never be implied as "current").
export interface CachedMasterRecord {
  id: string; // server id
  tenant_id: string;
  data: Record<string, unknown>;
  synced_at: string;
}

export const DEFAULT_MAX_RETRIES = 5; // OD-011, resolved for M1
export const RETRY_BASE_DELAY_MS = 2000; // OD-012, resolved for M1: exponential backoff base
export const RETRY_MAX_DELAY_MS = 5 * 60 * 1000; // cap at 5 minutes between attempts
