import React, { useState, useEffect, useCallback } from 'react';
import {
  Loader2, RefreshCw, X, AlertTriangle, CheckCircle2, Clock, Ban, WifiOff, Info, PlusCircle,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { dbGetAllByTenant, STORE_SYNC_QUEUE, hasUnsyncedTransactions } from '../pwa/offlineDb';
import { runSync, retryItem, cancelQueueItem } from '../pwa/syncEngine';
import { refreshMasterData } from '../pwa/masterDataCache';
import { isBrowserOnline } from '../pwa/connectivity';
import { SyncQueueItem, SyncStatus } from '../pwa/offlineTypes';
import OfflineInvoiceCapture from './OfflineInvoiceCapture';

const STATUS_META: Record<SyncStatus, { label: string; className: string; icon: React.ReactNode }> = {
  LOCAL_DRAFT: { label: 'Draft', className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400', icon: <Clock size={12} /> },
  PENDING_SYNC: { label: 'Pending Sync', className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400', icon: <Clock size={12} /> },
  SYNCING: { label: 'Syncing', className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400', icon: <RefreshCw size={12} className="animate-spin" /> },
  SYNCED: { label: 'Synced', className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400', icon: <CheckCircle2 size={12} /> },
  SYNC_FAILED: { label: 'Failed', className: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400', icon: <AlertTriangle size={12} /> },
  CONFLICT: { label: 'Conflict', className: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400', icon: <AlertTriangle size={12} /> },
  REQUIRES_ACTION: { label: 'Action Required', className: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400', icon: <AlertTriangle size={12} /> },
};

const FILTERS: { key: string; label: string; statuses: SyncStatus[] }[] = [
  { key: 'all', label: 'All', statuses: [] },
  { key: 'pending', label: 'Pending', statuses: ['PENDING_SYNC', 'SYNCING'] },
  { key: 'synced', label: 'Synced', statuses: ['SYNCED'] },
  { key: 'failed', label: 'Failed', statuses: ['SYNC_FAILED'] },
  { key: 'conflicts', label: 'Conflicts', statuses: ['CONFLICT'] },
  { key: 'action', label: 'Requires Action', statuses: ['REQUIRES_ACTION'] },
];

const SyncCenter: React.FC = () => {
  const { currentTenant, currentUser } = useAuth();
  const { showToast } = useToast();
  const [items, setItems] = useState<SyncQueueItem[]>([]);
  const [filter, setFilter] = useState('all');
  const [isLoading, setIsLoading] = useState(true);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isRefreshingMasterData, setIsRefreshingMasterData] = useState(false);
  const [reviewing, setReviewing] = useState<SyncQueueItem | null>(null);
  const [showCapture, setShowCapture] = useState(false);

  const load = useCallback(async () => {
    if (!currentTenant) return;
    setIsLoading(true);
    try {
      const rows = await dbGetAllByTenant<SyncQueueItem>(STORE_SYNC_QUEUE, currentTenant.id);
      rows.sort((a, b) => b.created_at.localeCompare(a.created_at));
      setItems(rows);
    } catch {
      showToast('Offline storage is not available in this browser.', 'error');
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentTenant]);

  useEffect(() => { load(); }, [load]);

  const handleSyncNow = async () => {
    if (!currentTenant) return;
    setIsSyncing(true);
    try {
      const result = await runSync(currentTenant.id);
      if (result === null) {
        showToast("You're offline. Connect to the internet to sync.", 'error');
      } else {
        showToast(`Synced ${result.synced} of ${result.attempted} pending transaction(s).`, result.failed + result.conflicts === 0 ? 'success' : 'error');
      }
    } finally {
      setIsSyncing(false);
      await load();
    }
  };

  const handleRefreshMasterData = async () => {
    if (!currentTenant || !isBrowserOnline()) {
      showToast("You're offline. This action requires an internet connection.", 'error');
      return;
    }
    setIsRefreshingMasterData(true);
    try {
      const counts = await refreshMasterData(currentTenant.id);
      showToast(`Cached ${counts.products} products, ${counts.customers} customers, ${counts.suppliers} suppliers for offline use.`, 'success');
    } catch {
      showToast('Failed to refresh offline master data.', 'error');
    } finally {
      setIsRefreshingMasterData(false);
    }
  };

  const handleRetry = async (item: SyncQueueItem) => {
    try {
      const result = await retryItem(item);
      if (result.status === 'SYNCED') showToast(`${item.local_reference} synced successfully.`, 'success');
      else if (result.status === 'CONFLICT') showToast(`${item.local_reference} has a conflict — review required.`, 'error');
      else showToast(`${item.local_reference} could not be synced yet.`, 'error');
    } finally {
      await load();
    }
  };

  const handleCancel = async (item: SyncQueueItem) => {
    try {
      await cancelQueueItem(item);
      showToast(`${item.local_reference} cancelled.`, 'success');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Could not cancel this transaction.', 'error');
    } finally {
      await load();
    }
  };

  const filtered = FILTERS.find((f) => f.key === filter)?.statuses.length
    ? items.filter((i) => FILTERS.find((f) => f.key === filter)!.statuses.includes(i.status))
    : items;

  const entityLabel = (t: string) => (t === 'SALES_INVOICE' ? 'Sales Invoice' : t === 'CUSTOMER' ? 'Customer' : 'Supplier');

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-3">
          <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">Sync Center</h2>
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => setShowCapture(true)} className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 text-[13px] font-medium">
              <PlusCircle size={14} /> New Offline Invoice
            </button>
            <button onClick={handleRefreshMasterData} disabled={isRefreshingMasterData} className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 text-[13px] font-medium disabled:opacity-60">
              {isRefreshingMasterData ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Refresh Offline Data
            </button>
            <button onClick={handleSyncNow} disabled={isSyncing} className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium disabled:opacity-60">
              {isSyncing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Sync Now
            </button>
          </div>
        </div>
        <div className="flex gap-1.5 overflow-x-auto">
          {FILTERS.map((f) => (
            <button key={f.key} onClick={() => setFilter(f.key)} className={`px-3 py-1.5 rounded-full text-[12px] font-medium whitespace-nowrap ${filter === f.key ? 'bg-[#0066ff] text-white' : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300'}`}>
              {f.label} {f.statuses.length > 0 && `(${items.filter((i) => f.statuses.includes(i.status)).length})`}
            </button>
          ))}
        </div>
      </div>

      {!isBrowserOnline() && (
        <div className="flex items-center gap-2 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-4 py-3 text-[13px] text-gray-600 dark:text-gray-300 mb-4">
          <WifiOff size={16} /> You're offline. New invoices/customers/suppliers can still be saved locally and will sync automatically once you're back online.
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center justify-center py-16"><Loader2 size={28} className="animate-spin text-gray-400" /></div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-400">No transactions in this view.</div>
      ) : (
        <div className="space-y-2">
          {filtered.map((item) => {
            const meta = STATUS_META[item.status];
            return (
              <div key={item.queue_id} className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-gray-900 dark:text-white text-[14px]">{entityLabel(item.entity_type)}</span>
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${meta.className}`}>{meta.icon}{meta.label}</span>
                    </div>
                    <p className="text-[13px] text-gray-500 dark:text-gray-400 mt-0.5">
                      Temp ref: <span className="font-mono">{item.local_reference}</span>
                      {item.final_reference && <> · Final: <span className="font-mono text-green-600">{item.final_reference}</span></>}
                    </p>
                    <p className="text-[11px] text-gray-400">Created {new Date(item.created_at).toLocaleString()}{item.retry_count > 0 && ` · ${item.retry_count} attempt(s)`}</p>
                    {item.last_error && <p className="text-[12px] text-red-600 dark:text-red-400 mt-1">{item.last_error.message}</p>}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {(item.status === 'SYNC_FAILED' || item.status === 'PENDING_SYNC') && (
                      <button onClick={() => handleRetry(item)} className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[12px] font-medium">Retry</button>
                    )}
                    {(item.status === 'CONFLICT' || item.status === 'REQUIRES_ACTION') && (
                      <button onClick={() => setReviewing(item)} className="px-3 py-1.5 rounded-lg border border-amber-300 dark:border-amber-700 text-amber-700 dark:text-amber-400 text-[12px] font-medium">Review</button>
                    )}
                    {item.status !== 'SYNCED' && item.status !== 'SYNCING' && (
                      <button onClick={() => handleCancel(item)} className="p-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400" title="Cancel"><Ban size={14} /></button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {reviewing && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white flex items-center gap-2"><AlertTriangle size={18} className="text-amber-500" /> {entityLabel(reviewing.entity_type)} — {reviewing.status === 'CONFLICT' ? 'Conflict' : 'Action Required'}</h3>
              <button onClick={() => setReviewing(null)} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>
            <p className="text-[13px] text-gray-600 dark:text-gray-300 mb-2">
              {reviewing.last_error?.message || 'This transaction could not be processed as submitted.'}
            </p>
            <div className="flex items-start gap-2 text-[12px] text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-900 rounded-md p-3 mb-4">
              <Info size={14} className="shrink-0 mt-0.5" />
              {reviewing.status === 'CONFLICT'
                ? 'The server rejected this because the underlying data (e.g. available stock) changed while this device was offline. Review the current data online, then edit and retry, or cancel this local transaction.'
                : 'This transaction needs correction (invalid data, missing permission, or your session expired) before it can be retried automatically.'}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => setReviewing(null)} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Close</button>
              <button onClick={() => { handleRetry(reviewing); setReviewing(null); }} className="py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium">Retry</button>
            </div>
          </div>
        </div>
      )}

      {showCapture && currentTenant && currentUser && (
        <OfflineInvoiceCapture
          tenantId={currentTenant.id}
          userId={currentUser.id}
          onClose={() => setShowCapture(false)}
          onCreated={() => { setShowCapture(false); load(); }}
        />
      )}
    </div>
  );
};

export default SyncCenter;

// §39: exported so AuthContext's logout handler can check before
// clearing session state.
export { hasUnsyncedTransactions };
