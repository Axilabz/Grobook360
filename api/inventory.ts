import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';

export interface UnitRef {
  id: string;
  code: string;
  name: string;
}

export interface InventoryItem {
  product_id: string;
  sku: string;
  name: string;
  base_uom: UnitRef;
  current_stock: string;
  reorder_level: string;
  is_low_stock: boolean;
  product_status: string;
  last_movement_at: string | null;
}

export interface StockMovement {
  id: string;
  movement_type: string;
  quantity: string;
  uom: UnitRef;
  base_quantity: string;
  source_type: string;
  source_id: string;
  occurred_at: string;
  created_by: string | null;
  running_balance: string;
  adjustment_number?: string;
  reason?: string;
}

export interface AvailabilityResponse {
  product_id: string;
  available_quantity: string;
  base_uom: UnitRef;
}

export interface ListInventoryParams {
  page?: number;
  page_size?: number;
  search?: string;
  stock_status?: 'in_stock' | 'zero_stock' | 'low_stock';
  [key: string]: string | number | undefined;
}

function buildQuery(params: Record<string, string | number | undefined | null>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

export async function listInventory(params: ListInventoryParams): Promise<ApiList<InventoryItem>> {
  return apiRequestList<InventoryItem>(`/inventory${buildQuery(params)}`);
}

export async function getStockDetail(productId: string): Promise<InventoryItem> {
  return apiRequest<InventoryItem>(`/inventory/${productId}`);
}

export async function getAvailability(productId: string): Promise<AvailabilityResponse> {
  return apiRequest<AvailabilityResponse>(`/inventory/availability/${productId}`);
}

export async function listMovements(
  productId: string,
  params: { page?: number; page_size?: number; movement_type?: string; [key: string]: string | number | undefined } = {}
): Promise<ApiList<StockMovement>> {
  return apiRequestList<StockMovement>(`/inventory/${productId}/movements${buildQuery(params)}`);
}

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export interface OpeningStockPayload {
  product_id: string;
  quantity: string;
  uom_id: string;
}

export async function createOpeningStock(payload: OpeningStockPayload): Promise<StockMovement> {
  return apiRequest<StockMovement>('/inventory/opening-stock', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export interface StockMovePayload {
  product_id: string;
  quantity: string;
  uom_id: string;
  notes?: string | null;
}

export async function createStockIn(payload: StockMovePayload): Promise<StockMovement> {
  return apiRequest<StockMovement>('/inventory/stock-in', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function createStockOut(payload: StockMovePayload): Promise<StockMovement> {
  return apiRequest<StockMovement>('/inventory/stock-out', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}

export interface AdjustmentPayload {
  product_id: string;
  quantity: string;
  uom_id: string;
  direction: 'IN' | 'OUT';
  reason: string;
}

export async function createAdjustment(payload: AdjustmentPayload): Promise<StockMovement> {
  return apiRequest<StockMovement>('/inventory/adjustments', {
    method: 'POST',
    body: payload,
    idempotencyKey: newIdempotencyKey(),
  });
}
