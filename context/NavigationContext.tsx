import React, { createContext, useContext, useRef } from 'react';

type NavigationBlocker = (targetView: string) => boolean;

export type NavigationParams = Record<string, string>;

interface NavigationContextType {
  navigate: (view: string, params?: NavigationParams) => void;
  setBlocker: (blocker: NavigationBlocker | null) => void;
  /**
   * Consumes (reads + clears) any params handed to `navigate()` the last
   * time it targeted `view` — e.g. the record id a header-search result
   * should open on arrival. Returns undefined if none are pending, so a
   * screen only auto-opens a detail view when it was actually navigated
   * to with a target, not on every mount.
   */
  consumeParams: (view: string) => NavigationParams | undefined;
}

const NavigationContext = createContext<NavigationContextType | undefined>(undefined);

export const useNavigation = () => {
  const context = useContext(NavigationContext);
  if (!context) {
    throw new Error('useNavigation must be used within a NavigationProvider');
  }
  return context;
};

interface NavigationProviderProps {
  children: React.ReactNode;
  onNavigateInternal: (view: string) => void;
}

export const NavigationProvider: React.FC<NavigationProviderProps> = ({ children, onNavigateInternal }) => {
  const blockerRef = useRef<NavigationBlocker | null>(null);
  const pendingParamsRef = useRef<{ view: string; params: NavigationParams } | null>(null);

  const setBlocker = (blocker: NavigationBlocker | null) => {
    blockerRef.current = blocker;
  };

  const navigate = (view: string, params?: NavigationParams) => {
    const proceed = () => {
      pendingParamsRef.current = params ? { view, params } : null;
      onNavigateInternal(view);
    };
    if (blockerRef.current) {
      const shouldProceed = blockerRef.current(view);
      if (shouldProceed) proceed();
    } else {
      proceed();
    }
  };

  const consumeParams = (view: string): NavigationParams | undefined => {
    if (pendingParamsRef.current?.view !== view) return undefined;
    const { params } = pendingParamsRef.current;
    pendingParamsRef.current = null;
    return params;
  };

  return (
    <NavigationContext.Provider value={{ navigate, setBlocker, consumeParams }}>
      {children}
    </NavigationContext.Provider>
  );
};
