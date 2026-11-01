
import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { getInvoiceTemplateConfig, uploadBusinessLogo, removeBusinessLogo } from '../api/configuration';
import LogoCropModal from '../shared/LogoCropModal';
import { Building2, Mail, Phone, MapPin, Globe, PenLine, Save, Landmark, AlertTriangle, X, Loader2 } from 'lucide-react';
import Input from './Input';
import Select from './Select';
import { useToast } from '../context/ToastContext';
import { useNavigation } from '../context/NavigationContext';
import { ApiError, ConcurrencyConflictError } from '../api/client';
import { getTenantProfile, updateTenantProfile } from '../api/tenant';
import { stateNameForCode, stateCodeForName } from '../shared/gstStateCodes';

// "Country" is the one field with no real backend column (every tenant in
// this MVP is India-only, per the GST state-code scheme used everywhere
// else) — kept as a fixed, permanently-disabled display value rather than
// a real editable field.
const UNAVAILABLE_FIELD_NOTE = 'India-only for now — not an editable field.';

const ViewCompany: React.FC = () => {
  const [isEditing, setIsEditing] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [rowVersion, setRowVersion] = useState(0);
  const { showToast } = useToast();
  const { setBlocker, navigate } = useNavigation();

  // Modal State
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [pendingView, setPendingView] = useState<string | null>(null);

  const [tenantCode, setTenantCode] = useState('');

  const [companyData, setCompanyData] = useState({
    orgName: '',
    gstin: '',
    pan: '',
    businessType: '',
    phone: '',
    email: '',
    website: '',
    address: '',
    city: '',
    state: '',
    pincode: '',
    country: 'India',
    // Bank Details
    bankName: '',
    accountNumber: '',
    accountHolderName: '',
    ifscCode: '',
    branchName: '',
    accountType: '',
    upiId: ''
  });

  const [errors, setErrors] = useState<Record<string, string>>({});

  // Logo: stored with the invoice template config (same logo the invoice
  // print view uses), so it needs configuration.manage to change.
  const { hasPermission } = useAuth();
  const canManageLogo = hasPermission('configuration.manage');
  const canEditLogo = canManageLogo && isEditing;
  const [logoUri, setLogoUri] = useState<string | null>(null);
  const [cropFile, setCropFile] = useState<File | null>(null);
  const logoInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    getInvoiceTemplateConfig()
      .then((c) => { if (!cancelled) setLogoUri(c.logo_data_uri); })
      .catch(() => { /* no configuration.view — keep the initials placeholder */ });
    return () => { cancelled = true; };
  }, []);

  // A logo picked/removed while editing is only STAGED here; nothing hits
  // the server until "Save Details" (same as every other field on this
  // screen), and discarding the edit throws it away.
  const [pendingLogo, setPendingLogo] = useState<{ file: File; preview: string } | 'REMOVE' | null>(null);
  const shownLogo = pendingLogo === 'REMOVE' ? null : pendingLogo ? pendingLogo.preview : logoUri;
  const snapshotRef = useRef<typeof companyData | null>(null);

  const clearPendingLogo = () => {
    setPendingLogo((p) => {
      if (p && p !== 'REMOVE') URL.revokeObjectURL(p.preview);
      return null;
    });
  };

  const handleLogoConfirm = (cropped: File) => {
    clearPendingLogo();
    setPendingLogo({ file: cropped, preview: URL.createObjectURL(cropped) });
    setCropFile(null);
  };

  const handleLogoRemove = () => {
    clearPendingLogo();
    setPendingLogo('REMOVE');
  };

  // Persist a staged logo change (called after the profile itself saved).
  const commitLogo = async () => {
    if (!pendingLogo) return;
    if (pendingLogo === 'REMOVE') {
      await removeBusinessLogo();
      setLogoUri(null);
    } else {
      const updated = await uploadBusinessLogo(pendingLogo.file);
      setLogoUri(updated.logo_data_uri);
    }
    clearPendingLogo();
  };

  // Warn on tab close/refresh while there is an edit in progress.
  useEffect(() => {
    if (!isEditing) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [isEditing]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const profile = await getTenantProfile();
        if (cancelled) return;
        setRowVersion(profile.row_version);
        setTenantCode(profile.tenant_code);
        setCompanyData((prev) => ({
          ...prev,
          orgName: profile.business_name,
          gstin: profile.gstin || '',
          pan: profile.pan || '',
          businessType: profile.business_type || '',
          phone: profile.phone || '',
          email: profile.email || '',
          website: profile.website || '',
          address: profile.address_line1 || '',
          city: profile.city || '',
          state: stateNameForCode(profile.state_code) || '',
          pincode: profile.pin_code || '',
          bankName: profile.bank_name || '',
          accountNumber: profile.bank_account_number || '',
          accountHolderName: profile.bank_account_holder_name || '',
          ifscCode: profile.bank_ifsc || '',
          branchName: profile.bank_branch_name || '',
          accountType: profile.bank_account_type || '',
          upiId: profile.bank_upi_id || '',
        }));
      } catch (err) {
        if (!cancelled) showToast(err instanceof ApiError ? err.message : 'Failed to load company profile.', 'error');
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [showToast]);

  // Navigation Blocker Logic
  useEffect(() => {
    if (isEditing) {
        setBlocker((targetView) => {
            setPendingView(targetView);
            setShowConfirmModal(true);
            return false; // Prevent navigation
        });
    } else {
        setBlocker(null);
    }
    return () => setBlocker(null);
  }, [isEditing, setBlocker]);

  const validateField = (name: string, value: string) => {
    let error = '';

    switch (name) {
      // Organization Details
      case 'orgName':
        if (!value) error = "Organization Name is required";
        else if (value.length < 2) error = "Name must be at least 2 characters";
        break;
      case 'gstin':
        if (value && !/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/.test(value)) {
            error = "Invalid GSTIN Format (e.g. 33ABCDE1234F1Z5)";
        }
        break;
      case 'pan':
        if (value && !/^[A-Z]{5}[0-9]{4}[A-Z]{1}$/.test(value)) error = "Invalid PAN Format (e.g. ABCDE1234F)";
        break;

      // Contact Info — all optional (no sign-up flow captures any of
      // these today), only format-checked when actually supplied.
      case 'phone':
        if (value && !/^\d{10}$/.test(value)) error = "Invalid Phone Number (10 digits)";
        break;
      case 'email':
        if (value && !/^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(value)) error = "Invalid Email Format";
        break;
      case 'website':
        if (value && !/^((https?:\/\/)?(www\.)?)[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(\.[a-zA-Z]{2,})?$/.test(value)) {
             error = "Invalid Website URL";
        }
        break;

      // Address
      case 'address':
        if (!value) error = "Address is required";
        break;
      case 'city':
        if (!value) error = "City is required";
        break;
      case 'state':
        if (!value) error = "State is required";
        break;
      case 'pincode':
        if (!value) error = "Pincode is required";
        else if (!/^\d{6}$/.test(value)) error = "Invalid Pincode (6 digits)";
        break;

      // Bank Details — all optional, format-checked only when supplied.
      case 'accountNumber':
        if (value && !/^\d{9,18}$/.test(value)) error = "Invalid Account Number";
        break;
      case 'ifscCode':
        if (value && !/^[A-Z]{4}0[A-Z0-9]{6}$/.test(value)) error = "Invalid IFSC Code (e.g. HDFC0001234)";
        break;
      case 'upiId':
        if (value && !/^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$/.test(value)) error = "Invalid UPI ID Format (e.g. name@bank)";
        break;
    }

    setErrors(prev => {
      const newErr = { ...prev };
      if (error) newErr[name] = error;
      else delete newErr[name];
      return newErr;
    });
    
    return error;
  };

  const handleChange = (name: string, value: string) => {
    setCompanyData(prev => ({ ...prev, [name]: value }));
    if (errors[name]) {
        setErrors(prev => {
            const newErr = {...prev};
            delete newErr[name];
            return newErr;
        });
    }
  };

  const handleSave = async (): Promise<boolean> => {
      const fieldsToValidate = [
          'orgName', 'gstin', 'pan',
          'phone', 'email', 'website',
          'address', 'city', 'state', 'pincode',
          'accountNumber', 'ifscCode', 'upiId',
      ];

      let hasError = false;
      fieldsToValidate.forEach(field => {
          const val = (companyData as any)[field];
          const error = validateField(field, val);
          if (error) hasError = true;
      });

      if (hasError) {
          showToast("Please fix the errors before saving", "error");
          return false;
      }

      setIsSaving(true);
      try {
          const updated = await updateTenantProfile({
              business_name: companyData.orgName,
              gstin: companyData.gstin || null,
              state_code: stateCodeForName(companyData.state) || null,
              address_line1: companyData.address || null,
              city: companyData.city || null,
              pin_code: companyData.pincode || null,
              pan: companyData.pan || null,
              business_type: companyData.businessType || null,
              phone: companyData.phone || null,
              email: companyData.email || null,
              website: companyData.website || null,
              bank_name: companyData.bankName || null,
              bank_account_number: companyData.accountNumber || null,
              bank_account_holder_name: companyData.accountHolderName || null,
              bank_ifsc: companyData.ifscCode || null,
              bank_branch_name: companyData.branchName || null,
              bank_account_type: companyData.accountType || null,
              bank_upi_id: companyData.upiId || null,
              expected_row_version: rowVersion,
          });
          setRowVersion(updated.row_version);
          try {
              await commitLogo();
          } catch (logoErr) {
              // Profile fields are saved; keep editing so the logo can be retried.
              showToast(logoErr instanceof ApiError ? logoErr.message : 'Details saved, but the logo could not be uploaded.', 'error');
              return false;
          }
          setIsEditing(false);
          showToast("Company Profile Updated Successfully", "success");
          return true;
      } catch (err) {
          if (err instanceof ConcurrencyConflictError) {
              showToast("This profile was updated elsewhere — reload and try again.", "error");
          } else {
              showToast(err instanceof ApiError ? err.message : "Failed to save company profile.", "error");
          }
          return false;
      } finally {
          setIsSaving(false);
      }
  };

  const handleEditToggle = () => {
    if (isEditing) {
        void handleSave();
    } else {
        snapshotRef.current = companyData;
        setIsEditing(true);
    }
  };

  // Modal Handlers
  const handleConfirmDiscard = () => {
    setBlocker(null); // Unblock navigation
    if (snapshotRef.current) setCompanyData(snapshotRef.current); // Revert unsaved field edits
    clearPendingLogo();
    setErrors({});
    setIsEditing(false); // Reset editing state
    setShowConfirmModal(false);
    if (pendingView) navigate(pendingView); // Proceed to pending view
  };

  const handleConfirmSave = async () => {
    if (await handleSave()) {
        setBlocker(null);
        setShowConfirmModal(false);
        if (pendingView) navigate(pendingView);
    }
  };

  const darkCardClass = "bg-white dark:bg-gray-900";
  const darkLabelClass = "bg-white dark:bg-gray-900";
  const lockedClassName = !isEditing ? "!bg-white dark:!bg-gray-900 !text-gray-900 dark:!text-white !cursor-default !border-gray-200 dark:!border-gray-700" : "";
  // Same "locked" look as lockedClassName, but applied unconditionally —
  // for Country (see UNAVAILABLE_FIELD_NOTE), which stays disabled even
  // while isEditing is true, so it shouldn't fall back to the plain grey
  // disabled style the rest of this form uses.
  const unavailableClassName = "!bg-white dark:!bg-gray-900 !text-gray-900 dark:!text-white !cursor-not-allowed !border-gray-200 dark:!border-gray-700";

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 size={28} className="animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto p-4 md:p-8 animate-fade-in relative">
        {/* Sticky Header */}
        <div className="sticky top-16 z-30 bg-white dark:bg-gray-950 -mx-4 md:-mx-8 px-4 md:px-8 py-4 -mt-4 md:-mt-8 mb-6 border-b border-gray-100 dark:border-gray-800 transition-all flex items-center justify-between shadow-sm">
            <div className="flex items-center gap-3">
              <h2 className="text-[22px] md:text-[26px] lg:text-[28px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight leading-tight">Company Profile</h2>
              {tenantCode && (
                <span className="text-[12px] font-mono font-medium px-2.5 py-1 rounded-md bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 border border-blue-100 dark:border-blue-800">
                  {tenantCode}
                </span>
              )}
            </div>

            <button
                onClick={handleEditToggle}
                disabled={isSaving}
                className="flex items-center gap-2 px-6 py-2 rounded-lg shadow-sm transition-colors font-medium bg-[#0066ff] hover:bg-blue-700 text-white disabled:opacity-60 disabled:cursor-not-allowed"
            >
               {isSaving ? <><Loader2 size={18} className="animate-spin" /> Saving…</> : isEditing ? <><Save size={18} /> Save Details</> : <><PenLine size={18} /> Edit Profile</>}
            </button>
        </div>

        <div className="space-y-8">
            {/* --- Section 1: Basic Information --- */}
            <div className={`${darkCardClass} p-6 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm transition-colors`}>
                <h3 className="text-[16px] md:text-[18px] font-semibold text-gray-800 dark:text-gray-200 mb-6 border-b border-gray-100 dark:border-gray-700 pb-3 flex items-center gap-2">
                    <span className="bg-blue-100 dark:bg-blue-900/30 p-1.5 rounded text-blue-600 dark:text-blue-400"><Building2 size={16} /></span>
                    Organization Details
                </h3>
                
                <div className="flex flex-col md:flex-row gap-8">
                    {/* Logo Section */}
                    <div className="flex flex-col items-center justify-center space-y-3 w-full md:w-48 shrink-0">
                        <input
                            ref={logoInputRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
                            onChange={(e) => { const f = e.target.files?.[0]; if (f) setCropFile(f); e.target.value = ''; }}
                        />
                        <button
                            type="button" aria-label="Upload logo" disabled={!canEditLogo}
                            onClick={() => logoInputRef.current?.click()}
                            className="w-32 h-32 rounded-full bg-gray-100 dark:bg-gray-800 border-2 border-dashed border-gray-300 dark:border-gray-600 flex items-center justify-center text-gray-400 dark:text-gray-500 overflow-hidden relative group cursor-pointer disabled:cursor-not-allowed"
                        >
                            {shownLogo
                                ? <img src={shownLogo} alt="Company logo" className="w-full h-full object-cover" />
                                : <span className="text-4xl font-bold text-gray-300 dark:text-gray-600">{(companyData.orgName || 'AC').slice(0, 2).toUpperCase()}</span>}
                            {canEditLogo && (
                                <div className="absolute inset-0 bg-black/50 flex items-center justify-center opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity">
                                    <span className="text-white text-xs font-medium">Change Logo</span>
                                </div>
                            )}
                        </button>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                            {canEditLogo ? 'Click to upload logo' : canManageLogo ? 'Click Edit Profile to change logo' : 'Logo'}
                        </p>
                        {canEditLogo && shownLogo && (
                            <button type="button" onClick={handleLogoRemove} className="text-xs text-red-600 hover:underline">Remove logo</button>
                        )}
                        {pendingLogo && <p className="text-[11px] text-amber-600">Logo change not saved yet</p>}
                    </div>

                    {/* Fields */}
                    <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-x-6 w-full">
                        <Input
                            label="Organization Name"
                            value={companyData.orgName}
                            disabled={!isEditing}
                            labelClassName={darkLabelClass}
                            className={lockedClassName}
                            onChange={(e) => handleChange('orgName', e.target.value)}
                            onBlur={() => validateField('orgName', companyData.orgName)}
                            error={errors.orgName}
                        />
                        <Select
                            label="Business Type"
                            options={['Distributor', 'Super Stockist', 'Wholesaler', 'Retailer']}
                            value={companyData.businessType}
                            disabled={!isEditing}
                            labelClassName={darkLabelClass}
                            className={lockedClassName}
                            onChange={(val) => handleChange('businessType', val)}
                            error={errors.businessType}
                        />
                         <Input
                            label="GSTIN"
                            value={companyData.gstin}
                            disabled={!isEditing}
                            labelClassName={darkLabelClass}
                            className={lockedClassName}
                            onChange={(e) => handleChange('gstin', e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))}
                            onBlur={() => validateField('gstin', companyData.gstin)}
                            error={errors.gstin}
                            maxLength={15}
                        />
                         <Input
                            label="PAN"
                            value={companyData.pan}
                            disabled={!isEditing}
                            className={lockedClassName}
                            labelClassName={darkLabelClass}
                            onChange={(e) => handleChange('pan', e.target.value.toUpperCase())}
                            onBlur={() => validateField('pan', companyData.pan)}
                            error={errors.pan}
                            maxLength={10}
                        />
                    </div>
                </div>
            </div>

            {/* --- Section 2: Contact Information --- */}
            <div className={`${darkCardClass} p-6 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm transition-colors`}>
                <h3 className="text-[16px] md:text-[18px] font-semibold text-gray-800 dark:text-gray-200 mb-6 border-b border-gray-100 dark:border-gray-700 pb-3 flex items-center gap-2">
                     <span className="bg-blue-100 dark:bg-blue-900/30 p-1.5 rounded text-blue-600 dark:text-blue-400"><Phone size={16} /></span>
                     Contact Information
                </h3>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-6">
                    <Input
                        label="Phone Number"
                        value={companyData.phone}
                        disabled={!isEditing}
                        className={lockedClassName}
                        labelClassName={darkLabelClass}
                        icon={<Phone size={18} />}
                        onChange={(e) => handleChange('phone', e.target.value.replace(/\D/g, ''))}
                        onBlur={() => validateField('phone', companyData.phone)}
                        error={errors.phone}
                        maxLength={10}
                    />
                    <Input
                        label="Email Address"
                        value={companyData.email}
                        disabled={!isEditing}
                        className={lockedClassName}
                        labelClassName={darkLabelClass}
                        icon={<Mail size={18} />}
                        onChange={(e) => handleChange('email', e.target.value)}
                        onBlur={() => validateField('email', companyData.email)}
                        error={errors.email}
                    />
                    <Input
                        label="Website"
                        value={companyData.website}
                        disabled={!isEditing}
                        className={lockedClassName}
                        labelClassName={darkLabelClass}
                        icon={<Globe size={18} />}
                        onChange={(e) => handleChange('website', e.target.value)}
                        onBlur={() => validateField('website', companyData.website)}
                        error={errors.website}
                    />
                </div>
            </div>

            {/* --- Section 3: Address --- */}
            <div className={`${darkCardClass} p-6 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm transition-colors`}>
                <h3 className="text-[16px] md:text-[18px] font-semibold text-gray-800 dark:text-gray-200 mb-6 border-b border-gray-100 dark:border-gray-700 pb-3 flex items-center gap-2">
                     <span className="bg-blue-100 dark:bg-blue-900/30 p-1.5 rounded text-blue-600 dark:text-blue-400"><MapPin size={16} /></span>
                     Registered Address
                </h3>

                <div className="mb-6">
                    <Input
                        label="Street Address"
                        value={companyData.address}
                        disabled={!isEditing}
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
                        onChange={(e) => handleChange('address', e.target.value)}
                        onBlur={() => validateField('address', companyData.address)}
                        error={errors.address}
                    />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-x-6">
                    <Input
                        label="City / District"
                        value={companyData.city}
                        disabled={!isEditing}
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
                        onChange={(e) => handleChange('city', e.target.value)}
                        onBlur={() => validateField('city', companyData.city)}
                        error={errors.city}
                    />
                    <Select
                        label="State"
                        options={['Tamil Nadu', 'Kerala', 'Karnataka', 'Maharashtra']}
                        value={companyData.state}
                        disabled={!isEditing}
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
                        onChange={(val) => handleChange('state', val)}
                        error={errors.state}
                    />
                    <Input
                        label="Pincode"
                        value={companyData.pincode}
                        disabled={!isEditing}
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
                        onChange={(e) => handleChange('pincode', e.target.value.replace(/\D/g, ''))}
                        onBlur={() => validateField('pincode', companyData.pincode)}
                        error={errors.pincode}
                        maxLength={6}
                    />
                    <Input
                        label="Country"
                        value={companyData.country}
                        disabled={true}
                        labelClassName={darkLabelClass}
                        className={unavailableClassName}
                        infoContent={UNAVAILABLE_FIELD_NOTE}
                        onChange={(e) => handleChange('country', e.target.value)}
                    />
                </div>
            </div>

            {/* --- Section 4: Bank Details --- */}
            <div className={`${darkCardClass} p-6 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm transition-colors`}>
                <h3 className="text-[16px] md:text-[18px] font-semibold text-gray-800 dark:text-gray-200 mb-6 border-b border-gray-100 dark:border-gray-700 pb-3 flex items-center gap-2">
                     <span className="bg-blue-100 dark:bg-blue-900/30 p-1.5 rounded text-blue-600 dark:text-blue-400"><Landmark size={16} /></span>
                     Bank Details
                </h3>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-6">
                    <Input
                        label="Bank Name"
                        value={companyData.bankName}
                        disabled={!isEditing}
                        className={lockedClassName}
                        labelClassName={darkLabelClass}
                        onChange={(e) => handleChange('bankName', e.target.value)}
                        onBlur={() => validateField('bankName', companyData.bankName)}
                        error={errors.bankName}
                    />
                    <Input
                        label="Account Number"
                        value={companyData.accountNumber}
                        disabled={!isEditing}
                        className={lockedClassName}
                        labelClassName={darkLabelClass}
                        onChange={(e) => handleChange('accountNumber', e.target.value.replace(/\D/g, ''))}
                        onBlur={() => validateField('accountNumber', companyData.accountNumber)}
                        error={errors.accountNumber}
                    />
                    <Input
                        label="Account Holder Name"
                        value={companyData.accountHolderName}
                        disabled={!isEditing}
                        className={lockedClassName}
                        labelClassName={darkLabelClass}
                        onChange={(e) => handleChange('accountHolderName', e.target.value)}
                        onBlur={() => validateField('accountHolderName', companyData.accountHolderName)}
                        error={errors.accountHolderName}
                    />
                    <Input
                        label="IFSC Code"
                        value={companyData.ifscCode}
                        disabled={!isEditing}
                        className={lockedClassName}
                        labelClassName={darkLabelClass}
                        onChange={(e) => handleChange('ifscCode', e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))}
                        onBlur={() => validateField('ifscCode', companyData.ifscCode)}
                        error={errors.ifscCode}
                        maxLength={11}
                    />
                    <Input
                        label="Branch Name"
                        value={companyData.branchName}
                        disabled={!isEditing}
                        className={lockedClassName}
                        labelClassName={darkLabelClass}
                        onChange={(e) => handleChange('branchName', e.target.value)}
                        onBlur={() => validateField('branchName', companyData.branchName)}
                        error={errors.branchName}
                    />
                    <Select
                        label="Account Type"
                        options={['Current', 'Savings', 'OD']}
                        value={companyData.accountType}
                        disabled={!isEditing}
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
                        onChange={(val) => handleChange('accountType', val)}
                        error={errors.accountType}
                    />
                    <Input
                        label="UPI ID (Optional)"
                        value={companyData.upiId}
                        disabled={!isEditing}
                        className={lockedClassName}
                        labelClassName={darkLabelClass}
                        onChange={(e) => handleChange('upiId', e.target.value)}
                        onBlur={() => validateField('upiId', companyData.upiId)}
                        error={errors.upiId}
                    />
                </div>
            </div>
        </div>

        {/* --- Confirmation Modal --- */}
        {cropFile && (
          <LogoCropModal file={cropFile} onCancel={() => setCropFile(null)} onConfirm={handleLogoConfirm} />
        )}

        {showConfirmModal && (
            <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in">
                <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl w-full max-w-md p-6 border border-gray-200 dark:border-gray-700 transform transition-all scale-100">
                    <div className="flex items-center gap-3 mb-4 text-amber-500">
                        <AlertTriangle size={28} />
                        <h3 className="text-xl font-bold text-gray-900 dark:text-white">Unsaved Changes</h3>
                    </div>
                    
                    <p className="text-gray-600 dark:text-gray-300 mb-8 leading-relaxed">
                        You have unsaved changes in your company profile. Do you want to save these changes before leaving?
                    </p>
                    
                    <div className="flex items-center justify-end gap-3">
                         <button 
                            onClick={() => setShowConfirmModal(false)}
                            className="px-4 py-2 rounded-md text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 font-medium transition-colors"
                        >
                            Cancel
                        </button>
                        <button 
                            onClick={handleConfirmDiscard}
                            className="px-4 py-2 rounded-md bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/30 font-medium transition-colors"
                        >
                            Discard
                        </button>
                        <button 
                            onClick={handleConfirmSave}
                            className="px-6 py-2 rounded-md bg-[#0066ff] hover:bg-blue-700 text-white font-medium shadow-sm transition-colors"
                        >
                            Save Changes
                        </button>
                    </div>
                    
                    <button 
                        onClick={() => setShowConfirmModal(false)}
                        className="absolute top-4 right-4 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                    >
                        <X size={20} />
                    </button>
                </div>
            </div>
        )}
    </div>
  );
};

export default ViewCompany;
