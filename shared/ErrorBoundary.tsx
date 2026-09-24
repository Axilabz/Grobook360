import React from 'react';

interface ErrorBoundaryState {
  hasError: boolean;
}

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

// Global error handling foundation (PROMPT-001 S14). Catches rendering errors
// that escape individual feature modules so the whole app doesn't go blank.
class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error('Unhandled application error', error, info);
  }

  render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-white px-4 text-center dark:bg-gray-950">
          <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">Something went wrong</p>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Please reload the page. If the problem continues, contact support.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="mt-2 rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white dark:bg-gray-100 dark:text-gray-900"
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
