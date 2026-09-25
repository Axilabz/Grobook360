import React, { useState } from 'react';
import Header from './Header';
import Sidebar from './Sidebar';

interface DashboardLayoutProps {
  children: React.ReactNode;
  currentView: string;
  onNavigate: (view: string) => void;
  onLogout: () => void;
}

const DashboardLayout: React.FC<DashboardLayoutProps> = ({ children, currentView, onNavigate, onLogout }) => {
  // Mobile: Default to collapsed (which means hidden).
  // Desktop: Default to collapsed (which means icon view).
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(true);

  const toggleSidebar = () => {
      setIsSidebarCollapsed(!isSidebarCollapsed);
  }

  return (
    <div className="min-h-screen bg-white dark:bg-gray-950 font-['Figtree'] transition-colors">
      <Header onMenuClick={toggleSidebar} onNavigate={onNavigate} onLogout={onLogout} />
      <Sidebar 
        isCollapsed={isSidebarCollapsed} 
        toggleSidebar={toggleSidebar}
        onNavigate={onNavigate} 
      />
      <main 
        className={`
          pt-16 min-h-screen transition-all duration-300 pl-0
          ${isSidebarCollapsed ? 'md:pl-16' : 'md:pl-64'} 
        `}
      >
        <div className="p-0 h-full w-full">
          {children}
        </div>
      </main>
      
      {/* Mobile Overlay Backdrop when sidebar is open — z-[57] sits above
          every page's own sticky content header (z-[55]) so the drawer it
          backs (z-[58]) genuinely reads as "on top of the whole screen",
          not just the plain page content beneath a still-visible header. */}
      {!isSidebarCollapsed && (
        <div
            className="md:hidden fixed inset-0 bg-black/20 z-[57] backdrop-blur-sm"
            onClick={() => setIsSidebarCollapsed(true)}
        ></div>
      )}
    </div>
  );
};

export default DashboardLayout;