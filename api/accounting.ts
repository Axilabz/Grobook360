import { apiRequest, apiRequestList } from './client';
import type { ApiList } from './envelopes';

export interface JournalLineItem {
  id: string;
  account_id: string;
  account_code: string;
  account_name: string;
  debit_amount: string;
  credit_amount: string;
  description: string | null;
}

export interface JournalListItem {
  id: string;
  journal_number: string;
  journal_date: string;
  posting_date: string;
  source_type: string;
  source_id: string;
  source_number: string | null;
  posting_event_type: 'ORIGINAL' | 'REVERSAL';
  description: string | null;
  status: 'DRAFT' | 'POSTED' | 'REVERSED';
  reversal_of_journal_id: string | null;
  total_debit: string;
  total_credit: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  row_version: number;
}

export interface JournalDetail extends JournalListItem {
  currency: string;
  lines: JournalLineItem[];
}

export interface ChartOfAccountItem {
  id: string;
  code: string;
  name: string;
  account_type: string;
  is_active: boolean;
  is_system_default: boolean;
}

export interface AccountMappingItem {
  posting_rule_code: string;
  account_id: string;
  account_code: string;
  account_name: string;
}

export interface PostingRuleItem {
  code: string;
  description: string;
}

export interface ListJournalsParams {
  page?: number;
  page_size?: number;
  source_type?: string;
  status?: string;
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

export async function listJournals(params: ListJournalsParams): Promise<ApiList<JournalListItem>> {
  return apiRequestList<JournalListItem>(`/accounting/journals${buildQuery(params)}`);
}

export async function getJournal(journalId: string): Promise<JournalDetail> {
  return apiRequest<JournalDetail>(`/accounting/journals/${journalId}`);
}

export async function reverseJournal(journalId: string): Promise<JournalDetail> {
  return apiRequest<JournalDetail>(`/accounting/journals/${journalId}/reverse`, { method: 'POST', body: {} });
}

export async function listChartOfAccounts(): Promise<ChartOfAccountItem[]> {
  return apiRequest<ChartOfAccountItem[]>('/accounting/accounts');
}

export async function listAccountMappings(): Promise<AccountMappingItem[]> {
  return apiRequest<AccountMappingItem[]>('/accounting/account-mappings');
}

export async function listPostingRules(): Promise<PostingRuleItem[]> {
  return apiRequest<PostingRuleItem[]>('/accounting/posting-rules');
}
