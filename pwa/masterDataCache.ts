// Offline read cache for master data (PROMPT-028 §15/§36/§37).
//
// Only data a user is already entitled to see online is ever cached —
// this reuses the EXISTING authenticated/tenant-scoped list endpoints,
// never a separate "offline export" endpoint. Each cached record is
// tagged with `synced_at` (§37 — the UI must show "Last synchronized:
// <time>", never imply this is guaranteed-current stock/pricing).
//
// §51: capped at a page count per entity (not "the whole tenant's
// history") — this is a READ cache for offline invoice creation, not a
// full local mirror of the database.

import { listProducts, Product } from '../api/products';
import { listCustomers, Customer } from '../api/customers';
import { listSuppliers, Supplier } from '../api/suppliers';
import { listUnits, UnitOfMeasure } from '../api/units';
import {
  dbPut, dbGetAllByTenant, STORE_MASTER_PRODUCTS, STORE_MASTER_CUSTOMERS, STORE_MASTER_SUPPLIERS, STORE_MASTER_UNITS,
} from './offlineDb';
import { CachedMasterRecord } from './offlineTypes';

const MAX_PAGES_PER_ENTITY = 20; // 20 * 100 = up to 2,000 records per entity — an MVP-scale offline cache cap (§51)
const PAGE_SIZE = 100;

async function cacheAll<T extends { id: string }>(storeName: string, tenantId: string, records: T[]): Promise<void> {
  const syncedAt = new Date().toISOString();
  for (const record of records) {
    const cached: CachedMasterRecord = { id: record.id, tenant_id: tenantId, data: record as unknown as Record<string, unknown>, synced_at: syncedAt };
    await dbPut(storeName, cached as unknown as Record<string, unknown>);
  }
}

export async function refreshMasterData(tenantId: string): Promise<{ products: number; customers: number; suppliers: number; units: number }> {
  const products: Product[] = [];
  const customers: Customer[] = [];
  const suppliers: Supplier[] = [];

  for (let page = 1; page <= MAX_PAGES_PER_ENTITY; page++) {
    const result = await listProducts({ page, page_size: PAGE_SIZE, status: 'ACTIVE' });
    products.push(...result.data);
    if (page >= result.pagination.total_pages) break;
  }
  for (let page = 1; page <= MAX_PAGES_PER_ENTITY; page++) {
    const result = await listCustomers({ page, page_size: PAGE_SIZE, status: 'ACTIVE' });
    customers.push(...result.data);
    if (page >= result.pagination.total_pages) break;
  }
  for (let page = 1; page <= MAX_PAGES_PER_ENTITY; page++) {
    const result = await listSuppliers({ page, page_size: PAGE_SIZE, status: 'ACTIVE' });
    suppliers.push(...result.data);
    if (page >= result.pagination.total_pages) break;
  }
  const units: UnitOfMeasure[] = await listUnits();

  await cacheAll(STORE_MASTER_PRODUCTS, tenantId, products);
  await cacheAll(STORE_MASTER_CUSTOMERS, tenantId, customers);
  await cacheAll(STORE_MASTER_SUPPLIERS, tenantId, suppliers);
  await cacheAll(STORE_MASTER_UNITS, tenantId, units.map((u) => ({ ...u, id: u.id })));

  return { products: products.length, customers: customers.length, suppliers: suppliers.length, units: units.length };
}

export interface CachedRecordWithFreshness<T> {
  record: T;
  synced_at: string;
}

async function readCache<T>(storeName: string, tenantId: string): Promise<CachedRecordWithFreshness<T>[]> {
  const rows = await dbGetAllByTenant<CachedMasterRecord>(storeName, tenantId);
  return rows.map((row) => ({ record: row.data as unknown as T, synced_at: row.synced_at }));
}

export const readCachedProducts = (tenantId: string) => readCache<Product>(STORE_MASTER_PRODUCTS, tenantId);
export const readCachedCustomers = (tenantId: string) => readCache<Customer>(STORE_MASTER_CUSTOMERS, tenantId);
export const readCachedSuppliers = (tenantId: string) => readCache<Supplier>(STORE_MASTER_SUPPLIERS, tenantId);
export const readCachedUnits = (tenantId: string) => readCache<UnitOfMeasure>(STORE_MASTER_UNITS, tenantId);

export function oldestSync(records: CachedRecordWithFreshness<unknown>[]): string | null {
  if (records.length === 0) return null;
  return records.reduce((oldest, r) => (r.synced_at < oldest ? r.synced_at : oldest), records[0].synced_at);
}
