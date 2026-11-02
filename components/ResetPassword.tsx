import React, { useEffect, useState } from 'react';
import { Eye, EyeOff, Loader2, CheckCircle2, XCircle } from 'lucide-react';
import Input from './Input';
import { AuthView } from '../types';
import { validateResetToken, resetPassword } from '../api/passwordReset';
import { ApiError } from '../api/client';
import LoadingState from '../shared/LoadingState';

interface ResetPasswordProps {
  token: string;
  onChangeView: (view: AuthView) => void;
}

const PASSWORD_MIN_LENGTH = 8; // matches backend settings.password_min_length placeholder

type ScreenState = 'checking-token' | 'invalid-token' | 'form' | 'success';

const ResetPassword: React.FC<ResetPasswordProps> = ({ token, onChangeView }) => {
  const [screenState, setScreenState] = useState<ScreenState>('checking-token');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [errors, setErrors] = useState<{ password?: string; confirmPassword?: string }>({});
  const [submitError, setSubmitError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Pre-validate (PROMPT-004 S22) so the user isn't left filling a form for a
  // link that's already dead — a cheap, read-only check.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await validateResetToken(token);
        if (cancelled) return;
        setScreenState(result.valid ? 'form' : 'invalid-token');
      } catch {
        if (!cancelled) setScreenState('invalid-token');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const validate = (): boolean => {
    const next: { password?: string; confirmPassword?: string } = {};
    if (password.length < PASSWORD_MIN_LENGTH) {
      next.password = `Password must be at least ${PASSWORD_MIN_LENGTH} characters`;
    }
    if (password !== confirmPassword) {
      next.confirmPassword = 'Passwords do not match';
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSubmit = async () => {
    setSubmitError(undefined);
    if (!validate()) return;
    if (isSubmitting) return;

    setIsSubmitting(true);
    try {
      await resetPassword(token, password, confirmPassword);
      setScreenState('success');
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 429) {
          setSubmitError('Please wait before trying again.');
        } else if (['RESET-002', 'RESET-003', 'RESET-004', 'RESET-005'].includes(err.code)) {
          // Token became invalid between pre-validation and submit (race /
          // already used elsewhere) — show the same dead-link screen.
          setScreenState('invalid-token');
        } else {
          setSubmitError(err.message || 'Something went wrong. Please try again later.');
        }
      } else {
        setSubmitError('Network error. Please check your connection and try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (screenState === 'checking-token') {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl overflow-hidden w-full max-w-md mx-auto border border-gray-100 dark:border-gray-700 p-10 text-center">
        <LoadingState bare label="Checking your reset link…" />
      </div>
    );
  }

  if (screenState === 'invalid-token') {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl overflow-hidden w-full max-w-md mx-auto border border-gray-100 dark:border-gray-700 p-8 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-100 dark:bg-red-900/40">
          <XCircle size={28} className="text-red-600 dark:text-red-400" />
        </div>
        <h1 className="text-[22px] font-bold text-gray-900 dark:text-white mb-2">Link Invalid or Expired</h1>
        <p className="text-[14px] text-gray-500 dark:text-gray-400 mb-8">
          This password reset link is invalid or has expired. Please request a new one.
        </p>
        <button
          onClick={() => onChangeView(AuthView.FORGOT_PASSWORD)}
          className="w-full bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] md:text-[16px] py-3 rounded-lg transition-colors duration-200 mb-3"
        >
          Request a New Link
        </button>
        <button
          onClick={() => onChangeView(AuthView.SIGN_IN)}
          className="w-full text-[13px] text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
        >
          Back to Sign In
        </button>
      </div>
    );
  }

  if (screenState === 'success') {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl overflow-hidden w-full max-w-md mx-auto border border-gray-100 dark:border-gray-700 p-8 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/40">
          <CheckCircle2 size={28} className="text-green-600 dark:text-green-400" />
        </div>
        <h1 className="text-[22px] font-bold text-gray-900 dark:text-white mb-2">Password Reset</h1>
        <p className="text-[14px] text-gray-500 dark:text-gray-400 mb-8">
          Your password has been changed. For your security, you've been signed out everywhere and need to sign in again.
        </p>
        <button
          onClick={() => onChangeView(AuthView.SIGN_IN)}
          className="w-full bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] md:text-[16px] py-3 rounded-lg transition-colors duration-200"
        >
          Continue to Sign In
        </button>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl overflow-hidden w-full max-w-md mx-auto border border-gray-100 dark:border-gray-700 relative z-10 animate-fade-in transition-colors">
      <div className="p-8 pt-6">
        <h1 className="text-[26px] md:text-[30px] font-bold text-gray-900 dark:text-white mb-1 leading-tight tracking-tight">
          Reset Password
        </h1>
        <p className="text-[14px] md:text-[16px] text-gray-500 dark:text-gray-400 mb-8 font-normal leading-[1.4]">
          Choose a new password for your account. It must be at least {PASSWORD_MIN_LENGTH} characters.
        </p>

        {submitError && (
          <div className="mb-6 rounded-md border border-red-300 bg-red-50 dark:bg-red-900/20 dark:border-red-700 p-3 text-[13px] text-red-700 dark:text-red-300">
            {submitError}
          </div>
        )}

        <form noValidate onSubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
          <Input
            label="New Password"
            type={showPassword ? 'text' : 'password'}
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              if (errors.password) setErrors({ ...errors, password: undefined });
            }}
            error={errors.password}
            icon={showPassword ? <Eye size={20} /> : <EyeOff size={20} />}
            onIconClick={() => setShowPassword(!showPassword)}
          />
          <Input
            label="Confirm New Password"
            type={showConfirmPassword ? 'text' : 'password'}
            value={confirmPassword}
            onChange={(e) => {
              setConfirmPassword(e.target.value);
              if (errors.confirmPassword) setErrors({ ...errors, confirmPassword: undefined });
            }}
            error={errors.confirmPassword}
            icon={showConfirmPassword ? <Eye size={20} /> : <EyeOff size={20} />}
            onIconClick={() => setShowConfirmPassword(!showConfirmPassword)}
          />

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] md:text-[16px] py-3 rounded-lg transition-colors duration-200 leading-[1.3] tracking-wide mt-2 disabled:opacity-70 flex items-center justify-center gap-2"
          >
            {isSubmitting && <Loader2 size={18} className="animate-spin" />}
            {isSubmitting ? 'Resetting…' : 'Reset Password'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default ResetPassword;
