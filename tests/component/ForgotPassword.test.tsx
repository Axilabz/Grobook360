import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ForgotPassword from '../../components/ForgotPassword';
import { ToastProvider } from '../../context/ToastContext';
import { AuthView } from '../../types';

vi.mock('../../api/passwordReset', () => ({
  requestPasswordReset: vi.fn(),
}));

import { requestPasswordReset } from '../../api/passwordReset';

const GENERIC_MESSAGE = 'If an account matches the information provided, recovery instructions will be sent.';

describe('ForgotPassword (PROMPT-004 anti-enumeration UI)', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('shows the same generic confirmation for a real-looking email', async () => {
    (requestPasswordReset as any).mockResolvedValue({ message: GENERIC_MESSAGE });
    const user = userEvent.setup();

    render(
      <ToastProvider>
        <ForgotPassword onChangeView={vi.fn()} />
      </ToastProvider>
    );

    await user.type(screen.getByPlaceholderText('Email Address'), 'known@example.com');
    await user.click(screen.getByText('Continue'));

    await waitFor(() => expect(screen.getByText(GENERIC_MESSAGE)).toBeInTheDocument());
  });

  it('shows the identical generic confirmation for an unknown-looking email', async () => {
    (requestPasswordReset as any).mockResolvedValue({ message: GENERIC_MESSAGE });
    const user = userEvent.setup();

    render(
      <ToastProvider>
        <ForgotPassword onChangeView={vi.fn()} />
      </ToastProvider>
    );

    await user.type(screen.getByPlaceholderText('Email Address'), 'definitely-not-registered@example.com');
    await user.click(screen.getByText('Continue'));

    await waitFor(() => expect(screen.getByText(GENERIC_MESSAGE)).toBeInTheDocument());
  });

  it('validates email format client-side before submitting', async () => {
    const user = userEvent.setup();

    render(
      <ToastProvider>
        <ForgotPassword onChangeView={vi.fn()} />
      </ToastProvider>
    );

    await user.type(screen.getByPlaceholderText('Email Address'), 'not-an-email');
    await user.click(screen.getByText('Continue'));

    expect(await screen.findByText('Please enter a valid email address')).toBeInTheDocument();
    expect(requestPasswordReset).not.toHaveBeenCalled();
  });

  it('calls onChangeView(SIGN_IN) when Back to Sign In is clicked', async () => {
    const onChangeView = vi.fn();
    const user = userEvent.setup();

    render(
      <ToastProvider>
        <ForgotPassword onChangeView={onChangeView} />
      </ToastProvider>
    );

    await user.click(screen.getByText('Back to Sign In'));
    expect(onChangeView).toHaveBeenCalledWith(AuthView.SIGN_IN);
  });
});
