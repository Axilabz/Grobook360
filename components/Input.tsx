import React from 'react';
import { InputProps } from '../types';
import { Info } from 'lucide-react';

const Input: React.FC<InputProps> = ({ label, error, icon, onIconClick, infoContent, forceShowTooltip, className, labelClassName, ...props }) => {
  return (
    <div className="relative mb-10 w-full">
      <div className="relative">
        <input
          {...props}
          className={`
            peer block w-full rounded-md border px-3 py-3 
            text-gray-900 dark:text-white
            bg-transparent
            focus:outline-none focus:ring-0 
            text-[15px] md:text-[16px] font-normal leading-[1.4] /* Input Text Typography */
            ${error ? 'border-red-500 focus:border-red-500' : 'border-blue-300 focus:border-blue-500 dark:border-gray-600 dark:focus:border-blue-400'}
            placeholder-transparent
            ${props.disabled ? 'bg-gray-100 dark:bg-gray-700 cursor-not-allowed text-gray-500 dark:text-gray-400' : ''}
            ${className || ''}
          `}
          placeholder={label} 
        />
        <label
          title={label}
          className={`
            absolute left-3 z-10 px-1 transition-all duration-200 pointer-events-none
            whitespace-nowrap overflow-hidden text-ellipsis max-w-[calc(100%-1.5rem)]
            ${labelClassName || 'bg-white dark:bg-gray-800'}
            -top-2.5
            text-[12px] md:text-[14px] font-medium /* Label Typography (Floating) */
            peer-placeholder-shown:top-3 peer-placeholder-shown:text-[15px] peer-placeholder-shown:md:text-[16px] peer-placeholder-shown:font-normal peer-placeholder-shown:text-gray-500 dark:peer-placeholder-shown:text-gray-400
            peer-focus:-top-2.5 peer-focus:text-[12px] peer-focus:md:text-[14px] peer-focus:font-medium
            ${error ? 'text-red-500 peer-focus:text-red-500' : 'text-gray-500 dark:text-gray-400 peer-focus:text-blue-500 dark:peer-focus:text-blue-400'}
          `}
        >
          {label}
        </label>
        
        {/* Info Tooltip Icon */}
        {infoContent && (
            <div className={`absolute top-1/2 -translate-y-1/2 z-20 group ${icon ? 'right-12' : 'right-3'}`}>
                 <Info size={18} className="text-gray-400 dark:text-gray-500 hover:text-[#0066ff] dark:hover:text-blue-400 cursor-help" />
                 <div className={`
                    absolute right-[-2rem] md:right-0 bottom-full mb-2 w-64 p-3 bg-gray-900 dark:bg-gray-700 text-white text-xs rounded-lg shadow-xl 
                    transition-all duration-200 z-50 pointer-events-none md:pointer-events-auto
                    ${forceShowTooltip ? 'visible opacity-100' : 'invisible group-hover:visible opacity-0 group-hover:opacity-100'}
                 `}>
                    {infoContent}
                    <div className="absolute right-10 md:right-2 -bottom-1 w-2 h-2 bg-gray-900 dark:bg-gray-700 rotate-45"></div>
                 </div>
            </div>
        )}

        {icon && (
          <div 
            className={`absolute right-3 top-1/2 -translate-y-1/2 cursor-pointer text-gray-500 dark:text-gray-400 ${props.disabled ? 'pointer-events-none opacity-50' : ''}`}
            onClick={!props.disabled ? onIconClick : undefined}
          >
            {icon}
          </div>
        )}
      </div>
      {error && (
        <div className="absolute left-0 top-full mt-1 text-[12px] text-red-500 text-left w-full truncate">{error}</div>
      )}
    </div>
  );
};

export default Input;