import React from 'react';

interface EmptyStateProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
}

const EmptyState: React.FC<EmptyStateProps> = ({ title, description, action }) => (
  <div className="flex flex-col items-center justify-center gap-2 py-16 text-center px-4">
    <p className="text-base font-medium text-gray-900 dark:text-gray-100">{title}</p>
    {description && <p className="text-sm text-gray-500 dark:text-gray-400 max-w-sm">{description}</p>}
    {action && <div className="mt-3">{action}</div>}
  </div>
);

export default EmptyState;
