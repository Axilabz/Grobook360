import React, { useState, useEffect, useRef } from 'react';
import { SelectProps } from '../types';
import { ChevronDown, Check } from 'lucide-react';

const Select: React.FC<SelectProps> = ({ label, options, error, value, onChange, className, disabled, labelClassName }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [newItemValue, setNewItemValue] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Sync search term with selected value
  useEffect(() => {
    setSearchTerm(value || '');
  }, [value]);

  // Handle click outside to close dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        // Revert input to selected value if user didn't select a new option
        setSearchTerm(value || '');
        setNewItemValue('');
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [value]);

  const filteredOptions = options.filter((opt) =>
    opt.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleSelect = (option: string) => {
    onChange(option);
    setSearchTerm(option);
    setIsOpen(false);
    setNewItemValue('');
  };

  const handleAddNew = (e: React.MouseEvent | React.KeyboardEvent) => {
    e.preventDefault(); // Prevent form submission
    const val = newItemValue.trim();
    if (!val) return;

    // Validation: Min 2, Max 20, Alpha only (Lower + Upper)
    // Regex: ^[a-zA-Z]{2,20}$
    const isValid = /^[a-zA-Z\s]{2,20}$/.test(val); // Allowing spaces for multi-word items like "Small Business"
    
    if (isValid) {
      onChange(val);
      setSearchTerm(val);
      setIsOpen(false);
      setNewItemValue('');
    } else {
      // Ideally show error, but for now we just prevent addition if invalid
      // to maintain exact screen design without adding new error UI elements.
    }
  };

  const toggleDropdown = (e: React.MouseEvent) => {
    e.preventDefault();
    if (disabled) return;
    
    if (isOpen) {
      setIsOpen(false);
    } else {
      setIsOpen(true);
      inputRef.current?.focus();
    }
  };

  return (
    <div className="relative mb-10 w-full" ref={containerRef}>
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          disabled={disabled}
          value={searchTerm}
          onChange={(e) => {
            setSearchTerm(e.target.value);
            if (!isOpen) setIsOpen(true);
          }}
          onFocus={() => !disabled && setIsOpen(true)}
          className={`
            peer block w-full rounded-md border px-3 py-3 pr-10 
            text-gray-900 dark:text-white
            bg-white dark:bg-transparent
            focus:outline-none focus:ring-0 
            text-[15px] md:text-[16px] font-normal leading-[1.4] /* Input Text */
            ${error ? 'border-red-500 focus:border-red-500' : 'border-blue-300 focus:border-blue-500 dark:border-gray-600 dark:focus:border-blue-400'}
            placeholder-transparent
            ${className || ''}
            ${disabled ? 'bg-gray-100 dark:bg-gray-700 cursor-not-allowed' : ''}
          `}
          placeholder={label}
          autoComplete="off"
        />
        
        {/* Floating Label */}
        <label
          className={`
            absolute left-3 z-10 px-1 transition-all duration-200 pointer-events-none
            ${labelClassName || 'bg-white dark:bg-gray-800'}
            -top-2.5 
            text-[12px] md:text-[14px] font-medium /* Label Typography */
            peer-placeholder-shown:top-3 peer-placeholder-shown:text-[15px] peer-placeholder-shown:md:text-[16px] peer-placeholder-shown:font-normal peer-placeholder-shown:text-gray-500 dark:peer-placeholder-shown:text-gray-400
            peer-focus:-top-2.5 peer-focus:text-[12px] peer-focus:md:text-[14px] peer-focus:font-medium
            ${error ? 'text-red-500 peer-focus:text-red-500' : 'text-gray-500 dark:text-gray-400 peer-focus:text-blue-500 dark:peer-focus:text-blue-400'}
          `}
        >
          {label}
        </label>
        
        {/* Toggle Icon */}
        <div 
          className="absolute right-3 top-1/2 -translate-y-1/2 cursor-pointer"
          onMouseDown={(e) => e.preventDefault()} 
          onClick={toggleDropdown}
        >
          <ChevronDown 
            size={20} 
            className={`
                bg-[#0066ff] hover:bg-blue-700 text-white rounded-sm p-0.5 transition-all duration-200
                ${isOpen ? 'rotate-180' : ''}
                ${disabled ? 'opacity-50' : ''}
            `} 
          />
        </div>
      </div>

      {/* Dropdown List */}
      {isOpen && (
        <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-md bg-white dark:bg-gray-800 shadow-lg ring-1 ring-black ring-opacity-5 animate-fade-in border border-gray-100 dark:border-gray-700">
          <ul className="max-h-48 overflow-auto py-1 custom-scrollbar">
            {filteredOptions.length === 0 ? (
              <li className="px-4 py-2 text-sm text-gray-400 italic">No matching options found</li>
            ) : (
              filteredOptions.map((opt) => (
                <li
                  key={opt}
                  className={`
                    cursor-pointer px-4 py-2 text-gray-900 dark:text-gray-100 hover:bg-blue-50 dark:hover:bg-gray-700
                    text-[14px] md:text-[15px] font-normal leading-[1.4] /* Dropdown Item */
                    ${opt === value ? 'bg-blue-100 dark:bg-blue-900/40 font-medium' : ''}
                  `}
                  onClick={() => handleSelect(opt)}
                >
                  {opt}
                </li>
              ))
            )}
          </ul>

          {/* Add New Item Section */}
          <div className="border-t border-gray-100 dark:border-gray-700 p-2 bg-gray-50 dark:bg-gray-800/50">
             <div className="relative">
                <input 
                    type="text"
                    className="w-full text-sm border border-gray-300 dark:border-gray-600 rounded px-3 py-2 pr-10 focus:outline-none focus:border-blue-400 focus:ring-0 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                    placeholder="Add new item..."
                    value={newItemValue}
                    onChange={(e) => setNewItemValue(e.target.value.replace(/[^a-zA-Z\s]/g, ''))}
                    onClick={(e) => e.stopPropagation()}
                    maxLength={20}
                    onKeyDown={(e) => {
                        if(e.key === 'Enter') {
                            handleAddNew(e);
                        }
                    }}
                />
                <button
                    type="button"
                    onClick={handleAddNew}
                    disabled={!newItemValue.trim()}
                    className={`
                        absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded transition-colors flex items-center justify-center
                        ${newItemValue.trim() 
                            ? 'bg-[#0066ff] hover:bg-blue-700 text-white' 
                            : 'bg-gray-100 dark:bg-gray-600 text-gray-300 dark:text-gray-400 cursor-not-allowed'}
                    `}
                    title="Add Item"
                >
                    <Check size={18} strokeWidth={3} />
                </button>
             </div>
          </div>
        </div>
      )}

      {error && (
        <div className="absolute left-0 top-full mt-1 text-[12px] text-red-500 text-left w-full truncate">{error}</div>
      )}
    </div>
  );
};

export default Select;