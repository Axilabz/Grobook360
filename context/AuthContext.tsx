import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { login as apiLogin, logout as apiLogout, fetchCurrentSession, AuthUser, AuthTenant } from '../api/auth';
import { ApiError, setUnauthorizedHandler } from '../api/client';
import { hasUnsyncedTransactions } from '../pwa/offlineDb';

// Centralized authentication state (PROMPT-003 S28). The frontend is never
// the source of truth for authorization — role/permissions here are only for
// UI behavior (show/hide); every protected API call is re-checked server-side.
interface AuthContextType {
  isAuthenticated: boolean;
  currentUser: AuthUser | { id: string } | null;
  currentTenant: AuthTenant | null;
  role: string | null;
  permissions: string[];
  /** UX convenience only (PROMPT-006 S16/S27) — hides/shows UI. The backend
   * independently re-checks every protected call; this is never the
   * authorization boundary. */
  hasPermission: (code: string) => boolean;
  authenticationLoading: boolean;
  sessionExpired: boolean;
  login: (loginIdentifier: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [currentUser, setCurrentUser] = useState<AuthUser | { id: string } | null>(null);
  const [currentTenant, setCurrentTenant] = useState<AuthTenant | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [authenticationLoading, setAuthenticationLoading] = useState(true);
  const [sessionExpired, setSessionExpired] = useState(false);
  const wasAuthenticatedRef = useRef(false);

  const clearAuthState = useCallback(() => {
    setIsAuthenticated(false);
    setCurrentUser(null);
    setCurrentTenant(null);
    setRole(null);
    setPermissions([]);
  }, []);

  useEffect(() => {
    wasAuthenticatedRef.current = isAuthenticated;
  }, [isAuthenticated]);

  // Any protected call anywhere in the app hitting 401 while we previously
  // held an authenticated session means the session expired/was revoked
  // mid-use — distinct from "never logged in" (avoid infinite refresh loops
  // per S22: this only flips a flag, it never auto-retries).
  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (wasAuthenticatedRef.current) {
        setSessionExpired(true);
      }
      clearAuthState();
    });
    return () => setUnauthorizedHandler(null);
  }, [clearAuthState]);

  // Session restoration on app open/refresh (PROMPT-003 S20): ask the server
  // whether the httpOnly cookie still names a valid, non-revoked session.
  // Never silently fabricate an authenticated state without this check.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await fetchCurrentSession();
        if (cancelled) return;
        setIsAuthenticated(true);
        setCurrentUser({ id: me.user_id });
        setCurrentTenant(me.tenant);
        setRole(me.role);
        setPermissions(me.permissions);
      } catch {
        if (cancelled) return;
        clearAuthState();
      } finally {
        if (!cancelled) setAuthenticationLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [clearAuthState]);

  const login = useCallback(async (loginIdentifier: string, password: string) => {
    setSessionExpired(false);
    const result = await apiLogin(loginIdentifier, password);
    setIsAuthenticated(true);
    setCurrentUser(result.user);
    setCurrentTenant(result.tenant);
    setRole(result.user.role);
    setPermissions(result.permissions);
    // PROMPT-028 §15/§36: best-effort background refresh of the offline
    // read cache right after login, so master data (products/customers/
    // suppliers/units) is available if the device goes offline soon
    // after. Never blocks/fails the login itself — offline capability
    // is a convenience layer, not a login precondition.
    if (result.tenant) {
      import('../pwa/masterDataCache')
        .then(({ refreshMasterData }) => refreshMasterData(result.tenant!.id))
        .catch(() => undefined);
    }
  }, []);

  const logout = useCallback(async () => {
    // PROMPT-028 §39: logout must NEVER silently discard unsynchronized
    // offline transactions. Nothing in this function (or anywhere else)
    // deletes the IndexedDB sync_queue — this check exists purely to
    // warn the user BEFORE they leave the session, since a
    // logged-out/different-session device is less likely to be the one
    // that eventually reconnects and completes the sync.
    if (currentTenant) {
      let unsynced = false;
      try {
        unsynced = await hasUnsyncedTransactions(currentTenant.id);
      } catch {
        // Offline storage unavailable — nothing to warn about, proceed.
      }
      if (unsynced) {
        const proceedAnyway = window.confirm(
          'You have unsynchronized transactions. Please connect to the internet and synchronize before leaving this session.\n\n' +
            'Log out anyway? Your offline data will remain saved on this device and can be synced the next time you sign in here.'
        );
        if (!proceedAnyway) return;
      }
    }
    try {
      await apiLogout();
    } catch (err) {
      // Best-effort: even if the server call fails (already-expired session,
      // network error), clear local state so the UI never keeps showing
      // protected content after the user asked to log out.
      if (!(err instanceof ApiError)) {
        console.error('Logout request failed', err);
      }
    } finally {
      clearAuthState();
      setSessionExpired(false);
    }
  }, [clearAuthState, currentTenant]);

  const hasPermission = useCallback((code: string) => permissions.includes(code), [permissions]);

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated,
        currentUser,
        currentTenant,
        role,
        permissions,
        hasPermission,
        authenticationLoading,
        sessionExpired,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};
