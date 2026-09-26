import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';

export type PaymentPartyType = 'CUSTOMER' | 'SUPPLIER';
export type PaymentMethod = 'CASH' | 'UPI' | 'BANK_TRANSFER' | 'CHEQUE';
export type PaymentStatus = 'DRAFT' | 'POSTED' | 'REVERSED';
export type ChequeStatus = 'PENDING' | 'CLEARED' | 'BOUNCED';

export const PAYMENT_METHODS: { value: PaymentMethod; label: string }[] = [
  { value: 'CASH', label: 'Cash' },
  { value: 'UPI', label: 'UPI' },
  { value: 'BANK_TRANSFER', label: 'Bank Transfer' },
  { value: 'CHEQUE', label: 'Cheque' },
];

export interface PaymentAllocationItem {
  id: string;
  invoice_id: string;
  invoice_type: 'SALES_INVOICE' | 'PURCHASE_INVOICE';
  invoice_number: string;
  allocated_amount: string;
}

export interface PaymentListItem {
  id: string;
  payment_number: string;
  party_type: PaymentPartyType;
  customer_id: string | null;
  supplier_id: string | null;
  party_name: string;
  payment_date: string;
  payment_method: PaymentMethod;
  amount: string;
  allocated_amount: string;
  unallocated_amount: string;
  status: PaymentStatus;
  cheque_status: ChequeStatus | null;
  created_by: string | null;
  created_by_name: string | null;
  updated_by_name: string | null;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface PaymentDetail extends PaymentListItem {
  reference_number: string | null;
  notes: string | null;
  client_transaction_id: string | null;
  cheque_number: string | null;
  cheque_date: string | null;
  cheque_bank_name: string | null;
  cleared_date: string | null;
  accounting_posting_reference: string | null;
  allocations: PaymentAllocationItem[];
}

export interface AllocationLineInput {
  invoice_id: string;
  allocated_amount: string;
}

export interface OutstandingInvoiceItem {
  invoice_id: string;
  invoice_number: string;
  invoice_date: string;
  invoice_total: string;
  paid_amount: string;
  outstanding_amount: string;
  payment_status: string;
}

export interface OutstandingInvoicesResponse {
  party_type: PaymentPartyType;
  party_id: string;
  party_name: string;
  invoices: OutstandingInvoiceItem[];
}

export interface ListPaymentsParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  payment_method?: string;
  customer_id?: string;
  supplier_id?: string;
  date_from?: string;
  date_to?: string;
  [key: string]: string | number | undefined;
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export interface CreatePaymentPayload {
  payment_date?: string | null;
  payment_method: PaymentMethod;
  amount: string;
  reference_number?: string | null;
  notes?: string | null;
  client_transaction_id?: string | null;
  cheque_number?: string | null;
  cheque_date?: string | null;
  cheque_bank_name?: string | null;
  allocations: AllocationLineInput[];
}

export interface UpdatePaymentPayload {
  payment_date?: string | null;
  payment_method?: PaymentMethod | null;
  amount?: string | null;
  reference_number?: string | null;
  notes?: string | null;
  cheque_number?: string | null;
  cheque_date?: string | null;
  cheque_bank_name?: string | null;
  allocations?: AllocationLineInput[] | null;
  expected_row_version: number;
}

// --- Customer Receipts ---

export async function listCustomerReceipts(params: ListPaymentsParams): Promise<ApiList<PaymentListItem>> {
  return apiRequestList<PaymentListItem>(`/customer-receipts${buildQuery(params)}`);
}

export async function getCustomerReceipt(paymentId: string): Promise<PaymentDetail> {
  return apiRequest<PaymentDetail>(`/customer-receipts/${paymentId}`);
}

export async function getCustomerOutstandingInvoices(customerId: string): Promise<OutstandingInvoicesResponse> {
  return apiRequest<OutstandingInvoicesResponse>(`/customer-receipts/outstanding-invoices?customer_id=${customerId}`);
}

export async function createCustomerReceipt(customerId: string, payload: CreatePaymentPayload): Promise<PaymentDetail> {
  return apiRequest<PaymentDetail>('/customer-receipts', {
    method: 'POST',
    body: { customer_id: customerId, ...payload },
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function updateCustomerReceipt(paymentId: string, payload: UpdatePaymentPayload): Promise<PaymentDetail> {
  return apiRequest<PaymentDetail>(`/customer-receipts/${paymentId}`, { method: 'PATCH', body: payload });
}

export async function postCustomerReceipt(paymentId: string, expectedRowVersion: number): Promise<PaymentDetail> {
  return apiRequest<PaymentDetail>(`/customer-receipts/${paymentId}/post`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function reverseCustomerReceipt(paymentId: string, expectedRowVersion: number): Promise<PaymentDetail> {
  return apiRequest<PaymentDetail>(`/customer-receipts/${paymentId}/reverse`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

export async function updateCustomerReceiptChequeStatus(
  paymentId: string, expectedRowVersion: number, chequeStatus: ChequeStatus, clearedDate?: string | null,
): Promise<PaymentDetail> {
  return apiRequest<PaymentDetail>(`/customer-receipts/${paymentId}/cheque-status`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion, cheque_status: chequeStatus, cleared_date: clearedDate ?? null },
  });
}

// --- Supplier Payments ---

export async function listSupplierPayments(params: ListPaymentsParams): Promise<ApiList<PaymentListItem>> {
  return apiRequestList<PaymentListItem>(`/supplier-payments${buildQuery(params)}`);
}

export async function getSupplierPayment(paymentId: string): Promise<PaymentDetail> {
  return apiRequest<PaymentDetail>(`/supplier-payments/${paymentId}`);
}

export async function getSupplierOutstandingInvoices(supplierId: string): Promise<OutstandingInvoicesResponse> {
  return apiRequest<OutstandingInvoicesResponse>(`/supplier-payments/outstanding-invoices?supplier_id=${supplierId}`);
}

export async function createSupplierPayment(supplierId: string, payload: CreatePaymentPayload): Promise<PaymentDetail> {
  return apiRequest<PaymentDetail>('/supplier-payments', {
    method: 'POST',
    body: { supplier_id: supplierId, ...payload },
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function updateSupplierPayment(paymentId: string, payload: UpdatePaymentPayload): Promise<PaymentDetail> {
  return apiRequest<PaymentDetail>(`/supplier-payments/${paymentId}`, { method: 'PATCH', body: payload });
}

export async function postSupplierPayment(paymentId: string, expectedRowVersion: number): Promise<PaymentDetail> {
  return apiRequest<PaymentDetail>(`/supplier-payments/${paymentId}/post`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function reverseSupplierPayment(paymentId: string, expectedRowVersion: number): Promise<PaymentDetail> {
  return apiRequest<PaymentDetail>(`/supplier-payments/${paymentId}/reverse`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion },
  });
}

export async function updateSupplierPaymentChequeStatus(
  paymentId: string, expectedRowVersion: number, chequeStatus: ChequeStatus, clearedDate?: string | null,
): Promise<PaymentDetail> {
  return apiRequest<PaymentDetail>(`/supplier-payments/${paymentId}/cheque-status`, {
    method: 'POST',
    body: { expected_row_version: expectedRowVersion, cheque_status: chequeStatus, cleared_date: clearedDate ?? null },
  });
}
