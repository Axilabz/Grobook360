import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';

export interface Customer {
  id: string;
  customer_code: string;
  name: string;
  owner_name: string;
  phone: string | null;
  email: string | null;
  gstin: string | null;
  state_code: string | null;
  address: string | null;
  city: string | null;
  pincode: string | null;
  region: string | null;
  gps_location: string | null;
  credit_limit: string;
  payment_terms_days: number;
  balance: string;
  is_over_credit_limit: boolean;
  status: string;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface ListCustomersParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  state_code?: string;
  gst_registered?: boolean;
}

function buildQuery(params: ListCustomersParams): string {
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

export async function listCustomers(params: ListCustomersParams): Promise<ApiList<Customer>> {
  return apiRequestList<Customer>(`/customers${buildQuery(params)}`);
}

export async function getCustomer(customerId: string): Promise<Customer> {
  return apiRequest<Customer>(`/customers/${customerId}`);
}

export interface CustomerFormPayload {
  name: string;
  owner_name: string;
  phone: string;
  email?: string | null;
  gstin?: string | null;
  state_code?: string | null;
  address?: string | null;
  city?: string | null;
  pincode?: string | null;
  region?: string | null;
  gps_location?: string | null;
  credit_limit?: number;
  payment_terms_days?: number;
}

export async function createCustomer(payload: CustomerFormPayload, idempotencyKey?: string): Promise<Customer> {
  return apiRequest<Customer>('/customers', { method: 'POST', body: payload, idempotencyKey });
}

export interface UpdateCustomerPayload extends Partial<CustomerFormPayload> {
  expected_row_version: number;
}

export async function updateCustomer(customerId: string, payload: UpdateCustomerPayload): Promise<Customer> {
  return apiRequest<Customer>(`/customers/${customerId}`, { method: 'PATCH', body: payload });
}

export async function activateCustomer(customerId: string, expectedRowVersion: number): Promise<Customer> {
  return apiRequest<Customer>(`/customers/${customerId}/activate`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

export async function deactivateCustomer(customerId: string, expectedRowVersion: number): Promise<Customer> {
  return apiRequest<Customer>(`/customers/${customerId}/deactivate`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}
