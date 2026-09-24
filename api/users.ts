import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';

export interface TenantUser {
  id: string;
  name: string | null;
  phone: string | null;
  email: string;
  role: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface ListUsersParams {
  page?: number;
  page_size?: number;
  search?: string;
  role?: string;
  status?: string;
}

function buildQuery(params: ListUsersParams): string {
  const query = new URLSearchParams();
  if (params.page) query.set('page', String(params.page));
  if (params.page_size) query.set('page_size', String(params.page_size));
  if (params.search) query.set('search', params.search);
  if (params.role) query.set('role', params.role);
  if (params.status) query.set('status', params.status);
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

export async function listUsers(params: ListUsersParams): Promise<ApiList<TenantUser>> {
  return apiRequestList<TenantUser>(`/users${buildQuery(params)}`);
}

export async function getUser(userId: string): Promise<TenantUser> {
  return apiRequest<TenantUser>(`/users/${userId}`);
}

export interface CreateUserPayload {
  name: string;
  phone: string;
  email: string;
  role: string;
}

export async function createUser(payload: CreateUserPayload): Promise<TenantUser> {
  return apiRequest<TenantUser>('/users', { method: 'POST', body: payload });
}

export interface UpdateUserPayload {
  name?: string;
  email?: string;
  role?: string;
  expected_row_version: number;
}

export async function updateUser(userId: string, payload: UpdateUserPayload): Promise<TenantUser> {
  return apiRequest<TenantUser>(`/users/${userId}`, { method: 'PATCH', body: payload });
}

export async function activateUser(userId: string, expectedRowVersion: number): Promise<TenantUser> {
  return apiRequest<TenantUser>(`/users/${userId}/activate`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

export async function deactivateUser(userId: string, expectedRowVersion: number): Promise<TenantUser> {
  return apiRequest<TenantUser>(`/users/${userId}/deactivate`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}
