import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Wifi, WifiOff, RefreshCw, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { isBrowserOnline, subscribeToConnectivity, checkRealConnectivity } from '../pwa/connectivity';
import { runSync } from '../pwa/syncEngine';
import { dbGetAllByTenant, STORE_SYNC_QUEUE } from '../pwa/offlineDb';
import { SyncQueueItem } from '../pwa/offlineTypes';

const AUTO_SYNC_INTERVAL_MS = 30000;

// PROMPT-028 §41: "Provide a persistent but unobtrusive sync indicator."
// Mounted once in Header.tsx so it's visible from every screen.
const ConnectivityBadge: React.FC<{ onOpenSyncCenter: () => void }> = ({ onOpenSyncCenter }) => {
  const { currentTenant, isAuthenticated } = useAuth();
  const [online, setOnline] = useState(isBrowserOnline());
  const [isSyncing, setIsSyncing] = useState(false);
  const [pending, setPending] = useState(0);
  const [failed, setFailed] = useState(0);
  const [conflicts, setConflicts] = useState(0);
  const [requiresAction, setRequiresAction] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refreshCounts = useCallback(async () => {
    if (!currentTenant) return;
    try {
      const items = await dbGetAllByTenant<SyncQueueItem>(STORE_SYNC_QUEUE, currentTenant.id);
      setPending(items.filter((i) => i.status === 'PENDING_SYNC' || i.status === 'SYNCING').length);
      setFailed(items.filter((i) => i.status === 'SYNC_FAILED').length);
      setConflicts(items.filter((i) => i.status === 'CONFLICT').length);
      setRequiresAction(items.filter((i) => i.status === 'REQUIRES_ACTION').length);
    } catch {
      // IndexedDB unavailable (e.g. private-browsing edge cases) — badge
      // just shows connectivity, no queue counts. Not fatal.
    }
  }, [currentTenant]);

  const attemptSync = useCallback(async () => {
    if (!currentTenant || isSyncing) return;
    setIsSyncing(true);
    try {
      const result = await runSync(currentTenant.id);
      setOnline(result !== null);
    } finally {
      setIsSyncing(false);
      await refreshCounts();
    }
  }, [currentTenant, isSyncing, refreshCounts]);

  useEffect(() => {
    if (!isAuthenticated) return;
    refreshCounts();
    const unsubscribe = subscribeToConnectivity(async (isOnline) => {
      setOnline(isOnline);
      if (isOnline) await attemptSync();
    });
    intervalRef.current = setInterval(() => {
      checkRealConnectivity().then((reallyOnline) => {
        setOnline(reallyOnline);
        if (reallyOnline) attemptSync();
      });
    }, AUTO_SYNC_INTERVAL_MS);
    return () => {
      unsubscribe();
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, currentTenant?.id]);

  if (!isAuthenticated) return null;

  const hasIssues = conflicts + requiresAction + failed > 0;
  const label = !online
    ? 'Offline'
    : isSyncing
      ? 'Syncing…'
      : hasIssues
        ? `${conflicts + requiresAction + failed} need attention`
        : pending > 0
          ? `${pending} pending sync`
          : 'Synced';

  const tone = !online ? 'bg-gray-600' : hasIssues ? 'bg-amber-500' : pending > 0 ? 'bg-blue-500' : 'bg-green-600';

  return (
    <button
      onClick={onOpenSyncCenter}
      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-white text-[12px] font-medium shadow-sm ${tone} hover:opacity-90 transition-opacity`}
      title="Open Sync Center"
    >
      {!online ? <WifiOff size={13} /> : isSyncing ? <RefreshCw size={13} className="animate-spin" /> : hasIssues ? <AlertTriangle size={13} /> : pending > 0 ? <Wifi size={13} /> : <CheckCircle2 size={13} />}
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
};

export default ConnectivityBadge;
