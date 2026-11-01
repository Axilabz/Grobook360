import React, { useState } from 'react';
import { Eye, EyeOff, Building2, FileText, User, ClipboardCheck, Check, Loader2, AlertTriangle } from 'lucide-react';
import Input from './Input';
import Select from './Select';
import { AuthView } from '../types';
import { useToast } from '../context/ToastContext';
import { GST_STATE_CODES, formatStateOption, parseStateCode } from '../data/gstStateCodes';
import { INDIA_STATE_CITIES, BUSINESS_TYPE_OPTIONS } from '../data/indiaStateCities';
import { signUp } from '../api/signup';
import { ApiError } from '../api/client';

interface SignUpProps {
  onChangeView: (view: AuthView) => void;
}

type Step = 1 | 2 | 3 | 4;

// Password complexity: exact policy is a pending BA/product decision (see
// backend PROMPT-002-NOTES.md) — this enforces only the documented minimum.
const PASSWORD_MIN_LENGTH = 8;

const STATE_OPTIONS = GST_STATE_CODES.map((s) => formatStateOption(s.code, s.name));

function cityOptionsForState(stateOption: string): string[] {
  if (!stateOption) return [];
  return INDIA_STATE_CITIES[parseStateCode(stateOption)] ?? [];
}

const SignUp: React.FC<SignUpProps> = ({ onChangeView }) => {
  const [step, setStep] = useState<Step>(1);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'success' | 'failed'>('idle');
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);
  const [createdTenantId, setCreatedTenantId] = useState<string | null>(null);

  const { showToast } = useToast();

  const [org, setOrg] = useState({
    businessName: '',
    businessType: '',
    addressLine1: '',
    city: '',
    stateOption: '',
    pinCode: '',
  });

  const [noGst, setNoGst] = useState(false);
  const [gstin, setGstin] = useState('');

  const [owner, setOwner] = useState({
    name: '',
    phone: '',
    email: '',
    password: '',
    confirmPassword: '',
  });

  const [errors, setErrors] = useState<Record<string, string>>({});

  const cityOptions = cityOptionsForState(org.stateOption);

  const setFieldError = (field: string, message?: string) => {
    setErrors((prev) => {
      const next = { ...prev };
      if (message) next[field] = message;
      else delete next[field];
      return next;
    });
  };

  // Any edit after a failed/successful attempt invalidates the previous
  // idempotency key — a materially different retry must not collide with it.
  const invalidateIdempotencyKey = () => {
    if (idempotencyKey) setIdempotencyKey(null);
    if (submitState === 'failed') setSubmitState('idle');
  };

  const validateStep1 = (): boolean => {
    const next: Record<string, string> = {};
    if (!org.businessName.trim()) next.businessName = 'Please enter the organization / business name';
    if (!org.businessType) next.businessType = 'Please select the business type';
    if (!org.addressLine1.trim()) next.addressLine1 = 'Please enter the address';
    if (!org.stateOption) next.stateOption = 'Please select the state';
    if (!org.city.trim()) next.city = 'Please select the city';
    if (!/^\d{6}$/.test(org.pinCode)) next.pinCode = 'Please enter a valid 6-digit PIN code';
    setErrors((prev) => ({ ...prev, ...next }));
    return Object.keys(next).length === 0;
  };

  const validateStep2 = (): boolean => {
    if (noGst) {
      setFieldError('gstin');
      return true;
    }
    if (!gstin) return true; // GSTIN optional (FR-SU-03: non-GST businesses may omit it)
    const gstinPattern = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;
    if (!gstinPattern.test(gstin)) {
      setFieldError('gstin', 'Invalid GSTIN format');
      return false;
    }
    setFieldError('gstin');
    return true;
  };

  const validateStep3 = (): boolean => {
    const next: Record<string, string> = {};
    if (!owner.name.trim()) next.name = "Please enter the owner's name";
    if (!/^\d{10}$/.test(owner.phone)) next.phone = 'Phone must be exactly 10 numeric digits';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(owner.email)) next.email = 'Invalid email format';
    if (owner.password.length < PASSWORD_MIN_LENGTH) {
      next.password = `Password must be at least ${PASSWORD_MIN_LENGTH} characters`;
    }
    if (owner.password !== owner.confirmPassword) next.confirmPassword = 'Password and confirmation do not match';
    setErrors((prev) => ({ ...prev, ...next }));
    return Object.keys(next).length === 0;
  };

  const goNext = () => {
    if (step === 1 && validateStep1()) setStep(2);
    else if (step === 2 && validateStep2()) setStep(3);
    else if (step === 3 && validateStep3()) setStep(4);
  };

  const goBack = () => {
    invalidateIdempotencyKey();
    if (step > 1) setStep(((step - 1) as Step));
  };

  const handleConfirmSubmit = async () => {
    const key = idempotencyKey ?? crypto.randomUUID();
    if (!idempotencyKey) setIdempotencyKey(key);

    setSubmitState('submitting');
    try {
      const result = await signUp(
        {
          organization: {
            business_name: org.businessName,
            business_type: org.businessType || null,
            address_line1: org.addressLine1,
            city: org.city,
            state_code: parseStateCode(org.stateOption),
            pin_code: org.pinCode,
            gstin: noGst || !gstin ? null : gstin,
          },
          owner: {
            name: owner.name,
            phone: owner.phone,
            email: owner.email,
            password: owner.password,
            confirm_password: owner.confirmPassword,
          },
        },
        key
      );
      setCreatedTenantId(result.tenant_id);
      setSubmitState('success');
    } catch (err) {
      setSubmitState('failed');
      if (err instanceof ApiError) {
        if (err.status === 429) {
          showToast('Too many attempts. Please wait a while before trying again.', 'error');
        } else if (err.status === 409) {
          showToast(err.message || 'This registration could not be completed.', 'error');
        } else {
          showToast(err.message || 'Registration failed. Please try again.', 'error');
        }
      } else {
        showToast('Network error. Please check your connection and try again.', 'error');
      }
    }
  };

  const steps: { id: Step; label: string; icon: React.ReactNode }[] = [
    { id: 1, label: 'Organization', icon: <Building2 size={18} /> },
    { id: 2, label: 'GST Details', icon: <FileText size={18} /> },
    { id: 3, label: 'Owner Account', icon: <User size={18} /> },
    { id: 4, label: 'Review', icon: <ClipboardCheck size={18} /> },
  ];

  if (submitState === 'success' && createdTenantId) {
    return (
      <div className="bg-white dark:bg-gray-800 w-full mx-auto max-w-lg md:rounded-xl md:shadow-2xl md:overflow-hidden md:border md:border-gray-100 dark:border-gray-700 p-6 sm:p-10 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/40">
          <Check size={28} className="text-green-600 dark:text-green-400" />
        </div>
        <h1 className="text-[22px] font-bold text-gray-900 dark:text-white mb-2">Account Created</h1>
        <p className="text-[14px] text-gray-500 dark:text-gray-400 mb-8">
          Your organization has been registered successfully. You can now sign in with your new account.
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
    <div className="bg-white dark:bg-gray-800 w-full mx-auto max-w-3xl md:rounded-xl md:shadow-2xl md:overflow-hidden md:border md:border-gray-100 dark:border-gray-700 relative transition-colors">
      <div className="p-4 sm:p-8">
        <h1 className="text-[26px] md:text-[30px] font-bold text-gray-900 dark:text-white mb-1 leading-tight tracking-tight">
          GroBook 360
        </h1>
        <p className="text-[14px] md:text-[16px] text-gray-500 dark:text-gray-400 mb-6 font-normal leading-[1.4]">
          Create an account to access your business
        </p>

        {/* Step indicator: full labels on tablet/desktop, compact dots on mobile */}
        <div className="mb-8">
          <div className="hidden sm:flex items-center justify-between">
            {steps.map((s, idx) => (
              <React.Fragment key={s.id}>
                <div className={`flex items-center gap-2 ${step === s.id ? 'text-black dark:text-white font-bold' : step > s.id ? 'text-blue-600 dark:text-blue-400' : 'text-gray-400 dark:text-gray-500'}`}>
                  <div className={`p-1.5 rounded-md ${step === s.id ? 'bg-blue-600 text-white' : step > s.id ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400' : 'bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400'}`}>
                    {step > s.id ? <Check size={18} /> : s.icon}
                  </div>
                  <span className="text-[13px] md:text-[14px]">{s.label}</span>
                </div>
                {idx < steps.length - 1 && (
                  <div className="flex-1 h-0.5 bg-gray-300 dark:bg-gray-600 mx-2">
                    <div className={`h-full bg-blue-600 transition-all duration-300 ${step > s.id ? 'w-full' : 'w-0'}`} />
                  </div>
                )}
              </React.Fragment>
            ))}
          </div>
          <div className="flex sm:hidden items-center justify-center gap-2">
            {steps.map((s) => (
              <div
                key={s.id}
                className={`h-2 rounded-full transition-all ${step === s.id ? 'w-6 bg-blue-600' : step > s.id ? 'w-2 bg-blue-300' : 'w-2 bg-gray-300 dark:bg-gray-600'}`}
              />
            ))}
          </div>
          <p className="sm:hidden text-center text-[13px] font-medium text-gray-700 dark:text-gray-300 mt-2">
            Step {step} of 4 — {steps[step - 1].label}
          </p>
        </div>

        {step === 1 && (
          <div className="animate-fade-in">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
              <Input
                label="Business / Organization Name"
                value={org.businessName}
                onChange={(e) => {
                  setOrg({ ...org, businessName: e.target.value });
                  setFieldError('businessName');
                  invalidateIdempotencyKey();
                }}
                error={errors.businessName}
              />
              <Select
                label="Business Type"
                options={BUSINESS_TYPE_OPTIONS}
                value={org.businessType}
                onChange={(val) => {
                  setOrg({ ...org, businessType: val });
                  setFieldError('businessType');
                  invalidateIdempotencyKey();
                }}
                error={errors.businessType}
              />
            </div>
            <div className="grid grid-cols-1">
              <Input
                label="Address"
                value={org.addressLine1}
                onChange={(e) => {
                  setOrg({ ...org, addressLine1: e.target.value });
                  setFieldError('addressLine1');
                  invalidateIdempotencyKey();
                }}
                error={errors.addressLine1}
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6">
              <Select
                label="City"
                options={cityOptions}
                value={org.city}
                disabled={!org.stateOption}
                onChange={(val) => {
                  setOrg({ ...org, city: val });
                  setFieldError('city');
                  invalidateIdempotencyKey();
                }}
                error={errors.city}
              />
              <Select
                label="State"
                options={STATE_OPTIONS}
                value={org.stateOption}
                onChange={(val) => {
                  const cityStillValid = INDIA_STATE_CITIES[parseStateCode(val)]?.includes(org.city);
                  setOrg({ ...org, stateOption: val, city: cityStillValid ? org.city : '' });
                  setFieldError('stateOption');
                  invalidateIdempotencyKey();
                }}
                error={errors.stateOption}
              />
              <Input
                label="PIN Code"
                value={org.pinCode}
                maxLength={6}
                onChange={(e) => {
                  setOrg({ ...org, pinCode: e.target.value.replace(/\D/g, '') });
                  setFieldError('pinCode');
                  invalidateIdempotencyKey();
                }}
                error={errors.pinCode}
              />
            </div>
            {!org.stateOption && (
              <p className="text-[12px] text-gray-400 dark:text-gray-500 -mt-6 mb-6">
                Select a state to unlock its city list.
              </p>
            )}

            <div className="flex justify-end mt-2">
              <button
                onClick={goNext}
                className="bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] md:text-[16px] py-3 px-12 rounded-lg transition-colors duration-200 w-full sm:w-auto"
              >
                Next
              </button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="animate-fade-in">
            <label className="flex items-center gap-2 mb-6 text-[14px] text-gray-700 dark:text-gray-300">
              <input
                type="checkbox"
                className="h-4 w-4 accent-blue-600"
                checked={noGst}
                onChange={(e) => {
                  setNoGst(e.target.checked);
                  invalidateIdempotencyKey();
                }}
              />
              This business does not have GST registration
            </label>

            {!noGst && (
              <>
                <Input
                  label="GSTIN (optional)"
                  value={gstin}
                  maxLength={15}
                  onChange={(e) => {
                    setGstin(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''));
                    setFieldError('gstin');
                    invalidateIdempotencyKey();
                  }}
                  error={errors.gstin}
                />
              </>
            )}

            <div className="grid grid-cols-2 gap-4 mt-2">
              <button
                onClick={goBack}
                className="bg-blue-100 dark:bg-gray-700 hover:bg-blue-200 dark:hover:bg-gray-600 text-blue-700 dark:text-gray-200 font-semibold text-[15px] md:text-[16px] py-3 rounded-lg transition-colors duration-200 w-full"
              >
                Back
              </button>
              <button
                onClick={goNext}
                className="bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] md:text-[16px] py-3 rounded-lg transition-colors duration-200 w-full"
              >
                Next
              </button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="animate-fade-in">
            <div className="grid grid-cols-1">
              <Input
                label="Owner Name"
                value={owner.name}
                onChange={(e) => {
                  setOwner({ ...owner, name: e.target.value });
                  setFieldError('name');
                  invalidateIdempotencyKey();
                }}
                error={errors.name}
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
              <Input
                label="Phone Number"
                value={owner.phone}
                maxLength={10}
                inputMode="numeric"
                onChange={(e) => {
                  setOwner({ ...owner, phone: e.target.value.replace(/\D/g, '') });
                  setFieldError('phone');
                  invalidateIdempotencyKey();
                }}
                error={errors.phone}
              />
              <Input
                label="Email ID"
                type="email"
                value={owner.email}
                onChange={(e) => {
                  setOwner({ ...owner, email: e.target.value });
                  setFieldError('email');
                  invalidateIdempotencyKey();
                }}
                error={errors.email}
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
              <Input
                label="Password"
                type={showPassword ? 'text' : 'password'}
                value={owner.password}
                onChange={(e) => {
                  setOwner({ ...owner, password: e.target.value });
                  setFieldError('password');
                  invalidateIdempotencyKey();
                }}
                error={errors.password}
                icon={showPassword ? <Eye size={20} /> : <EyeOff size={20} />}
                onIconClick={() => setShowPassword(!showPassword)}
              />
              <Input
                label="Confirm Password"
                type={showConfirmPassword ? 'text' : 'password'}
                value={owner.confirmPassword}
                onChange={(e) => {
                  setOwner({ ...owner, confirmPassword: e.target.value });
                  setFieldError('confirmPassword');
                  invalidateIdempotencyKey();
                }}
                error={errors.confirmPassword}
                icon={showConfirmPassword ? <Eye size={20} /> : <EyeOff size={20} />}
                onIconClick={() => setShowConfirmPassword(!showConfirmPassword)}
              />
            </div>

            <div className="grid grid-cols-2 gap-4 mt-2">
              <button
                onClick={goBack}
                className="bg-blue-100 dark:bg-gray-700 hover:bg-blue-200 dark:hover:bg-gray-600 text-blue-700 dark:text-gray-200 font-semibold text-[15px] md:text-[16px] py-3 rounded-lg transition-colors duration-200 w-full"
              >
                Back
              </button>
              <button
                onClick={goNext}
                className="bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] md:text-[16px] py-3 rounded-lg transition-colors duration-200 w-full"
              >
                Review
              </button>
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="animate-fade-in">
            <div className="space-y-4 mb-6">
              <div>
                <h3 className="text-[12px] uppercase tracking-wider text-gray-500 dark:text-gray-400 font-semibold mb-2">
                  Organization
                </h3>
                <div className="bg-gray-50 dark:bg-gray-900 p-3 rounded text-[14px] space-y-1 border border-gray-100 dark:border-gray-700">
                  <p><span className="font-medium">Name:</span> {org.businessName}</p>
                  <p><span className="font-medium">Business Type:</span> {org.businessType}</p>
                  <p><span className="font-medium">Address:</span> {org.addressLine1}, {org.city}</p>
                  <p><span className="font-medium">State:</span> {org.stateOption}</p>
                  <p><span className="font-medium">PIN:</span> {org.pinCode}</p>
                  <p><span className="font-medium">GST Status:</span> {noGst ? 'Not GST registered' : gstin ? 'GST registered' : 'GSTIN not provided'}</p>
                  {!noGst && gstin && <p><span className="font-medium">GSTIN:</span> {gstin}</p>}
                </div>
              </div>
              <div>
                <h3 className="text-[12px] uppercase tracking-wider text-gray-500 dark:text-gray-400 font-semibold mb-2">
                  Owner Account
                </h3>
                <div className="bg-gray-50 dark:bg-gray-900 p-3 rounded text-[14px] space-y-1 border border-gray-100 dark:border-gray-700">
                  <p><span className="font-medium">Name:</span> {owner.name}</p>
                  <p><span className="font-medium">Phone:</span> {owner.phone}</p>
                  <p><span className="font-medium">Email:</span> {owner.email}</p>
                </div>
              </div>
            </div>

            {submitState === 'failed' && (
              <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-700 p-3 text-[13px] text-amber-800 dark:text-amber-300">
                <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
                <span>The last attempt failed. It's safe to retry — this won't create a duplicate account.</span>
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <button
                onClick={goBack}
                disabled={submitState === 'submitting'}
                className="bg-blue-100 dark:bg-gray-700 hover:bg-blue-200 dark:hover:bg-gray-600 text-blue-700 dark:text-gray-200 font-semibold text-[15px] md:text-[16px] py-3 rounded-lg transition-colors duration-200 w-full disabled:opacity-50"
              >
                Edit
              </button>
              <button
                onClick={handleConfirmSubmit}
                disabled={submitState === 'submitting'}
                className="bg-[#0066ff] hover:bg-blue-700 text-white font-semibold text-[15px] md:text-[16px] py-3 rounded-lg transition-colors duration-200 w-full disabled:opacity-70 flex items-center justify-center gap-2"
              >
                {submitState === 'submitting' && <Loader2 size={18} className="animate-spin" />}
                {submitState === 'submitting'
                  ? 'Creating Account…'
                  : submitState === 'failed'
                  ? 'Retry'
                  : 'Confirm & Create Account'}
              </button>
            </div>
          </div>
        )}

        <div className="text-center border-t border-gray-200 dark:border-gray-600 pt-6 mt-6">
          <p className="text-[12px] md:text-[14px] text-gray-600 dark:text-gray-400">
            Already have a GroBook 360 account?{' '}
            <button onClick={() => onChangeView(AuthView.SIGN_IN)} className="text-blue-600 dark:text-blue-400 font-bold hover:underline">
              Sign In / Log In
            </button>
          </p>
        </div>
      </div>
    </div>
  );
};

export default SignUp;
