import { apiRequest } from './client';

export async function requestPasswordReset(recoveryIdentifier: string): Promise<{ message: string }> {
  return apiRequest<{ message: string }>('/auth/forgot-password', {
    method: 'POST',
    body: { recovery_identifier: recoveryIdentifier },
  });
}

export async function validateResetToken(token: string): Promise<{ valid: boolean }> {
  return apiRequest<{ valid: boolean }>('/auth/reset-password/validate', {
    method: 'POST',
    body: { token },
  });
}

export async function resetPassword(token: string, newPassword: string, confirmPassword: string): Promise<{ status: string }> {
  return apiRequest<{ status: string }>('/auth/reset-password', {
    method: 'POST',
    body: { token, new_password: newPassword, confirm_password: confirmPassword },
  });
}
