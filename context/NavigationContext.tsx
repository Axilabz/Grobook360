import React, { createContext, useContext, useRef } from 'react';

type NavigationBlocker = (targetView: string) => boolean;

interface NavigationContextType {
  navigate: (view: string) => void;
  setBlocker: (blocker: NavigationBlocker | null) => void;
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

  const setBlocker = (blocker: NavigationBlocker | null) => {
    blockerRef.current = blocker;
  };

  const navigate = (view: string) => {
    if (blockerRef.current) {
      const shouldProceed = blockerRef.current(view);
      if (shouldProceed) {
        onNavigateInternal(view);
      }
    } else {
      onNavigateInternal(view);
    }
  };

  return (
    <NavigationContext.Provider value={{ navigate, setBlocker }}>
      {children}
    </NavigationContext.Provider>
  );
};
