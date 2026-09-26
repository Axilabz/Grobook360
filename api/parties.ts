import { apiRequest } from './client';

export type PartyType = 'customer' | 'supplier';

export interface PartyHeader {
  party_type: PartyType;
  id: string;
  code: string;
  name: string;
  status: string;
  gstin: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  city: string | null;
  state_code: string | null;
  pincode: string | null;
  credit_limit: string | null;
  payment_terms_days: number;
}

export interface PartyKpis {
  // Customer
  total_sales?: string;
  collected?: string;
  // Supplier
  total_purchases?: string;
  paid?: string;
  // Shared
  outstanding: string;
  invoice_count: number;
  order_count: number;
  last_transaction_date: string | null;
}

export interface PartyAging {
  current: string;
  days_1_30: string;
  days_31_60: string;
  days_61_90: string;
  days_90_plus: string;
  no_due_date: string;
}

export interface PartyTopProduct {
  product_id: string;
  sku: string;
  product_name: string;
  quantity: string;
  value: string;
  last_transaction_date: string | null;
}

export interface PartyPaymentHistoryItem {
  reference: string;
  date: string;
  amount: string;
  method: string;
  allocated_amount: string;
  unallocated_amount: string;
  status: string;
}

export interface PartyRecentTransaction {
  type: string;
  reference: string;
  date: string;
  amount: string | null;
  status: string;
}

export interface PartyProfile {
  header: PartyHeader;
  kpis: PartyKpis;
  outstanding_aging: PartyAging;
  top_products: PartyTopProduct[];
  payment_history: PartyPaymentHistoryItem[];
  recent_transactions: PartyRecentTransaction[];
}

export async function getPartyProfile(partyType: PartyType, partyId: string): Promise<PartyProfile> {
  return apiRequest<PartyProfile>(`/parties/${partyType}/${partyId}`);
}
