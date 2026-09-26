import React, { useState, useEffect, useCallback } from 'react';
import {
  Search, X, Loader2, ChevronLeft, ChevronRight, Eye, Gauge, ListChecks,
  FileText, FileSpreadsheet, Scale, AlertTriangle, CheckCircle2, Info,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { ApiError } from '../api/client';
import {
  GstTransactionListItem, GstTransactionDetail, GstDashboard, Gstr1Dataset, Gstr3bDataset,
  ValidationResult, ReconciliationResult,
  listGstTransactions, getGstTransaction, getGstDashboard, getGstr1, validateGstr1, getGstr3b, validateGstr3b, getGstReconciliation,
} from '../api/gst';

function currentReturnPeriod(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

const SOURCE_TYPES = ['SALES_INVOICE', 'PURCHASE_INVOICE', 'SALES_RETURN', 'PURCHASE_RETURN', 'CREDIT_NOTE', 'DEBIT_NOTE'];

const SEVERITY_STYLE: Record<string, string> = {
  ERROR: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  WARNING: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  INFO: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
};

type Tab = 'dashboard' | 'transactions' | 'gstr1' | 'gstr3b' | 'reconciliation';

const StatCard: React.FC<{ label: string; value: string; tone?: 'default' | 'positive' | 'negative' }> = ({ label, value, tone = 'default' }) => (
  <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
    <p className="text-[12px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{label}</p>
    <p className={`text-[22px] font-semibold mt-1 ${tone === 'positive' ? 'text-green-600' : tone === 'negative' ? 'text-red-600' : 'text-gray-900 dark:text-white'}`}>{value}</p>
  </div>
);

const GstManagement: React.FC = () => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const canView = hasPermission('gst.view');
  const canPrepare = hasPermission('gst.prepare_returns');

  const [tab, setTab] = useState<Tab>('dashboard');
  const [returnPeriod, setReturnPeriod] = useState(currentReturnPeriod());

  // Dashboard
  const [dashboard, setDashboard] = useState<GstDashboard | null>(null);
  const [isLoadingDashboard, setIsLoadingDashboard] = useState(false);

  // Transactions
  const [items, setItems] = useState<GstTransactionListItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [search, setSearch] = useState('');
  const [sourceTypeFilter, setSourceTypeFilter] = useState('');
  const [directionFilter, setDirectionFilter] = useState('');
  const [isLoadingTxns, setIsLoadingTxns] = useState(true);
  const [viewingId, setViewingId] = useState<string | null>(null);

  // GSTR-1 / GSTR-3B / Reconciliation
  const [gstr1, setGstr1] = useState<Gstr1Dataset | null>(null);
  const [gstr3b, setGstr3b] = useState<Gstr3bDataset | null>(null);
  const [reconciliation, setReconciliation] = useState<ReconciliationResult | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [isLoadingReturn, setIsLoadingReturn] = useState(false);
  const [isValidating, setIsValidating] = useState(false);

  const fetchDashboard = useCallback(async () => {
    setIsLoadingDashboard(true);
    try {
      setDashboard(await getGstDashboard(returnPeriod));
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load GST dashboard.', 'error');
    } finally {
      setIsLoadingDashboard(false);
    }
  }, [returnPeriod, showToast]);

  useEffect(() => { if (tab === 'dashboard' && canView) fetchDashboard(); }, [tab, canView, fetchDashboard]);

  const fetchTransactions = useCallback(async () => {
    setIsLoadingTxns(true);
    try {
      const result = await listGstTransactions({
        page, page_size: 10, source_type: sourceTypeFilter || undefined, direction: directionFilter || undefined,
      });
      const filtered = search
        ? result.data.filter((t) => (t.source_number || '').toLowerCase().includes(search.toLowerCase()) || (t.party_name || '').toLowerCase().includes(search.toLowerCase()))
        : result.data;
      setItems(filtered);
      setTotalPages(result.pagination.total_pages || 1);
      setTotalItems(result.pagination.total_items);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load GST transactions.', 'error');
    } finally {
      setIsLoadingTxns(false);
    }
  }, [page, sourceTypeFilter, directionFilter, search, showToast]);

  useEffect(() => { if (tab === 'transactions' && canView) fetchTransactions(); }, [tab, page, sourceTypeFilter, directionFilter, canView]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (tab !== 'transactions') return;
    const timer = setTimeout(() => { setPage(1); fetchTransactions(); }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const fetchGstr1 = useCallback(async () => {
    setIsLoadingReturn(true);
    setValidation(null);
    try {
      setGstr1(await getGstr1(returnPeriod));
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load GSTR-1.', 'error');
    } finally {
      setIsLoadingReturn(false);
    }
  }, [returnPeriod, showToast]);

  const fetchGstr3b = useCallback(async () => {
    setIsLoadingReturn(true);
    setValidation(null);
    try {
      setGstr3b(await getGstr3b(returnPeriod));
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load GSTR-3B.', 'error');
    } finally {
      setIsLoadingReturn(false);
    }
  }, [returnPeriod, showToast]);

  const fetchReconciliation = useCallback(async () => {
    setIsLoadingReturn(true);
    try {
      setReconciliation(await getGstReconciliation(returnPeriod));
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Failed to load reconciliation.', 'error');
    } finally {
      setIsLoadingReturn(false);
    }
  }, [returnPeriod, showToast]);

  useEffect(() => { if (tab === 'gstr1' && canView) fetchGstr1(); }, [tab, canView, fetchGstr1]);
  useEffect(() => { if (tab === 'gstr3b' && canView) fetchGstr3b(); }, [tab, canView, fetchGstr3b]);
  useEffect(() => { if (tab === 'reconciliation' && canView) fetchReconciliation(); }, [tab, canView, fetchReconciliation]);

  const handleValidate = async (which: 'gstr1' | 'gstr3b') => {
    setIsValidating(true);
    try {
      const result = which === 'gstr1' ? await validateGstr1(returnPeriod) : await validateGstr3b(returnPeriod);
      setValidation(result);
      showToast(result.is_valid ? 'No blocking errors found.' : `${result.error_count} error(s) found — review before finalizing.`, result.is_valid ? 'success' : 'error');
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Validation failed.', 'error');
    } finally {
      setIsValidating(false);
    }
  };

  if (!canView) {
    return <div className="p-8 text-center text-gray-500 dark:text-gray-400">You do not have permission to view GST data.</div>;
  }

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-3">
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">GST Filing</h2>
          <div className="flex items-center gap-2">
            <label className="text-[13px] text-gray-500 dark:text-gray-400">Return Period</label>
            <input
              type="month" value={returnPeriod} onChange={(e) => setReturnPeriod(e.target.value)}
              className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[13px] px-3 py-1.5"
            />
          </div>
        </div>
        <div className="flex gap-2 border-b border-gray-100 dark:border-gray-800 -mb-4 overflow-x-auto">
          {([
            ['dashboard', 'Dashboard', <Gauge size={14} key="i" />],
            ['transactions', 'Transactions', <ListChecks size={14} key="i" />],
            ['gstr1', 'GSTR-1', <FileText size={14} key="i" />],
            ['gstr3b', 'GSTR-3B', <FileSpreadsheet size={14} key="i" />],
            ['reconciliation', 'Reconciliation', <Scale size={14} key="i" />],
          ] as [Tab, string, React.ReactNode][]).map(([key, label, icon]) => (
            <button key={key} onClick={() => setTab(key)} className={`flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium border-b-2 whitespace-nowrap ${tab === key ? 'border-[#0066ff] text-[#0066ff]' : 'border-transparent text-gray-500 dark:text-gray-400'}`}>
              {icon} {label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'dashboard' && (
        isLoadingDashboard || !dashboard ? (
          <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
            <StatCard label="Output GST" value={`₹${dashboard.output_gst}`} />
            <StatCard label="Input GST" value={`₹${dashboard.input_gst}`} />
            <StatCard label="Net GST Position" value={`₹${dashboard.net_gst_position}`} tone={Number(dashboard.net_gst_position) >= 0 ? 'negative' : 'positive'} />
            <StatCard label="Validation Errors" value={String(dashboard.validation_error_count)} tone={dashboard.validation_error_count > 0 ? 'negative' : 'positive'} />
            <StatCard label="B2B Sales" value={`₹${dashboard.b2b_sales}`} />
            <StatCard label="B2C Sales" value={`₹${dashboard.b2c_sales}`} />
            <StatCard label="Credit Notes" value={`₹${dashboard.credit_notes}`} />
            <StatCard label="Debit Notes" value={`₹${dashboard.debit_notes}`} />
          </div>
        )
      )}

      {tab === 'transactions' && (
        <>
          <div className="flex flex-col sm:flex-row gap-3 w-full mb-4">
            <div className="relative w-full sm:w-64">
              <input
                type="text" placeholder="Search document #, party…" value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500/50 text-[14px]"
              />
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            </div>
            <select value={sourceTypeFilter} onChange={(e) => { setSourceTypeFilter(e.target.value); setPage(1); }} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2">
              <option value="">All Document Types</option>
              {SOURCE_TYPES.map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
            </select>
            <select value={directionFilter} onChange={(e) => { setDirectionFilter(e.target.value); setPage(1); }} className="border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2">
              <option value="">All Directions</option>
              <option value="OUTWARD">Outward</option>
              <option value="INWARD">Inward</option>
            </select>
          </div>

          {isLoadingTxns ? (
            <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
          ) : items.length === 0 ? (
            <div className="text-center py-16 text-gray-500 dark:text-gray-400">No GST transactions found.</div>
          ) : (
            <>
              <div className="hidden md:block bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                      <tr>
                        {[
                          { label: 'Document #', align: 'text-left' }, { label: 'Date', align: 'text-right' }, { label: 'Type', align: 'text-left' },
                          { label: 'Party', align: 'text-left' }, { label: 'GSTIN', align: 'text-left' }, { label: 'Taxable', align: 'text-right' },
                          { label: 'CGST', align: 'text-right' }, { label: 'SGST', align: 'text-right' }, { label: 'IGST', align: 'text-right' },
                          { label: 'Total GST', align: 'text-right' }, { label: '', align: 'text-center' },
                        ].map((h) => (
                          <th key={h.label} className={`px-6 py-3 text-[12px] font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wider ${h.align}`}>{h.label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                      {items.map((t) => (
                        <tr key={t.id} className="hover:bg-blue-50 dark:hover:bg-gray-800 transition-colors">
                          <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap text-left">
                            <button onClick={() => setViewingId(t.id)} className="hover:text-[#0066ff] hover:underline">{t.source_number || '—'}</button>
                            {t.event_type === 'REVERSAL' && <span className="ml-1.5 text-[10px] text-amber-600">(reversal)</span>}
                          </td>
                          <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-right">{t.document_date}</td>
                          <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{t.source_type.replace(/_/g, ' ')} · {t.classification}</td>
                          <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{t.party_name || '—'}</td>
                          <td className="px-6 py-4 text-[13px] text-gray-500 dark:text-gray-400 whitespace-nowrap text-left">{t.party_gstin || '—'}</td>
                          <td className="px-6 py-4 text-[13px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">₹{t.taxable_value}</td>
                          <td className="px-6 py-4 text-[13px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">₹{t.cgst_amount}</td>
                          <td className="px-6 py-4 text-[13px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">₹{t.sgst_amount}</td>
                          <td className="px-6 py-4 text-[13px] text-gray-700 dark:text-gray-300 whitespace-nowrap text-right">₹{t.igst_amount}</td>
                          <td className="px-6 py-4 text-[14px] font-medium text-gray-900 dark:text-white whitespace-nowrap text-right">₹{t.total_gst}</td>
                          <td className="px-6 py-4 text-center whitespace-nowrap">
                            <button onClick={() => setViewingId(t.id)} className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400" title="View"><Eye size={16} /></button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="md:hidden space-y-3">
                {items.map((t) => (
                  <button key={t.id} onClick={() => setViewingId(t.id)} className="w-full text-left bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
                    <div className="flex items-start justify-between mb-2">
                      <div>
                        <p className="font-semibold text-gray-900 dark:text-white text-[15px]">{t.source_number || '—'}</p>
                        <p className="text-[13px] text-gray-500 dark:text-gray-400">{t.source_type.replace(/_/g, ' ')} · {t.classification} · {t.party_name || '—'}</p>
                      </div>
                      <span className="text-[12px] text-gray-500">{t.direction}</span>
                    </div>
                    <p className="text-[13px] text-gray-600 dark:text-gray-300">Taxable ₹{t.taxable_value} · GST ₹{t.total_gst} · {t.document_date}</p>
                  </button>
                ))}
              </div>

              <div className="flex items-center justify-between mt-4 px-1">
                <p className="text-[13px] text-gray-500 dark:text-gray-400">{totalItems} transaction{totalItems === 1 ? '' : 's'}</p>
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

      {tab === 'gstr1' && (
        isLoadingReturn || !gstr1 ? (
          <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
        ) : (
          <div className="space-y-4">
            {canPrepare && (
              <button onClick={() => handleValidate('gstr1')} disabled={isValidating} className="px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium disabled:opacity-60">
                {isValidating ? 'Validating…' : 'Validate GSTR-1'}
              </button>
            )}
            <ValidationPanel result={validation} />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <GstrBucketCard title="B2B Outward Supplies" bucket={gstr1.b2b} />
              <GstrBucketCard title="B2C Outward Supplies" bucket={gstr1.b2c} />
              <GstrBucketCard title="Credit Notes" bucket={gstr1.credit_notes} />
              <GstrBucketCard title="Debit Notes" bucket={gstr1.debit_notes} />
            </div>
            <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
              <p className="px-6 py-3 text-[14px] font-semibold text-gray-800 dark:text-gray-100 border-b border-gray-100 dark:border-gray-800">HSN/SAC Summary</p>
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-[13px]">
                  <thead className="bg-gray-50 dark:bg-gray-800">
                    <tr>{['HSN', 'Qty', 'Taxable', 'CGST', 'SGST', 'IGST'].map((h) => <th key={h} className="px-4 py-2 text-[11px] font-semibold text-gray-600 dark:text-gray-300 uppercase">{h}</th>)}</tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                    {gstr1.hsn_summary.map((e) => (
                      <tr key={e.hsn_code}>
                        <td className="px-4 py-2">{e.hsn_code}</td>
                        <td className="px-4 py-2">{e.quantity}</td>
                        <td className="px-4 py-2">₹{e.taxable_value}</td>
                        <td className="px-4 py-2">₹{e.cgst}</td>
                        <td className="px-4 py-2">₹{e.sgst}</td>
                        <td className="px-4 py-2">₹{e.igst}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )
      )}

      {tab === 'gstr3b' && (
        isLoadingReturn || !gstr3b ? (
          <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
        ) : (
          <div className="space-y-4">
            {canPrepare && (
              <button onClick={() => handleValidate('gstr3b')} disabled={isValidating} className="px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium disabled:opacity-60">
                {isValidating ? 'Validating…' : 'Validate GSTR-3B'}
              </button>
            )}
            <ValidationPanel result={validation} />
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard label="Outward Taxable Supplies" value={`₹${gstr3b.outward_taxable_supplies.taxable_value}`} />
              <StatCard label="Output CGST" value={`₹${gstr3b.output_cgst}`} />
              <StatCard label="Output SGST" value={`₹${gstr3b.output_sgst}`} />
              <StatCard label="Output IGST" value={`₹${gstr3b.output_igst}`} />
              <StatCard label="Inward Supplies" value={`₹${gstr3b.inward_supplies.taxable_value}`} />
              <StatCard label="Input Tax Credit CGST" value={`₹${gstr3b.input_tax_credit_cgst}`} />
              <StatCard label="Input Tax Credit SGST" value={`₹${gstr3b.input_tax_credit_sgst}`} />
              <StatCard label="Input Tax Credit IGST" value={`₹${gstr3b.input_tax_credit_igst}`} />
              <StatCard label="Net GST Payable" value={`₹${gstr3b.net_gst_payable}`} tone={Number(gstr3b.net_gst_payable) >= 0 ? 'negative' : 'positive'} />
            </div>
          </div>
        )
      )}

      {tab === 'reconciliation' && (
        isLoadingReturn || !reconciliation ? (
          <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
        ) : (
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6 space-y-4 text-[14px]">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-center">
              <div><p className="text-[12px] text-gray-500 uppercase">GST Engine Output GST</p><p className="text-[18px] font-semibold text-gray-900 dark:text-white">₹{reconciliation.gst_engine_output_gst}</p></div>
              <div><p className="text-[12px] text-gray-500 uppercase">Accounting Output GST</p><p className="text-[18px] font-semibold text-gray-900 dark:text-white">₹{reconciliation.accounting_output_gst}</p></div>
              <div>
                <p className="text-[12px] text-gray-500 uppercase">Difference</p>
                <p className={`text-[18px] font-semibold ${Number(reconciliation.output_gst_difference) === 0 ? 'text-green-600' : 'text-red-600'}`}>₹{reconciliation.output_gst_difference}</p>
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-center pt-4 border-t border-gray-100 dark:border-gray-800">
              <div><p className="text-[12px] text-gray-500 uppercase">GST Engine Input GST</p><p className="text-[18px] font-semibold text-gray-900 dark:text-white">₹{reconciliation.gst_engine_input_gst}</p></div>
              <div><p className="text-[12px] text-gray-500 uppercase">Accounting Input GST</p><p className="text-[18px] font-semibold text-gray-900 dark:text-white">₹{reconciliation.accounting_input_gst}</p></div>
              <div>
                <p className="text-[12px] text-gray-500 uppercase">Difference</p>
                <p className={`text-[18px] font-semibold ${Number(reconciliation.input_gst_difference) === 0 ? 'text-green-600' : 'text-red-600'}`}>₹{reconciliation.input_gst_difference}</p>
              </div>
            </div>
          </div>
        )
      )}

      {viewingId && <GstTransactionModal transactionId={viewingId} onClose={() => setViewingId(null)} />}
    </div>
  );
};

const GstrBucketCard: React.FC<{ title: string; bucket: { count: number; totals: { taxable_value: string; cgst: string; sgst: string; igst: string } } }> = ({ title, bucket }) => (
  <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
    <div className="flex items-center justify-between mb-2">
      <p className="text-[14px] font-semibold text-gray-800 dark:text-gray-100">{title}</p>
      <span className="text-[12px] text-gray-500 dark:text-gray-400">{bucket.count} document{bucket.count === 1 ? '' : 's'}</span>
    </div>
    <div className="grid grid-cols-2 gap-2 text-[13px] text-gray-600 dark:text-gray-300">
      <span>Taxable: ₹{bucket.totals.taxable_value}</span>
      <span>CGST: ₹{bucket.totals.cgst}</span>
      <span>SGST: ₹{bucket.totals.sgst}</span>
      <span>IGST: ₹{bucket.totals.igst}</span>
    </div>
  </div>
);

const ValidationPanel: React.FC<{ result: ValidationResult | null }> = ({ result }) => {
  if (!result) return null;
  if (result.issues.length === 0) {
    return (
      <div className="flex items-center gap-2 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg px-4 py-3 text-[13px] text-green-700 dark:text-green-400">
        <CheckCircle2 size={16} /> No validation issues found for this period.
      </div>
    );
  }
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <p className="px-4 py-3 text-[13px] font-semibold text-gray-800 dark:text-gray-100 border-b border-gray-100 dark:border-gray-800">
        {result.error_count} error{result.error_count === 1 ? '' : 's'}, {result.warning_count} warning{result.warning_count === 1 ? '' : 's'}
      </p>
      <div className="divide-y divide-gray-100 dark:divide-gray-800">
        {result.issues.map((issue, idx) => (
          <div key={idx} className="px-4 py-3 flex items-start gap-3">
            <span className={`shrink-0 mt-0.5 inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${SEVERITY_STYLE[issue.severity]}`}>{issue.severity}</span>
            <div className="min-w-0">
              <p className="text-[13px] text-gray-800 dark:text-gray-200">{issue.message}</p>
              <p className="text-[12px] text-gray-500 dark:text-gray-400">{issue.suggested_action}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const GstTransactionModal: React.FC<{ transactionId: string; onClose: () => void }> = ({ transactionId, onClose }) => {
  const { showToast } = useToast();
  const [txn, setTxn] = useState<GstTransactionDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setIsLoading(true);
      try {
        setTxn(await getGstTransaction(transactionId));
      } catch {
        showToast('Failed to load GST transaction.', 'error');
      } finally {
        setIsLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transactionId]);

  if (isLoading || !txn) {
    return (
      <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
        <Loader2 size={28} className="animate-spin text-white" />
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <div>
            <h3 className="text-[18px] font-semibold text-gray-800 dark:text-gray-100">{txn.source_number || txn.source_type}</h3>
            <p className="text-[13px] text-gray-500 dark:text-gray-400">{txn.source_type.replace(/_/g, ' ')} · {txn.classification} · {txn.direction}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={20} /></button>
        </div>

        <div className="p-6 space-y-5 text-[14px]">
          <div className="flex items-center gap-2 flex-wrap text-gray-500 dark:text-gray-400">
            <span>Date: {txn.document_date}</span><span>· Return Period: {txn.return_period}</span>
            {txn.party_gstin && <span>· GSTIN: {txn.party_gstin}</span>}
            {txn.event_type === 'REVERSAL' && <span className="text-amber-600">(reversal)</span>}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-gray-500 dark:text-gray-400 uppercase text-[11px]">
                  <th className="py-2 pr-2">HSN</th><th className="py-2 pr-2">Qty</th><th className="py-2 pr-2">Taxable</th>
                  <th className="py-2 pr-2">CGST</th><th className="py-2 pr-2">SGST</th><th className="py-2">IGST</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {txn.lines.map((line) => (
                  <tr key={line.line_no}>
                    <td className="py-2 pr-2">{line.hsn_code || '—'}</td>
                    <td className="py-2 pr-2">{line.quantity}</td>
                    <td className="py-2 pr-2">₹{line.taxable_value}</td>
                    <td className="py-2 pr-2">₹{line.cgst_amount}</td>
                    <td className="py-2 pr-2">₹{line.sgst_amount}</td>
                    <td className="py-2">₹{line.igst_amount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="bg-gray-50 dark:bg-gray-900 rounded-md p-4 space-y-1 border border-gray-200 dark:border-gray-700">
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Taxable Value</span><span>₹{txn.taxable_value}</span></div>
            <div className="flex justify-between text-gray-500 dark:text-gray-400"><span>Total GST</span><span>₹{txn.total_gst}</span></div>
            <div className="flex justify-between font-semibold pt-1 border-t border-gray-100 dark:border-gray-700 text-gray-900 dark:text-white"><span>Total Amount</span><span>₹{txn.total_amount}</span></div>
          </div>

          <div className="flex items-start gap-2 text-[12px] text-gray-400">
            <Info size={14} className="shrink-0 mt-0.5" /> This snapshot is immutable — it reflects the GST rate/values at the time this document was posted, regardless of later master-data changes.
          </div>
        </div>
      </div>
    </div>
  );
};

export default GstManagement;
