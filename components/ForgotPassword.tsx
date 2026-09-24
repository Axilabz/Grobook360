import React, { useState } from 'react';
import { ArrowLeft, Loader2, MailCheck } from 'lucide-react';
import Input from './Input';
import { AuthView } from '../types';
import { requestPasswordReset } from '../api/passwordReset';
import { ApiError } from '../api/client';

interface ForgotPasswordProps {
  onChangeView: (view: AuthView) => void;
}

// PROMPT-004 S7/S8: identifier is email (see PROMPT-004-NOTES.md — OTP-to-phone
// is out of scope, so a link-based channel needs the only other stored
// identifier). The response is identical whether or not an account matches —
// this screen never learns which case occurred, by design.
const ForgotPassword: React.FC<ForgotPasswordProps> = ({ onChangeView }) => {
  const [identifier, setIdentifier] = useState('');
  const [error, setError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [genericMessage, setGenericMessage] = useState('');

  const validate = (): boolean => {
    if (!identifier.trim()) {
      setError('Please enter your registered email address');
      return false;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(identifier)) {
      setError('Please enter a valid email address');
      return false;
    }
    return true;
  };

  const handleSubmit = async () => {
    if (!validate()) return;
    if (isSubmitting) return;

    setIsSubmitting(true);
    try {
      const result = await requestPasswordReset(identifier);
      setGenericMessage(result.message);
      setSubmitted(true);
    } catch (err) {
      // Even on rate-limit (429) the server returns the same generic message
      // body (S8) — surface it the same way as success rather than a distinct
      // error state, so the UI itself can't become an enumeration signal.
      if (err instanceof ApiError && err.status === 429) {
        setGenericMessage(err.message);
        setSubmitted(true);
      } else {
        setError('Something went wrong. Please try again later.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl overflow-hidden w-full max-w-md mx-auto border border-gray-100 dark:border-gray-700 relative z-10 animate-fade-in transition-colors">
        <div className="p-8 pt-6 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-900/40">
            <MailCheck size={28} className="text-blue-600 dark:text-blue-400" />
          </div>
          <h1 className="text-[22px] font-bold text-gray-900 dark:text-white mb-2">Check Your Email</h1>
          <p className="text-[14px] text-gray-500 dark:text-gray-400 mb-8">{genericMessage}</p>
          <button
            onClick={() => onChangeView(AuthView.SIGN_IN)}
            className="w-full bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] md:text-[16px] py-3 rounded-lg transition-colors duration-200"
          >
            Back to Sign In
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl overflow-hidden w-full max-w-md mx-auto border border-gray-100 dark:border-gray-700 relative z-10 animate-fade-in transition-colors">
      <div className="p-8 pt-6">
        <button
          onClick={() => onChangeView(AuthView.SIGN_IN)}
          className="flex items-center gap-1 text-[13px] text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 mb-4"
        >
          <ArrowLeft size={16} /> Back to Sign In
        </button>

        <h1 className="text-[26px] md:text-[30px] font-bold text-gray-900 dark:text-white mb-1 leading-tight tracking-tight">
          Forgot Password
        </h1>
        <p className="text-[14px] md:text-[16px] text-gray-500 dark:text-gray-400 mb-8 font-normal leading-[1.4]">
          Enter your registered account email and we'll provide instructions if an account is eligible for password recovery.
        </p>

        <form noValidate onSubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
          <Input
            label="Email Address"
            type="email"
            value={identifier}
            onChange={(e) => {
              setIdentifier(e.target.value);
              if (error) setError(undefined);
            }}
            error={error}
          />

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] md:text-[16px] py-3 rounded-lg transition-colors duration-200 leading-[1.3] tracking-wide mt-2 disabled:opacity-70 flex items-center justify-center gap-2"
          >
            {isSubmitting && <Loader2 size={18} className="animate-spin" />}
            {isSubmitting ? 'Submitting…' : 'Continue'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default ForgotPassword;
