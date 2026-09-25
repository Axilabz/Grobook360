import React, { useState, useRef, useEffect } from 'react';
import { Search, Bell, ChevronDown, Menu, LogOut, Building, Shield, Lock, Sun, Moon, Settings } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import ConnectivityBadge from './ConnectivityBadge';

interface HeaderProps {
  onMenuClick: () => void;
  onNavigate: (view: string) => void;
  onLogout: () => void;
}

const Header: React.FC<HeaderProps> = ({ onMenuClick, onNavigate, onLogout }) => {
  const [searchType, setSearchType] = useState('Customer');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  
  const dropdownRef = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);

  const { theme, toggleTheme } = useTheme();
  const { hasPermission } = useAuth();

  // Requirement: Dynamic User Profile
  const companyName = "Agin Crop";

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map((word) => word[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  // Requirement 5: Updated Dropdown Options
  const searchOptions = ['Customer', 'Vendor', 'Product', 'Sales Invoice', 'Purchase Invoice'];

  // Handle click outside to close dropdowns
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      // Close Search Dropdown
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
      // Close Profile Dropdown
      if (profileRef.current && !profileRef.current.contains(event.target as Node)) {
        setIsProfileOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <header className="bg-[#0066ff] dark:bg-gray-900 h-16 flex items-center justify-between px-4 fixed top-0 w-full z-[60] shadow-sm transition-all duration-300 border-b border-transparent dark:border-gray-800">
      {/* Logo Area */}
      <div className="flex items-center w-auto md:w-64 pl-2">
        {/* Logo Text: 22-26px Bold */}
        <h1 className="text-white text-[22px] md:text-[24px] lg:text-[26px] font-bold tracking-tight leading-tight">Saas App</h1>
      </div>

      {/* Search Bar Area */}
      <div className="hidden md:flex flex-1 max-w-2xl mx-4">
        {/* Removed overflow-hidden here to allow dropdown to show */}
        <div className="flex w-full h-10 bg-white dark:bg-gray-800 rounded-md p-1 shadow-sm relative transition-colors">
          
          {/* Dropdown */}
          <div className="relative border-r border-gray-200 dark:border-gray-700" ref={dropdownRef}>
            <button
              className="h-full px-3 flex items-center gap-2 text-gray-800 dark:text-gray-200 text-[13px] md:text-[14px] font-medium hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors w-[180px] justify-between outline-none focus:outline-none focus:ring-0 rounded-l"
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
            >
              <span className="truncate max-w-[140px]">{searchType}</span>
              <div className="bg-[#0066ff] p-0.5 rounded-[4px] shrink-0">
                 <ChevronDown 
                    size={14} 
                    className={`text-white font-bold transition-transform duration-200 ${isDropdownOpen ? 'rotate-180' : ''}`} 
                    strokeWidth={3} 
                 />
              </div>
            </button>
            
            {isDropdownOpen && (
              <div className="absolute top-full -left-[1px] mt-1 w-[calc(100%+1px)] bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 rounded-md shadow-lg py-1 z-50 animate-fade-in">
                {searchOptions.map((opt) => (
                  <button
                    key={opt}
                    className="w-full text-left px-3 py-2 text-[13px] md:text-[14px] text-gray-700 dark:text-gray-200 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-blue-600 dark:hover:text-blue-400 transition-colors truncate"
                    onClick={() => {
                      setSearchType(opt);
                      setIsDropdownOpen(false);
                    }}
                    title={opt}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Input - Requirement 5: Dynamic Placeholder */}
          <input
            type="text"
            placeholder={`Search the ${searchType}`}
            className="flex-1 px-4 text-[14px] text-gray-700 dark:text-gray-200 outline-none placeholder-gray-400 dark:placeholder-gray-500 bg-transparent font-normal"
          />

          {/* Search Button */}
          <button className="px-1">
             <div className="bg-[#0066ff] hover:bg-blue-700 h-8 w-8 rounded flex items-center justify-center transition-colors">
                 <Search size={18} className="text-white" strokeWidth={2.5} />
             </div>
          </button>
        </div>
      </div>

      {/* Right User Actions */}
      <div className="flex items-center justify-end gap-2 md:gap-4">

        <ConnectivityBadge onOpenSyncCenter={() => onNavigate('Sync Center')} />

        <span className="text-white text-[14px] font-medium hidden lg:block">{companyName}</span>
        
        {/* Profile Icon with Dropdown - Moved to last position (before mobile menu) */}
        <div className="relative" ref={profileRef}>
            <div 
              className="w-9 h-9 bg-white dark:bg-gray-800 rounded-full flex items-center justify-center text-[#0066ff] dark:text-blue-400 font-bold text-sm shadow-sm cursor-pointer hover:bg-blue-50 dark:hover:bg-gray-700 transition-colors"
              onClick={() => setIsProfileOpen(!isProfileOpen)}
            >
              {getInitials(companyName)}
            </div>

            {/* Profile Dropdown Menu */}
            {isProfileOpen && (
              <div className="absolute top-full right-0 mt-3 w-60 bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 rounded-lg shadow-xl py-1 z-50 animate-fade-in">
                  {/* Company Name (Text Only) */}
                  <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700 bg-gray-50/50 dark:bg-gray-900/50 rounded-t-lg">
                      <p className="text-xs text-gray-500 dark:text-gray-400 font-normal uppercase tracking-wider mb-0.5">Signed in as</p>
                      <p className="text-sm font-bold text-gray-900 dark:text-white truncate">{companyName}</p>
                  </div>
                  
                  {/* Menu Items */}
                  <div className="py-1">
                      <button 
                        onClick={() => {
                            onNavigate('View Company');
                            setIsProfileOpen(false);
                        }}
                        className="w-full text-left px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-[#0066ff] dark:hover:text-blue-400 flex items-center gap-3 transition-colors"
                      >
                          <Building size={16} /> View Company
                      </button>
                      <button className="w-full text-left px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-[#0066ff] dark:hover:text-blue-400 flex items-center gap-3 transition-colors">
                          <Shield size={16} /> User Permission
                      </button>
                      {hasPermission('configuration.view') && (
                        <button
                          onClick={() => {
                              onNavigate('Configuration');
                              setIsProfileOpen(false);
                          }}
                          className="w-full text-left px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-[#0066ff] dark:hover:text-blue-400 flex items-center gap-3 transition-colors"
                        >
                            <Settings size={16} /> Configuration
                        </button>
                      )}
                      <button className="w-full text-left px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-[#0066ff] dark:hover:text-blue-400 flex items-center gap-3 transition-colors">
                          <Lock size={16} /> Change Password
                      </button>

                      <div className="border-t border-gray-100 dark:border-gray-700 my-1"></div>

                      <button 
                        onClick={() => {
                            toggleTheme();
                        }}
                        className="w-full text-left px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-[#0066ff] dark:hover:text-blue-400 flex items-center gap-3 transition-colors"
                      >
                         {theme === 'light' ? <Moon size={16} /> : <Sun size={16} />} 
                         {theme === 'light' ? 'Dark Mode' : 'Light Mode'}
                      </button>
                      
                      <div className="border-t border-gray-100 dark:border-gray-700 my-1"></div>
                      
                      <button
                        onClick={() => {
                            setIsProfileOpen(false);
                            onLogout();
                        }}
                        className="w-full text-left px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-3 transition-colors"
                      >
                          <LogOut size={16} /> Log Out
                      </button>
                  </div>
              </div>
            )}
        </div>
        
        {/* Mobile Hamburger Menu - Always last on mobile */}
        <button 
            onClick={onMenuClick}
            className="md:hidden text-white hover:text-blue-100 transition-colors"
        >
            <Menu size={24} />
        </button>
      </div>
    </header>
  );
};

export default Header;