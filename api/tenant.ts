import { apiRequest } from './client';

export interface TenantProfile {
  id: string;
  tenant_code: string;
  business_name: string;
  gstin: string | null;
  state_code: string | null;
  address_line1: string | null;
  city: string | null;
  pin_code: string | null;
  pan: string | null;
  business_type: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  bank_name: string | null;
  bank_account_number: string | null;
  bank_account_holder_name: string | null;
  bank_ifsc: string | null;
  bank_branch_name: string | null;
  bank_account_type: string | null;
  bank_upi_id: string | null;
  financial_year_start_month: number;
  status: string;
  row_version: number;
}

export interface UpdateTenantProfilePayload {
  business_name: string;
  gstin?: string | null;
  state_code?: string | null;
  address_line1?: string | null;
  city?: string | null;
  pin_code?: string | null;
  pan?: string | null;
  business_type?: string | null;
  phone?: string | null;
  email?: string | null;
  website?: string | null;
  bank_name?: string | null;
  bank_account_number?: string | null;
  bank_account_holder_name?: string | null;
  bank_ifsc?: string | null;
  bank_branch_name?: string | null;
  bank_account_type?: string | null;
  bank_upi_id?: string | null;
  expected_row_version: number;
}

export async function getTenantProfile(): Promise<TenantProfile> {
  return apiRequest<TenantProfile>('/tenant');
}

export async function updateTenantProfile(payload: UpdateTenantProfilePayload): Promise<TenantProfile> {
  return apiRequest<TenantProfile>('/tenant', { method: 'PATCH', body: payload });
}
