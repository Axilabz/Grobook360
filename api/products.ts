import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';
import type { UnitOfMeasure } from './units';

export interface UnitRef {
  id: string;
  code: string;
  name: string;
}

export interface ProductSupplierRef {
  id: string;
  name: string;
  supplier_code: string;
  phone: string | null;
}

export interface ProductUnitConversion {
  id: string;
  from_uom: UnitRef;
  to_uom: UnitRef;
  conversion_factor: string;
}

export interface Product {
  id: string;
  sku: string;
  name: string;
  hsn_code: string | null;
  gst_rate: string | null;
  base_uom: UnitRef;
  supplier: ProductSupplierRef | null;
  cost_price: string;
  selling_price: string;
  mrp: string;
  reorder_level: string;
  stock_qty_cache: string;
  status: string;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface ProductDetail extends Product {
  unit_conversions: ProductUnitConversion[];
}

export interface ListProductsParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
}

function buildQuery(params: ListProductsParams): string {
  const query = new URLSearchParams();
  if (params.page) query.set('page', String(params.page));
  if (params.page_size) query.set('page_size', String(params.page_size));
  if (params.search) query.set('search', params.search);
  if (params.status) query.set('status', params.status);
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

export async function listProducts(params: ListProductsParams): Promise<ApiList<Product>> {
  return apiRequestList<Product>(`/products${buildQuery(params)}`);
}

export async function getProduct(productId: string): Promise<ProductDetail> {
  return apiRequest<ProductDetail>(`/products/${productId}`);
}

export interface ProductFormPayload {
  sku: string;
  name: string;
  hsn_code?: string | null;
  /** Mandatory — must be one of the standard GST slabs: 0, 3, 5, 12, 18, 28. */
  gst_rate: string;
  base_uom_id: string;
  /** Optional — the product's preferred/primary supplier. */
  supplier_id?: string | null;
  cost_price?: string;
  selling_price?: string;
  mrp?: string;
}

export async function createProduct(payload: ProductFormPayload): Promise<ProductDetail> {
  return apiRequest<ProductDetail>('/products', { method: 'POST', body: payload });
}

export interface UpdateProductPayload extends Partial<ProductFormPayload> {
  expected_row_version: number;
}

export async function updateProduct(productId: string, payload: UpdateProductPayload): Promise<ProductDetail> {
  return apiRequest<ProductDetail>(`/products/${productId}`, { method: 'PATCH', body: payload });
}

export async function activateProduct(productId: string, expectedRowVersion: number): Promise<ProductDetail> {
  return apiRequest<ProductDetail>(`/products/${productId}/activate`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

export async function deactivateProduct(productId: string, expectedRowVersion: number): Promise<ProductDetail> {
  return apiRequest<ProductDetail>(`/products/${productId}/deactivate`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

export interface CreateConversionPayload {
  from_uom_id: string;
  to_uom_id: string;
  conversion_factor: string;
}

export async function createUnitConversion(productId: string, payload: CreateConversionPayload): Promise<ProductUnitConversion> {
  return apiRequest<ProductUnitConversion>(`/products/${productId}/conversions`, { method: 'POST', body: payload });
}

export type { UnitOfMeasure };
