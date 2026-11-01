import React from 'react';
import { ShieldAlert } from 'lucide-react';

interface AccessDeniedProps {
  onGoHome?: () => void;
}

// RBAC Alignment Phase: the app had no "Access Denied" state at all before
// this — an unauthorized view either rendered unconditionally (the actual
// gap this fixes) or fell through to a generic "Page Under Construction"
// message, indistinguishable from a route that simply doesn't exist yet.
const AccessDenied: React.FC<AccessDeniedProps> = ({ onGoHome }) => (
  <div className="flex flex-col items-center justify-center gap-2 py-20 text-center px-4">
    <ShieldAlert size={40} className="text-red-400 dark:text-red-500 mb-2" />
    <p className="text-base font-medium text-gray-900 dark:text-gray-100">Access Denied</p>
    <p className="text-sm text-gray-500 dark:text-gray-400 max-w-sm">
      You don't have permission to view this page. If you think this is a mistake, contact your Owner or Manager.
    </p>
    {onGoHome && (
      <button
        onClick={onGoHome}
        className="mt-3 px-4 py-2 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[13px] font-medium"
      >
        Go to Home
      </button>
    )}
  </div>
);

export default AccessDenied;
