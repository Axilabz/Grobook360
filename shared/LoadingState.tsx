import React from 'react';

interface LoadingStateProps {
  label?: string;
}

const LoadingState: React.FC<LoadingStateProps> = ({ label = 'Loading…' }) => (
  <div className="flex flex-col items-center justify-center gap-3 py-16 text-gray-500 dark:text-gray-400">
    <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-gray-900 dark:border-gray-700 dark:border-t-gray-100" />
    <p className="text-sm">{label}</p>
  </div>
);

export default LoadingState;
