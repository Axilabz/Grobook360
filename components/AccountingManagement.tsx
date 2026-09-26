import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, X, Loader2, AlertTriangle, Ban, ChevronLeft, ChevronRight,
  Eye, BookOpen, Landmark, ListTree,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { ApiError } from '../api/client';
import {
  JournalListItem, JournalDetail, ChartOfAccountItem, AccountMappingItem,
  listJournals, getJournal, reverseJournal, listChartOfAccounts, listAccountMappings,
} from '../api/accounting';

const STATUS_BADGE: Record<string, string> = {
  DRAFT: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  POSTED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  REVERSED: 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400',
};

const SOURCE_TYPES = [
  'SALES_INVOICE', 'PURCHASE_INVOICE', 'CUSTOMER_RECEIPT', 'SUPPLIER_PAYMENT',
  'SALES_RETURN', 'PURCHASE_RETURN', 'CREDIT_NOTE', 'DEBIT_NOTE',
];

type Tab = 'journals' | 'accounts' | 'mappings';

const AccountingManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const canViewJournals = hasPermission('accounting.view_journals');
  const canViewAccounts = hasPermission('accounting.view_chart_of_accounts');
  const canViewMappings = hasPermission('accounting.manage_account_mappings');
  const canReverse = hasPermission('accounting.reverse_journal');

  const [tab, setTab] = useState<Tab>('journals');

  const [items, setItems] = useState<JournalListItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [sourceTypeFilter, setSourceTypeFilter] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [viewingId, setViewingId] = useState<string | null>(null);

  const [accounts, setAccounts] = useState<ChartOfAccountItem[]>([]);
  const [mappings, setMappings] = useState<AccountMappingItem[]>([]);
  const [isLoadingAccounts, setIsLoadingAccounts] = useState(false);

  const fetchJournals = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listJournals({ page, page_size: 10, status: statusFilter || undefined, source_type: sourceTypeFilter || undefined });
      const filtered = search
        ? result.data.filter((j) => j.journal_number.toLowerCase().includes(search.toLowerCase()) || (j.source_number || '').toLowerCase().includes(search.toLowerCase()))
        : result.data;
      setItems(filtered);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load journals.', 'error');
    } finally {
      setIsLoading(false);
    }
  }, [page, statusFilter, sourceTypeFilter, search, showToast]);

  useEffect(() => { if (tab === 'journals' && canViewJournals) fetchJournals(); }, [tab, page, statusFilter, sourceTypeFilter, canViewJournals]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (tab !== 'journals') return;
    const timer = setTimeout(() => { setPage(1); fetchJournals(); }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const fetchAccounts = useCallback(async () => {
    setIsLoadingAccounts(true);
    try {
      const [accountsResult, mappingsResult] = await Promise.all([listChartOfAccounts(), listAccountMappings()]);
      setAccounts(accountsResult);
      setMappings(mappingsResult);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load Chart of Accounts.', 'error');
    } finally {
      setIsLoadingAccounts(false);
    }
  }, [showToast]);

  useEffect(() => { if ((tab === 'accounts' || tab === 'mappings') && accounts.length === 0) fetchAccounts(); }, [tab, accounts.length, fetchAccounts]);

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 shadow-sm">
        <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight mb-3">Accounting</h2>
        <div className="flex gap-2 border-b border-gray-100 dark:border-gray-800 -mb-4">
          {canViewJournals && (
            <button onClick={() => setTab('journals')} className={`flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium border-b-2 ${tab === 'journals' ? 'border-[#0066ff] text-[#0066ff]' : 'border-transparent text-gray-500 dark:text-gray-400'}`}>
              <BookOpen size={14} /> Journals
            </button>
          )}
          {canViewAccounts && (
            <button onClick={() => setTab('accounts')} className={`flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium border-b-2 ${tab === 'accounts' ? 'border-[#0066ff] text-[#0066ff]' : 'border-transparent text-gray-500 dark:text-gray-400'}`}>
              <Landmark size={14} /> Chart of Accounts
            </button>
          )}
          {canViewMappings && (
            <button onClick={() => setTab('mappings')} className={`flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium border-b-2 ${tab === 'mappings' ? 'border-[#0066ff] text-[#0066ff]' : 'border-transparent text-gray-500 dark:text-gray-400'}`}>
              <ListTree size={14} /> Account Mappings
            </button>
          )}
        </div>
      </div>

      {tab === 'journals' && canViewJournals && (
        <>
          <div className="flex flex-col sm:flex-row gap-3 w-full mb-4">
            <div className="relative w-full sm:w-64">
              <input
                type="text" placeholder="Search journal #, source #…" value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500/50 text-[14px]"
              />
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            </div>
            <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2">
              <option value="">All Statuses</option>
              {['DRAFT', 'POSTED', 'REVERSED'].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select value={sourceTypeFilter} onChange={(e) => { setSourceTypeFilter(e.target.value); setPage(1); }} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2">
              <option value="">All Sources</option>
              {SOURCE_TYPES.map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
            </select>
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
          ) : items.length === 0 ? (
            <div className="text-center py-16 text-gray-500 dark:text-gray-400">No journals found.</div>
          ) : (
            <>
              <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                      <tr>
                        {[
                          { label: 'Journal #', align: 'text-left' }, { label: 'Date', align: 'text-right' }, { label: 'Posting Date', align: 'text-right' },
                          { label: 'Source', align: 'text-left' }, { label: 'Source #', align: 'text-left' }, { label: 'Description', align: 'text-left' },
                          { label: 'Debit', align: 'text-right' }, { label: 'Credit', align: 'text-right' }, { label: 'Status', align: 'text-left' },
                          { label: 'Actions', align: 'text-center' },
                        ].map((h) => (
                          <th key={h.label} className={`px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider ${h.align}`}>{h.label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                      {items.map((j) => (
                        <tr key={j.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                          <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap text-left">
                            <button onClick={() => setViewingId(j.id)} className="hover:text-[#0066ff] hover:underline">{j.journal_number}</button>
                            {j.posting_event_type === 'REVERSAL' && <span className="ml-1.5 text-[10px] text-amber-600">(reversal)</span>}
                          </td>
                          <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-right">{j.journal_date}</td>
                          <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-right">{j.posting_date}</td>
                          <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{j.source_type.replace(/_/g, ' ')}</td>
                          <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{j.source_number || '—'}</td>
                          <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{j.description || '—'}</td>
                          <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">₹{j.total_debit}</td>
                          <td className="px-6 py-4 text-[14px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">₹{j.total_credit}</td>
                          <td className="px-6 py-4 whitespace-nowrap text-left">
                            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[j.status]}`}>{j.status}</span>
                          </td>
                          <td className="px-6 py-4 text-center whitespace-nowrap">
                            <button onClick={() => setViewingId(j.id)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="View">
                              <Eye size={16} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="md:hidden space-y-3">
                {items.map((j) => (
                  <button key={j.id} onClick={() => setViewingId(j.id)} className="w-full text-left bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
                    <div className="flex items-start justify-between mb-2">
                      <div>
                        <p className="font-semibold text-gray-900 dark:text-white text-[15px]">{j.journal_number}</p>
                        <p className="text-[13px] text-gray-500 dark:text-gray-400">{j.source_type.replace(/_/g, ' ')} {j.source_number ? `· ${j.source_number}` : ''}</p>
                      </div>
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[j.status]}`}>{j.status}</span>
                    </div>
                    <p className="text-[13px] text-gray-600 dark:text-gray-300">Dr ₹{j.total_debit} · Cr ₹{j.total_credit} · {j.journal_date}</p>
                  </button>
                ))}
              </div>

              <div className="flex items-center justify-between mt-4 px-1">
                <p className="text-[13px] text-gray-500 dark:text-gray-400">{totalItems} journal{totalItems === 1 ? '' : 's'}</p>
                <div className="flex items-center gap-2">
                  <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronLeft size={16} /></button>
                  <span className="text-[13px] text-gray-600 dark:text-gray-400">Page {page} of {totalPages}</span>
                  <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="p-2 rounded-md border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-600 dark:text-gray-300"><ChevronRight size={16} /></button>
                </div>
              </div>
            </>
          )}
        </>
      )}

      {tab === 'accounts' && canViewAccounts && (
        isLoadingAccounts ? (
          <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
        ) : (
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    {['Code', 'Name', 'Type', 'Status'].map((h) => (
                      <th key={h} className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider text-left">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {accounts.map((a) => (
                    <tr key={a.id}>
                      <td className="px-6 py-3 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{a.code}</td>
                      <td className="px-6 py-3 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap text-left">{a.name}</td>
                      <td className="px-6 py-3 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{a.account_type}</td>
                      <td className="px-6 py-3 text-[13px] whitespace-nowrap text-left">{a.is_active ? <span className="text-green-600">Active</span> : <span className="text-gray-400">Inactive</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="px-6 py-3 text-[12px] text-gray-400 border-t border-gray-100 dark:border-gray-800">
              This is a default, editable starting Chart of Accounts — not an approved final COA. Editing is not yet available in this screen.
            </p>
          </div>
        )
      )}

      {tab === 'mappings' && canViewMappings && (
        isLoadingAccounts ? (
          <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
        ) : (
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    {['Posting Rule', 'Mapped Account'].map((h) => (
                      <th key={h} className="px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider text-left">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {mappings.map((m) => (
                    <tr key={m.posting_rule_code}>
                      <td className="px-6 py-3 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{m.posting_rule_code.replace(/_/g, ' ')}</td>
                      <td className="px-6 py-3 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap text-left">{m.account_code} — {m.account_name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      )}

      {viewingId && (
        <JournalDetailModal journalId={viewingId} onClose={() => setViewingId(null)} onChanged={fetchJournals} canReverse={canReverse} />
      )}
    </div>
  );
};

const JournalDetailModal: React.FC<{ journalId: string; onClose: () => void; onChanged: () => void; canReverse: boolean }> = ({
  journalId, onClose, onChanged, canReverse,
}) => {
  const { showToast } = useToast();
  const [journal, setJournal] = useState<JournalDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [confirmReverse, setConfirmReverse] = useState(false);
  const [isActing, setIsActing] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      setJournal(await getJournal(journalId));
    } catch {
      showToast('Failed to load journal.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [journalId]);

  useEffect(() => { load(); }, [load]);

  const handleReverse = async () => {
    setIsActing(true);
    try {
      await reverseJournal(journalId);
      showToast('Journal reversed.', 'success');
      await load();
      onChanged();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Something went wrong.', 'error');
    } finally {
      setIsActing(false);
      setConfirmReverse(false);
    }
  };

  if (isLoading || !journal) {
    return (
      <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
        <Loader2 size={28} className="animate-spin text-white" />
      </div>
    );
  }

  const totalDebit = journal.lines.reduce((sum, l) => sum + Number(l.debit_amount), 0);
  const totalCredit = journal.lines.reduce((sum, l) => sum + Number(l.credit_amount), 0);
  const isBalanced = Math.abs(totalDebit - totalCredit) < 0.005;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <div>
            <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{journal.journal_number}</h3>
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{journal.source_type.replace(/_/g, ' ')} {journal.source_number ? `· ${journal.source_number}` : ''}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>

        <div className="p-6 space-y-5 text-[14px]">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[journal.status]}`}>{journal.status}</span>
            <span className="text-gray-500 dark:text-gray-400">Journal Date: {journal.journal_date}</span>
            <span className="text-gray-500 dark:text-gray-400">· Posting Date: {journal.posting_date}</span>
            {journal.reversal_of_journal_id && <span className="text-amber-600 text-[12px]">Reverses another journal</span>}
          </div>

          {journal.description && <p className="text-gray-600 dark:text-gray-300">{journal.description}</p>}

          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                  <th className="py-2 pr-2">Account</th><th className="py-2 pr-2">Description</th><th className="py-2 pr-2">Debit</th><th className="py-2">Credit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {journal.lines.map((line) => (
                  <tr key={line.id}>
                    <td className="py-2 pr-2">{line.account_code} — {line.account_name}</td>
                    <td className="py-2 pr-2 text-gray-500">{line.description || '—'}</td>
                    <td className="py-2 pr-2">{Number(line.debit_amount) > 0 ? `₹${line.debit_amount}` : '—'}</td>
                    <td className="py-2">{Number(line.credit_amount) > 0 ? `₹${line.credit_amount}` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="bg-gray-50 dark:bg-gray-900 rounded-md p-4 space-y-1 border border-gray-200 dark:border-gray-700">
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Total Debit</span><span>₹{totalDebit.toFixed(2)}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Total Credit</span><span>₹{totalCredit.toFixed(2)}</span></div>
            <div className={`flex justify-between font-semibold pt-1 border-t border-gray-100 dark:border-gray-700 ${isBalanced ? 'text-green-600' : 'text-red-600'}`}>
              <span>Balance Status</span><span>{isBalanced ? 'Balanced' : 'UNBALANCED'}</span>
            </div>
          </div>

          {canReverse && journal.status === 'POSTED' && (
            <button disabled={isActing} onClick={() => setConfirmReverse(true)} className="flex items-center gap-1.5 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[13px] font-medium">
              <Ban size={14} /> Reverse Journal
            </button>
          )}
        </div>
      </div>

      {confirmReverse && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full shrink-0 bg-amber-100 dark:bg-amber-900/30">
                <AlertTriangle size={20} className="text-amber-600 dark:text-amber-400" />
              </div>
              <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">Reverse Journal</h3>
            </div>
            <p className="text-[14px] text-gray-600 dark:text-gray-300 mb-6">
              This creates a new journal with debit/credit swapped, referencing this one. The original journal is never edited — only its status changes to REVERSED.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => setConfirmReverse(false)} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Back</button>
              <button onClick={handleReverse} className="py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium">Confirm</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AccountingManagement;
