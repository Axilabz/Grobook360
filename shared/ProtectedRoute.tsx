import React from 'react';
import { useAuth } from '../context/AuthContext';
import LoadingState from './LoadingState';

interface ProtectedRouteProps {
  children: React.ReactNode;
  /** Rendered instead of children when there is no valid session. */
  fallback: React.ReactNode;
}

// Frontend route protection (PROMPT-003 S19). This is a UX convenience only —
// it decides what to render, never what the user is allowed to do. Every
// protected API call is independently authorized server-side regardless of
// what this component shows.
const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children, fallback }) => {
  const { isAuthenticated, authenticationLoading } = useAuth();

  if (authenticationLoading) {
    return <LoadingState label="Checking your session…" />;
  }

  if (!isAuthenticated) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
};

export default ProtectedRoute;
