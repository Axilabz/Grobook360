// IndexedDB local persistence layer (PROMPT-028 §7/§9/§53).
//
// Deliberately native `indexedDB` (no third-party wrapper library added
// to the project) — a thin, fully promisified layer over the four
// object stores this MVP's offline scope actually needs. localStorage is
// never used as the transactional store (§7's own explicit prohibition)
// — it's used nowhere in this file.
//
// Schema version is tracked explicitly (`DB_VERSION`, §53) so a future
// schema change goes through `onupgradeneeded` with a real migration
// path instead of silently discarding local data (§52/§53's own mandate)
// — see `migrateSchema` below for where that logic would be added.

const DB_NAME = 'saas_offline_db';
const DB_VERSION = 1;

export const STORE_SYNC_QUEUE = 'sync_queue';
export const STORE_MASTER_PRODUCTS = 'master_products';
export const STORE_MASTER_CUSTOMERS = 'master_customers';
export const STORE_MASTER_SUPPLIERS = 'master_suppliers';
export const STORE_MASTER_UNITS = 'master_units';

const MASTER_STORES = [STORE_MASTER_PRODUCTS, STORE_MASTER_CUSTOMERS, STORE_MASTER_SUPPLIERS, STORE_MASTER_UNITS] as const;

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB is not available in this environment.'));
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = request.result;
      migrateSchema(db, event.oldVersion, DB_VERSION);
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('Failed to open offline database.'));
    request.onblocked = () => reject(new Error('Offline database upgrade blocked by another open tab.'));
  });

  return dbPromise;
}

// §52/§53: every version bump adds a case here. Version 1 is the
// initial schema — nothing to migrate FROM yet, but the switch
// structure is what a real migration would extend rather than replace.
function migrateSchema(db: IDBDatabase, oldVersion: number, _newVersion: number): void {
  if (oldVersion < 1) {
    const queue = db.createObjectStore(STORE_SYNC_QUEUE, { keyPath: 'queue_id' });
    queue.createIndex('by_tenant', 'tenant_id', { unique: false });
    queue.createIndex('by_status', 'status', { unique: false });
    queue.createIndex('by_tenant_status', ['tenant_id', 'status'], { unique: false });
    queue.createIndex('by_client_transaction_id', 'client_transaction_id', { unique: true });

    for (const storeName of MASTER_STORES) {
      const store = db.createObjectStore(storeName, { keyPath: 'id' });
      store.createIndex('by_tenant', 'tenant_id', { unique: false });
    }
  }
  // if (oldVersion < 2) { ... next migration goes here, never a blind wipe ... }
}

function promisifyRequest<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed.'));
  });
}

async function withStore<T>(storeName: string, mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest<T> | void): Promise<T> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, mode);
    const store = tx.objectStore(storeName);
    const result = fn(store);
    tx.oncomplete = () => resolve(result ? (result as IDBRequest<T>).result : (undefined as unknown as T));
    tx.onerror = () => reject(tx.error ?? new Error('IndexedDB transaction failed.'));
    tx.onabort = () => reject(tx.error ?? new Error('IndexedDB transaction aborted.'));
  });
}

export async function dbPut<T extends { [key: string]: unknown }>(storeName: string, record: T): Promise<void> {
  await withStore<T>(storeName, 'readwrite', (store) => store.put(record) as unknown as IDBRequest<T>);
}

export async function dbGet<T>(storeName: string, key: string): Promise<T | undefined> {
  const db = await openDb();
  const tx = db.transaction(storeName, 'readonly');
  return promisifyRequest(tx.objectStore(storeName).get(key)) as Promise<T | undefined>;
}

export async function dbDelete(storeName: string, key: string): Promise<void> {
  await withStore(storeName, 'readwrite', (store) => store.delete(key));
}

export async function dbGetAllByTenant<T>(storeName: string, tenantId: string): Promise<T[]> {
  const db = await openDb();
  const tx = db.transaction(storeName, 'readonly');
  const index = tx.objectStore(storeName).index('by_tenant');
  return promisifyRequest(index.getAll(IDBKeyRange.only(tenantId))) as Promise<T[]>;
}

// §40: cross-tenant local data leakage is a CRITICAL defect — this is
// the primitive every tenant-scoped read in this module funnels
// through (`by_tenant` index), never an unfiltered `getAll()`.
export async function dbClearTenant(storeName: string, tenantId: string): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite');
    const store = tx.objectStore(storeName);
    const index = store.index('by_tenant');
    const request = index.openCursor(IDBKeyRange.only(tenantId));
    request.onsuccess = () => {
      const cursor = request.result;
      if (cursor) {
        cursor.delete();
        cursor.continue();
      }
    };
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

// §39: logout must NEVER silently delete unsynchronized financial data
// (sync_queue is deliberately excluded from this helper — callers that
// need to wipe a tenant's cache on logout must call it per-store and
// MUST NOT pass STORE_SYNC_QUEUE unless they've already confirmed there
// is nothing pending — see AuthContext's own logout handler).
export async function clearMasterDataForTenant(tenantId: string): Promise<void> {
  await Promise.all(MASTER_STORES.map((store) => dbClearTenant(store, tenantId)));
}

export async function hasUnsyncedTransactions(tenantId: string): Promise<boolean> {
  const items = await dbGetAllByTenant<{ status: string }>(STORE_SYNC_QUEUE, tenantId);
  return items.some((item) => item.status !== 'SYNCED');
}
