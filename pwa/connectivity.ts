// Connectivity detection (PROMPT-028 §21).
//
// §21's own explicit warning: "Do not assume the browser's online event
// guarantees actual internet connectivity" — `navigator.onLine` only
// reflects whether the OS network interface is up, not whether THIS
// tenant's API is actually reachable (captive portals, VPN issues, the
// backend itself being down all report `navigator.onLine === true`).
// `checkRealConnectivity` performs an actual lightweight API round-trip
// before the sync engine commits to a bulk sync attempt.

const HEALTH_CHECK_PATH = '/api/v1/auth/session-status';
const HEALTH_CHECK_TIMEOUT_MS = 4000;

export function isBrowserOnline(): boolean {
  return typeof navigator === 'undefined' || navigator.onLine !== false;
}

export async function checkRealConnectivity(): Promise<boolean> {
  if (typeof fetch === 'undefined') return false;
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return false;

  const controller = typeof AbortController !== 'undefined' ? new AbortController() : undefined;
  const timeoutId = controller ? setTimeout(() => controller.abort(), HEALTH_CHECK_TIMEOUT_MS) : undefined;
  try {
    await fetch(HEALTH_CHECK_PATH, { method: 'GET', credentials: 'include', signal: controller?.signal });
    // Any completed response at all (even a 401/500) proves the network
    // path and the server are reachable; only a THROWN network error
    // (timeout, DNS failure, connection refused, abort) means "offline".
    return true;
  } catch {
    return false;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

export type ConnectivityListener = (online: boolean) => void;

export function subscribeToConnectivity(listener: ConnectivityListener): () => void {
  if (typeof window === 'undefined') return () => {};
  const onOnline = () => listener(true);
  const onOffline = () => listener(false);
  window.addEventListener('online', onOnline);
  window.addEventListener('offline', onOffline);
  return () => {
    window.removeEventListener('online', onOnline);
    window.removeEventListener('offline', onOffline);
  };
}
