import { apiRequest } from './client';

export interface AuthUser {
  id: string;
  phone: string;
  email: string;
  role: string | null;
}

export interface AuthTenant {
  id: string;
  tenant_code: string;
  business_name: string;
}

export interface LoginResult {
  user: AuthUser;
  tenant: AuthTenant | null;
  permissions: string[];
}

export interface MeResult {
  user_id: string;
  tenant_id: string | null;
  tenant: AuthTenant | null;
  role: string | null;
  permissions: string[];
}

export async function login(loginIdentifier: string, password: string): Promise<LoginResult> {
  return apiRequest<LoginResult>('/auth/login', {
    method: 'POST',
    body: { login_identifier: loginIdentifier, password },
  });
}

export async function logout(): Promise<void> {
  await apiRequest<void>('/auth/logout', { method: 'POST' });
}

export async function fetchCurrentSession(): Promise<MeResult> {
  return apiRequest<MeResult>('/auth/me', { method: 'GET' });
}
