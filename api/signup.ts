import { apiRequest } from './client';

export interface SignUpOrganization {
  business_name: string;
  address_line1: string;
  city: string;
  state_code: string;
  pin_code: string;
  gstin: string | null;
}

export interface SignUpOwner {
  phone: string;
  email: string;
  password: string;
  confirm_password: string;
}

export interface SignUpRequest {
  organization: SignUpOrganization;
  owner: SignUpOwner;
}

export interface SignUpResult {
  tenant_id: string;
  owner_user_id: string;
  status: string;
}

export async function signUp(payload: SignUpRequest, idempotencyKey: string): Promise<SignUpResult> {
  return apiRequest<SignUpResult>('/auth/sign-up', {
    method: 'POST',
    body: payload,
    idempotencyKey,
  });
}
