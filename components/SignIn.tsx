import React, { useState } from 'react';
import { Eye, EyeOff, Loader2 } from 'lucide-react';
import Input from './Input';
import { AuthView } from '../types';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import { ApiError } from '../api/client';

interface SignInProps {
  onChangeView: (view: AuthView) => void;
  onLoginSuccess: () => void;
}

const SignIn: React.FC<SignInProps> = ({ onChangeView, onLoginSuccess }) => {
  const [showPassword, setShowPassword] = useState(false);
  const [formData, setFormData] = useState({ phone: '', password: '' });
  const [formErrors, setFormErrors] = useState<{ phone?: string; password?: string }>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { showToast } = useToast();
  const { login, sessionExpired } = useAuth();

  const validate = (): boolean => {
    const errors: { phone?: string; password?: string } = {};
    if (!formData.phone.trim()) errors.phone = 'Please enter your phone number';
    else if (!/^\d{10}$/.test(formData.phone)) errors.phone = 'Phone must be exactly 10 digits';
    if (!formData.password) errors.password = 'Please enter your password';
    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleLogin = async () => {
    // Client-side validation improves UX only — the server remains the
    // authoritative check (PROMPT-003 S8).
    if (!validate()) return;
    if (isSubmitting) return;

    setIsSubmitting(true);
    try {
      await login(formData.phone, formData.password);
      onLoginSuccess();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          showToast('Invalid login credentials.', 'error');
        } else if (err.status === 403) {
          showToast(err.message || 'Your account is inactive. Contact your administrator.', 'error');
        } else if (err.status === 429) {
          showToast('Too many attempts. Please wait a while before trying again.', 'error');
        } else {
          showToast(err.message || 'Sign in failed. Please try again.', 'error');
        }
      } else {
        showToast('Network error. Please check your connection and try again.', 'error');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl overflow-hidden w-full max-w-md mx-auto border border-gray-100 dark:border-gray-700 relative z-10 animate-fade-in transition-colors">
        <div className="p-8 pt-6">
          <h1 className="text-[26px] md:text-[30px] lg:text-[32px] font-bold text-gray-900 dark:text-white mb-1 leading-tight tracking-tight">
            GroBook 360
          </h1>
          <p className="text-[14px] md:text-[16px] text-gray-500 dark:text-gray-400 mb-8 font-normal leading-[1.4]">
            Sign In To Access Book
          </p>

          {sessionExpired && (
            <div className="mb-6 rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-700 p-3 text-[13px] text-amber-800 dark:text-amber-300">
              Your session has expired. Please sign in again.
            </div>
          )}

          <form onSubmit={(e) => { e.preventDefault(); handleLogin(); }}>
            <Input
              label="Phone Number"
              value={formData.phone}
              maxLength={10}
              inputMode="numeric"
              onChange={(e) => {
                setFormData({ ...formData, phone: e.target.value.replace(/\D/g, '') });
                if (formErrors.phone) setFormErrors({ ...formErrors, phone: undefined });
              }}
              error={formErrors.phone}
              type="tel"
            />

            <Input
              label="Password"
              type={showPassword ? 'text' : 'password'}
              value={formData.password}
              onChange={(e) => {
                setFormData({ ...formData, password: e.target.value });
                if (formErrors.password) setFormErrors({ ...formErrors, password: undefined });
              }}
              error={formErrors.password}
              icon={showPassword ? <Eye size={20} /> : <EyeOff size={20} />}
              onIconClick={() => setShowPassword(!showPassword)}
            />

            <div className="flex items-center justify-between mb-6 mt-2">
              <label className="flex items-center cursor-pointer">
                <input type="checkbox" className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:bg-gray-700 dark:border-gray-600" />
                <span className="ml-2 text-[12px] md:text-[14px] text-gray-500 dark:text-gray-400 font-normal">Remember Me</span>
              </label>
              <button
                type="button"
                onClick={() => onChangeView(AuthView.FORGOT_PASSWORD)}
                className="text-[12px] md:text-[14px] text-blue-500 hover:underline font-medium"
              >
                Forget Password ?
              </button>
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] md:text-[16px] py-3 rounded-lg transition-colors duration-200 leading-[1.3] tracking-wide mb-6 disabled:opacity-70 flex items-center justify-center gap-2"
            >
              {isSubmitting && <Loader2 size={18} className="animate-spin" />}
              {isSubmitting ? 'Signing In…' : 'Log in'}
            </button>
          </form>

          <div className="text-center border-t border-[#A39797] dark:border-gray-600 pt-4">
            <p className="text-[12px] md:text-[14px] text-gray-600 dark:text-gray-400">
              Don't have a GroBook 360 Account ?{' '}
              <button
                  onClick={() => onChangeView(AuthView.SIGN_UP)}
                  className="text-blue-600 dark:text-blue-400 font-bold hover:underline uppercase"
              >
                SIGN UP
              </button>
            </p>
          </div>
        </div>
      </div>
  );
};

export default SignIn;
