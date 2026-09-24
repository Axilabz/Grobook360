import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';

export interface Supplier {
  id: string;
  supplier_code: string;
  name: string;
  contact_person: string;
  phone: string | null;
  email: string | null;
  gstin: string | null;
  state_code: string | null;
  address: string | null;
  city: string | null;
  pincode: string | null;
  credit_terms_days: number;
  balance: string;
  status: string;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface ListSuppliersParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  state_code?: string;
  gst_registered?: boolean;
}

function buildQuery(params: ListSuppliersParams): string {
  const query = new URLSearchParams();
  if (params.page) query.set('page', String(params.page));
  if (params.page_size) query.set('page_size', String(params.page_size));
  if (params.search) query.set('search', params.search);
  if (params.status) query.set('status', params.status);
  if (params.state_code) query.set('state_code', params.state_code);
  if (params.gst_registered !== undefined) query.set('gst_registered', String(params.gst_registered));
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

export async function listSuppliers(params: ListSuppliersParams): Promise<ApiList<Supplier>> {
  return apiRequestList<Supplier>(`/suppliers${buildQuery(params)}`);
}

export async function getSupplier(supplierId: string): Promise<Supplier> {
  return apiRequest<Supplier>(`/suppliers/${supplierId}`);
}

export interface SupplierFormPayload {
  name: string;
  contact_person: string;
  phone: string;
  email?: string | null;
  gstin?: string | null;
  state_code?: string | null;
  address?: string | null;
  city?: string | null;
  pincode?: string | null;
  credit_terms_days?: number;
}

export async function createSupplier(payload: SupplierFormPayload, idempotencyKey?: string): Promise<Supplier> {
  return apiRequest<Supplier>('/suppliers', { method: 'POST', body: payload, idempotencyKey });
}

export interface UpdateSupplierPayload extends Partial<SupplierFormPayload> {
  expected_row_version: number;
}

export async function updateSupplier(supplierId: string, payload: UpdateSupplierPayload): Promise<Supplier> {
  return apiRequest<Supplier>(`/suppliers/${supplierId}`, { method: 'PATCH', body: payload });
}

export async function activateSupplier(supplierId: string, expectedRowVersion: number): Promise<Supplier> {
  return apiRequest<Supplier>(`/suppliers/${supplierId}/activate`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

export async function deactivateSupplier(supplierId: string, expectedRowVersion: number): Promise<Supplier> {
  return apiRequest<Supplier>(`/suppliers/${supplierId}/deactivate`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}
