import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { AuthProvider, useAuth } from '../../context/AuthContext';

vi.mock('../../api/auth', () => ({
  login: vi.fn(),
  logout: vi.fn(),
  fetchCurrentSession: vi.fn(),
}));

import { login as mockLogin, logout as mockLogout, fetchCurrentSession as mockFetchSession } from '../../api/auth';
import { ApiError } from '../../api/client';

const Probe: React.FC = () => {
  const { isAuthenticated, authenticationLoading, currentTenant, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(authenticationLoading)}</span>
      <span data-testid="authed">{String(isAuthenticated)}</span>
      <span data-testid="tenant">{currentTenant?.business_name ?? 'none'}</span>
      <button onClick={() => login('9876543210', 'pw')}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  );
};

describe('AuthContext (PROMPT-003 S28 centralized auth state)', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('starts loading, then resolves to unauthenticated when no session exists', async () => {
    (mockFetchSession as any).mockRejectedValue(new ApiError(401, { code: 'AUTH-008', message: 'Not authenticated', details: [] }));

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );

    expect(screen.getByTestId('loading').textContent).toBe('true');

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('authed').textContent).toBe('false');
  });

  it('restores an authenticated session when one exists', async () => {
    (mockFetchSession as any).mockResolvedValue({
      user_id: 'u1',
      tenant_id: 't1',
      role: 'OWNER',
      permissions: [],
    });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );

    await waitFor(() => expect(screen.getByTestId('authed').textContent).toBe('true'));
  });

  it('login() updates state on success', async () => {
    (mockFetchSession as any).mockRejectedValue(new ApiError(401, { code: 'AUTH-008', message: 'x', details: [] }));
    (mockLogin as any).mockResolvedValue({
      user: { id: 'u1', phone: '9876543210', email: 'a@b.com', role: 'OWNER' },
      tenant: { id: 't1', business_name: 'Test Co' },
      permissions: [],
    });

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));

    await act(async () => {
      screen.getByText('login').click();
    });

    expect(screen.getByTestId('authed').textContent).toBe('true');
    expect(screen.getByTestId('tenant').textContent).toBe('Test Co');
  });

  it('logout() clears state even when the server call fails', async () => {
    (mockFetchSession as any).mockResolvedValue({ user_id: 'u1', tenant_id: 't1', role: 'OWNER', permissions: [] });
    (mockLogout as any).mockRejectedValue(new ApiError(401, { code: 'AUTH-005', message: 'x', details: [] }));

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );
    await waitFor(() => expect(screen.getByTestId('authed').textContent).toBe('true'));

    await act(async () => {
      screen.getByText('logout').click();
    });

    expect(screen.getByTestId('authed').textContent).toBe('false');
  });
});
