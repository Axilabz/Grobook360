import React from 'react';
import { AuthView } from '../types';

interface LayoutProps {
  children: React.ReactNode;
  currentView: AuthView;
}

const Layout: React.FC<LayoutProps> = ({ children, currentView }) => {
  return (
    <div className="min-h-screen w-full relative overflow-x-hidden flex items-center justify-center p-4 bg-white">
      
      {/* --- Full Screen Background Image --- */}
      <div className="fixed inset-0 z-0 pointer-events-none select-none">
        {/* Mobile Background (Visible on small screens, hidden on Sign Up) */}
        {currentView !== AuthView.SIGN_UP && (
          <img 
            src="/MobileSignInBackGroundImage.png" 
            alt="Background Mobile" 
            className="block md:hidden w-full h-full object-cover"
          />
        )}
        
        {/* Tablet Background (Visible on medium screens, hidden on large screens) */}
        <img 
          src="/TabletSignInBackGroundImage.png" 
          alt="Background Tablet" 
          className="hidden md:block lg:hidden w-full h-full object-cover"
        />

        {/* Web/Desktop Background (Visible on large screens and up) */}
        <img 
          src="/WebSignInBackGroundImage.png" 
          alt="Background Web" 
          className="hidden lg:block w-full h-full object-cover"
        />
      </div>

      {/* Main Content Container */}
      <div className="relative z-10 w-full max-w-[95%] md:max-w-4xl lg:max-w-5xl transition-all duration-300 flex justify-center">
        {children}
      </div>
    </div>
  );
};

export default Layout;