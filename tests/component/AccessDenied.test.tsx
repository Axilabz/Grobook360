import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import AccessDenied from '../../shared/AccessDenied';

describe('AccessDenied (RBAC Alignment Phase)', () => {
  it('renders a clear access-denied message', () => {
    render(<AccessDenied />);
    expect(screen.getByText('Access Denied')).toBeInTheDocument();
  });

  it('calls onGoHome when the button is clicked', () => {
    const onGoHome = vi.fn();
    render(<AccessDenied onGoHome={onGoHome} />);
    fireEvent.click(screen.getByText('Go to Home'));
    expect(onGoHome).toHaveBeenCalledTimes(1);
  });

  it('omits the button when onGoHome is not provided', () => {
    render(<AccessDenied />);
    expect(screen.queryByText('Go to Home')).not.toBeInTheDocument();
  });
});
