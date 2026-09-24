import React, { createContext, useContext, useState, useCallback, useRef } from 'react';
import Toast from '../components/Toast';

interface ToastContextType {
  showToast: (message: string, type?: 'error' | 'success') => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
};

interface ToastData {
  id: number;
  message: string;
  type: 'error' | 'success';
}

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toast, setToast] = useState<ToastData | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, type: 'error' | 'success' = 'error') => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    setToast({ id: Date.now(), message, type });
    timerRef.current = setTimeout(() => {
      setToast(null);
    }, 5000);
  }, []);

  const closeToast = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setToast(null);
  };

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {toast && (
         <Toast 
            key={toast.id}
            message={toast.message} 
            type={toast.type} 
            onClose={closeToast} 
         />
      )}
    </ToastContext.Provider>
  );
};