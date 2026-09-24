import React from 'react';
import { X } from 'lucide-react';

interface ToastProps {
  message: string;
  type?: 'error' | 'success';
  onClose: () => void;
}

const Toast: React.FC<ToastProps> = ({ message, type = 'error', onClose }) => {
  return (
    <div className={`
        fixed z-[100] flex justify-center w-full pointer-events-none
        top-4 left-0 
        md:top-4 md:right-4 md:left-auto md:justify-end md:w-auto
    `}>
      <div className={`
        pointer-events-auto
        w-[90%] max-w-md md:w-96
        p-3 rounded-md shadow-lg border flex items-start gap-2 
        animate-fade-in-down
        ${type === 'error' ? 'bg-red-50 border-red-200 text-red-600' : 'bg-green-50 border-green-200 text-green-600'}
      `}>
         <div className="mt-0.5 shrink-0">
           {type === 'error' ? (
             <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
             </svg>
           ) : (
             <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                 <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
             </svg>
           )}
         </div>
         
         <div className="text-sm font-medium flex-1 break-words">
            {message}
         </div>

         <button 
            onClick={onClose} 
            className={`shrink-0 ml-2 hover:opacity-70 ${type === 'error' ? 'text-red-400' : 'text-green-400'}`}
         >
             <X size={16} />
         </button>
      </div>
    </div>
  );
};

export default Toast;