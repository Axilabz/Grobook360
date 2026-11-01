import { apiRequest } from './client';
import { API_BASE_URL } from './baseUrl';

export type InvoiceTemplateId = 'CLASSIC' | 'MODERN' | 'COMPACT';

export interface InvoiceTemplateConfig {
  id: string;
  template_id: InvoiceTemplateId;
  primary_color: string;
  secondary_color: string;
  accent_color: string;
  text_color: string;
  table_header_color: string;
  logo_data_uri: string | null;
  show_logo: boolean;
  show_business_address: boolean;
  show_gstin: boolean;
  show_customer_gstin: boolean;
  show_hsn: boolean;
  show_discount: boolean;
  show_tax_breakup: boolean;
  show_bank_details: boolean;
  show_terms: boolean;
  show_amount_in_words: boolean;
  show_round_off: boolean;
  terms_text: string | null;
  bank_name: string | null;
  bank_account_name: string | null;
  bank_account_number: string | null;
  bank_ifsc: string | null;
  bank_upi_id: string | null;
  row_version: number;
}

export type InvoiceTemplateConfigUpdate = Omit<InvoiceTemplateConfig, 'id' | 'logo_data_uri' | 'row_version'> & {
  expected_row_version: number;
};

export async function getInvoiceTemplateConfig(): Promise<InvoiceTemplateConfig> {
  return apiRequest<InvoiceTemplateConfig>('/configuration/invoice-template-config');
}

export async function updateInvoiceTemplateConfig(payload: InvoiceTemplateConfigUpdate): Promise<InvoiceTemplateConfig> {
  return apiRequest<InvoiceTemplateConfig>('/configuration/invoice-template-config', { method: 'PUT', body: payload });
}


async function uploadFile(path: string, method: 'POST' | 'DELETE', file?: File): Promise<InvoiceTemplateConfig> {
  const correlationId = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}`;
  const init: RequestInit = { method, credentials: 'include', headers: { 'X-Correlation-Id': correlationId } };
  if (file) {
    const form = new FormData();
    form.append('file', file);
    init.body = form;
  }
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const message = payload?.error?.message || `Request failed with status ${response.status}`;
    const error = new Error(message) as Error & { code?: string; status?: number };
    error.code = payload?.error?.code;
    error.status = response.status;
    throw error;
  }
  return payload.data as InvoiceTemplateConfig;
}

export async function uploadBusinessLogo(file: File): Promise<InvoiceTemplateConfig> {
  return uploadFile('/configuration/business-logo', 'POST', file);
}

export async function removeBusinessLogo(): Promise<InvoiceTemplateConfig> {
  return uploadFile('/configuration/business-logo', 'DELETE');
}
