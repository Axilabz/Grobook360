import React from 'react';
import { AuthView } from '../types';
import SignInIllustration from '../shared/SignInIllustration';

interface LayoutProps {
  children: React.ReactNode;
  currentView: AuthView;
}

const Layout: React.FC<LayoutProps> = ({ children, currentView }) => {
  return (
    <div className="min-h-screen w-full relative overflow-x-hidden flex items-center justify-center p-4 bg-white">
      
      {/* --- Full Screen Background Illustration (inline SVG, not an image file) --- */}
      <div className="fixed inset-0 z-0 pointer-events-none select-none">
        {currentView !== AuthView.SIGN_UP && (
          <SignInIllustration className="w-full h-full" />
        )}
      </div>

      {/* Main Content Container */}
      <div className="relative z-10 w-full max-w-[95%] md:max-w-4xl lg:max-w-5xl transition-all duration-300 flex justify-center">
        {children}
      </div>
    </div>
  );
};

export default Layout;