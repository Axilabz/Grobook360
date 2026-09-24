
import React, { useState, useEffect } from 'react';
import { Building2, Mail, Phone, MapPin, Globe, PenLine, Save, Landmark, AlertTriangle, X } from 'lucide-react';
import Input from './Input';
import Select from './Select';
import { useToast } from '../context/ToastContext';
import { useNavigation } from '../context/NavigationContext';

const ViewCompany: React.FC = () => {
  const [isEditing, setIsEditing] = useState(false);
  const { showToast } = useToast();
  const { setBlocker, navigate } = useNavigation();
  
  // Modal State
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [pendingView, setPendingView] = useState<string | null>(null);
  
  // Dummy data simulating fetched user company details
  const [companyData, setCompanyData] = useState({
    orgName: 'Agin Crop',
    gstin: '33ABCDE1234F1Z5',
    pan: 'ABCDE1234F',
    businessType: 'Super Stockist',
    phone: '9876543210',
    email: 'admin@agincrop.com',
    website: 'www.agincrop.com',
    address: '123, South Car Street',
    city: 'Tiruchirappalli',
    state: 'Tamil Nadu',
    pincode: '620006',
    country: 'India',
    // Bank Details
    bankName: 'HDFC Bank',
    accountNumber: '50200012345678',
    accountHolderName: 'Agin Crop',
    ifscCode: 'HDFC0001234',
    branchName: 'Cantonment',
    accountType: 'Current',
    upiId: 'agincrop@hdfc'
  });

  const [errors, setErrors] = useState<Record<string, string>>({});

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
      case 'businessType':
        if (!value) error = "Business Type is required";
        break;

      // Contact Info
      case 'phone':
        if (!value) error = "Phone Number is required";
        else if (!/^\d{10}$/.test(value)) error = "Invalid Phone Number (10 digits)";
        break;
      case 'email':
        if (!value) error = "Email is required";
        else if (!/^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(value)) error = "Invalid Email Format";
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

      // Bank Details
      case 'bankName':
        if (!value) error = "Bank Name is required";
        break;
      case 'accountNumber':
        if (!value) error = "Account Number is required";
        else if (!/^\d{9,18}$/.test(value)) error = "Invalid Account Number";
        break;
      case 'accountHolderName':
        if (!value) error = "Account Holder Name is required";
        break;
      case 'ifscCode':
        if (!value) error = "IFSC Code is required";
        else if (!/^[A-Z]{4}0[A-Z0-9]{6}$/.test(value)) error = "Invalid IFSC Code (e.g. HDFC0001234)";
        break;
      case 'branchName':
        if (!value) error = "Branch Name is required";
        break;
      case 'accountType':
        if (!value) error = "Account Type is required";
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

  const handleSave = (): boolean => {
      // Validate all fields
      const fieldsToValidate = [
          'orgName', 'gstin', 'pan', 'businessType',
          'phone', 'email', 'website',
          'address', 'city', 'state', 'pincode',
          'bankName', 'accountNumber', 'accountHolderName', 'ifscCode', 'branchName', 'accountType', 'upiId'
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

      setIsEditing(false);
      showToast("Company Profile Updated Successfully", "success");
      return true;
  };

  const handleEditToggle = () => {
    if (isEditing) {
        handleSave();
    } else {
        setIsEditing(true);
    }
  };

  // Modal Handlers
  const handleConfirmDiscard = () => {
    setBlocker(null); // Unblock navigation
    setIsEditing(false); // Reset editing state
    setShowConfirmModal(false);
    if (pendingView) navigate(pendingView); // Proceed to pending view
  };

  const handleConfirmSave = () => {
    if (handleSave()) {
        setBlocker(null);
        setShowConfirmModal(false);
        if (pendingView) navigate(pendingView);
    }
  };

  const darkCardClass = "bg-white dark:bg-gray-900";
  const darkLabelClass = "bg-white dark:bg-gray-900";
  const lockedClassName = !isEditing ? "!bg-white dark:!bg-gray-900 !text-gray-900 dark:!text-white !cursor-default !border-gray-200 dark:!border-gray-700" : "";

  return (
    <div className="max-w-7xl mx-auto p-4 md:p-8 animate-fade-in relative">
        {/* Sticky Header */}
        <div className="sticky top-16 z-30 bg-white dark:bg-gray-950 -mx-4 md:-mx-8 px-4 md:px-8 py-4 -mt-4 md:-mt-8 mb-6 border-b border-gray-100 dark:border-gray-800 transition-all flex items-center justify-between shadow-sm">
            <h2 className="text-[22px] md:text-[26px] lg:text-[28px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight leading-tight">Company Profile</h2>
            
            <button 
                onClick={handleEditToggle}
                className="flex items-center gap-2 px-6 py-2 rounded-lg shadow-sm transition-colors font-medium bg-[#0066ff] hover:bg-blue-700 text-white" 
            >
               {isEditing ? <><Save size={18} /> Save Details</> : <><PenLine size={18} /> Edit Profile</>}
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
                        <div className="w-32 h-32 rounded-full bg-gray-100 dark:bg-gray-800 border-2 border-dashed border-gray-300 dark:border-gray-600 flex items-center justify-center text-gray-400 dark:text-gray-500 overflow-hidden relative group cursor-pointer">
                            <span className="text-4xl font-bold text-gray-300 dark:text-gray-600">AC</span>
                            <div className="absolute inset-0 bg-black/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                                <span className="text-white text-xs font-medium">Change Logo</span>
                            </div>
                        </div>
                        <p className="text-xs text-gray-500 dark:text-gray-400">Click to upload logo</p>
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
                            className={!isEditing ? lockedClassName : "bg-gray-100 dark:bg-gray-800 cursor-not-allowed"}
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
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
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
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
                        icon={<Mail size={18} />}
                        onChange={(e) => handleChange('email', e.target.value)}
                        onBlur={() => validateField('email', companyData.email)}
                        error={errors.email}
                    />
                    <Input
                        label="Website"
                        value={companyData.website}
                        disabled={!isEditing}
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
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
                        className={!isEditing ? lockedClassName : "bg-gray-100 dark:bg-gray-800 cursor-not-allowed"}
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
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
                        onChange={(e) => handleChange('bankName', e.target.value)}
                        onBlur={() => validateField('bankName', companyData.bankName)}
                        error={errors.bankName}
                    />
                    <Input
                        label="Account Number"
                        value={companyData.accountNumber}
                        disabled={!isEditing}
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
                        onChange={(e) => handleChange('accountNumber', e.target.value.replace(/\D/g, ''))}
                        onBlur={() => validateField('accountNumber', companyData.accountNumber)}
                        error={errors.accountNumber}
                    />
                    <Input
                        label="Account Holder Name"
                        value={companyData.accountHolderName}
                        disabled={!isEditing}
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
                        onChange={(e) => handleChange('accountHolderName', e.target.value)}
                        onBlur={() => validateField('accountHolderName', companyData.accountHolderName)}
                        error={errors.accountHolderName}
                    />
                    <Input
                        label="IFSC Code"
                        value={companyData.ifscCode}
                        disabled={!isEditing}
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
                        onChange={(e) => handleChange('ifscCode', e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))}
                        onBlur={() => validateField('ifscCode', companyData.ifscCode)}
                        error={errors.ifscCode}
                        maxLength={11}
                    />
                    <Input
                        label="Branch Name"
                        value={companyData.branchName}
                        disabled={!isEditing}
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
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
                        labelClassName={darkLabelClass}
                        className={lockedClassName}
                        onChange={(e) => handleChange('upiId', e.target.value)}
                        onBlur={() => validateField('upiId', companyData.upiId)}
                        error={errors.upiId}
                    />
                </div>
            </div>
        </div>

        {/* --- Confirmation Modal --- */}
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
