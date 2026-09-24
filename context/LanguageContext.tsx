import React, { createContext, useContext, useState, useCallback } from 'react';

export type Language = 'English' | 'Tamil';

interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: string) => string;
}

const translations: Record<string, Record<Language, string>> = {
  // Common
  'Saas App': { English: 'Saas App', Tamil: 'சாஸ் பயன்பாடு' },
  'Search': { English: 'Search', Tamil: 'தேடு' },
  'Or': { English: 'Or', Tamil: 'அல்லது' },
  'Back': { English: 'Back', Tamil: 'பின்செல்க' },
  'Next': { English: 'Next', Tamil: 'அடுத்து' },
  
  // Header
  'Customer': { English: 'Customer', Tamil: 'வாடிக்கையாளர்' },
  'Vendor': { English: 'Vendor', Tamil: 'விற்பனையாளர்' },
  'Product': { English: 'Product', Tamil: 'தயாரிப்பு' },
  'Sales Invoice': { English: 'Sales Invoice', Tamil: 'விற்பனை விலைப்பட்டியல்' },
  'Purchase Invoice': { English: 'Purchase Invoice', Tamil: 'கொள்முதல் விலைப்பட்டியல்' },
  'Search the': { English: 'Search the', Tamil: 'தேடு' },

  // Sidebar
  'Home': { English: 'Home', Tamil: 'முகப்பு' },
  'Items': { English: 'Items', Tamil: 'பொருட்கள்' },
  'Add Items': { English: 'Add Items', Tamil: 'பொருட்களைச் சேர்' },
  'List Items': { English: 'List Items', Tamil: 'பொருட்களின் பட்டியல்' },
  'Stock': { English: 'Stock', Tamil: 'கையிருப்பு' },
  'Sales': { English: 'Sales', Tamil: 'விற்பனை' },
  'Add Customer': { English: 'Add Customer', Tamil: 'வாடிக்கையாளரைச் சேர்' },
  'View Customer': { English: 'View Customer', Tamil: 'வாடிக்கையாளரைப் பார்' },
  'Order': { English: 'Order', Tamil: 'ஆர்டர்' },
  'View Sales Invoice': { English: 'View Sales Invoice', Tamil: 'விற்பனை விலைப்பட்டியலைப் பார்' },
  'Purchase': { English: 'Purchase', Tamil: 'கொள்முதல்' },
  'Accountant': { English: 'Accountant', Tamil: 'கணக்காளர்' },
  'GST Filing': { English: 'GST Filing', Tamil: 'ஜிஎஸ்டி தாக்கல்' },
  'Payroll': { English: 'Payroll', Tamil: 'சம்பளப் பட்டியல்' },
  'Reports': { English: 'Reports', Tamil: 'அறிக்கைகள்' },
  'Analysis': { English: 'Analysis', Tamil: 'பகுப்பாய்வு' },

  // Auth (SignIn / SignUp)
  'Sign In To Access Book': { English: 'Sign In To Access Book', Tamil: 'புத்தகத்தை அணுக உள்நுழையவும்' },
  'Phone Number': { English: 'Phone Number', Tamil: 'தொலைபேசி எண்' },
  'Password': { English: 'Password', Tamil: 'கடவுச்சொல்' },
  'Remember Me': { English: 'Remember Me', Tamil: 'என்னை நினைவில் கொள்' },
  'Forget Password ?': { English: 'Forget Password ?', Tamil: 'கடவுச்சொல் மறந்துவிட்டதா?' },
  'Log in': { English: 'Log in', Tamil: 'உள்நுழை' },
  'Login with Google': { English: 'Login with Google', Tamil: 'கூகிள் மூலம் உள்நுழைக' },
  "Don't have a Saas App Account ?": { English: "Don't have a Saas App Account ?", Tamil: 'சாஸ் பயன்பாட்டுக் கணக்கு இல்லையா?' },
  'SIGN UP': { English: 'SIGN UP', Tamil: 'பதிவு செய்' },
  'Create An Account To Access Book': { English: 'Create An Account To Access Book', Tamil: 'புத்தகத்தை அணுக கணக்கை உருவாக்கவும்' },
  'Organization Details': { English: 'Organization Details', Tamil: 'நிறுவன விவரங்கள்' },
  'Login Details': { English: 'Login Details', Tamil: 'உள்நுழைவு விவரங்கள்' },
  'GSTIN / UIN': { English: 'GSTIN / UIN', Tamil: 'ஜிஎஸ்டிஐஎன் / யுஐஎன்' },
  'PAN': { English: 'PAN', Tamil: 'பான் எண்' },
  'Organization / Trader Name': { English: 'Organization / Trader Name', Tamil: 'நிறுவனம் / வர்த்தகர் பெயர்' },
  'Business Type': { English: 'Business Type', Tamil: 'வணிக வகை' },
  'Address': { English: 'Address', Tamil: 'முகவரி' },
  'Country': { English: 'Country', Tamil: 'நாடு' },
  'State': { English: 'State', Tamil: 'மாநிலம்' },
  'District': { English: 'District', Tamil: 'மாவட்டம்' },
  'Pin Code': { English: 'Pin Code', Tamil: 'அஞ்சல் குறியீடு' },
  'Email ID': { English: 'Email ID', Tamil: 'மின்னஞ்சல் முகவரி' },
  'Confirm Password': { English: 'Confirm Password', Tamil: 'கடவுச்சொல்லை உறுதிப்படுத்தவும்' },
  'Password Rules': { English: 'Password Rules', Tamil: 'கடவுச்சொல் விதிகள்' },
  'Already Have a Saas App Account ?': { English: 'Already Have a Saas App Account ?', Tamil: 'ஏற்கனவே கணக்கு உள்ளதா?' },
  'Sign In / Log In': { English: 'Sign In / Log In', Tamil: 'உள்நுழை / புகுபதிகை' },
  'Sign Up': { English: 'Sign Up', Tamil: 'பதிவு செய்' },
  
  // Dashboard
  'Dashboard Overview': { English: 'Dashboard Overview', Tamil: 'முகப்பு கண்ணோட்டம்' },
  'Total Sales': { English: 'Total Sales', Tamil: 'மொத்த விற்பனை' },
  'Total Orders': { English: 'Total Orders', Tamil: 'மொத்த ஆர்டர்கள்' },
  'New Customers': { English: 'New Customers', Tamil: 'புதிய வாடிக்கையாளர்கள்' },
  'Pending Invoices': { English: 'Pending Invoices', Tamil: 'நிலுவையிலுள்ள விலைப்பட்டியல்கள்' },
  'Recent Transactions': { English: 'Recent Transactions', Tamil: 'சமீபத்திய பரிவர்த்தனைகள்' },
  'Stock Alerts': { English: 'Stock Alerts', Tamil: 'கையிருப்பு எச்சரிக்கைகள்' },

  // Add Customer
  'Customer / Company Details': { English: 'Customer / Company Details', Tamil: 'வாடிக்கையாளர் / நிறுவன விவரங்கள்' },
  'Customer Type': { English: 'Customer Type', Tamil: 'வாடிக்கையாளர் வகை' },
  'Region': { English: 'Region', Tamil: 'பகுதி' },
  'Customer / Company Name': { English: 'Customer / Company Name', Tamil: 'வாடிக்கையாளர் / நிறுவன பெயர்' },
  'Owner Details': { English: 'Owner Details', Tamil: 'உரிமையாளர் விவரங்கள்' },
  'Owner Name': { English: 'Owner Name', Tamil: 'உரிமையாளர் பெயர்' },
  'Owner Phone Number': { English: 'Owner Phone Number', Tamil: 'உரிமையாளர் தொலைபேசி எண்' },
  'Email ID (Optional)': { English: 'Email ID (Optional)', Tamil: 'மின்னஞ்சல் (விருப்பத் தேர்வு)' },
  'Secondary Contact': { English: 'Secondary Contact', Tamil: 'இரண்டாம் நிலை தொடர்பு' },
  'Secondary Contact Details': { English: 'Secondary Contact Details', Tamil: 'இரண்டாம் நிலை தொடர்பு விவரங்கள்' },
  'Remove': { English: 'Remove', Tamil: 'நீக்கு' },
  'Name': { English: 'Name', Tamil: 'பெயர்' },
  'Customer Address': { English: 'Customer Address', Tamil: 'வாடிக்கையாளர் முகவரி' },
  'Billing Address': { English: 'Billing Address', Tamil: 'பில்லிங் முகவரி' },
  'Same as Customer Address': { English: 'Same as Customer Address', Tamil: 'வாடிக்கையாளர் முகவரி போன்றதே' },
  'Save Customer': { English: 'Save Customer', Tamil: 'சேமி' },
  'Please fill all required fields correctly': { English: 'Please fill all required fields correctly', Tamil: 'தேவையான அனைத்து புலங்களையும் சரியாக நிரப்பவும்' },
  'Customer Added Successfully!': { English: 'Customer Added Successfully!', Tamil: 'வாடிக்கையாளர் வெற்றிகரமாக சேர்க்கப்பட்டார்!' },
  
  // Dropdown Options
  'Distributor': { English: 'Distributor', Tamil: 'விநியோகஸ்தர்' },
  'Super Stockist': { English: 'Super Stockist', Tamil: 'சூப்பர் ஸ்டாக்கிஸ்ட்' },
  'Wholesaler': { English: 'Wholesaler', Tamil: 'மொத்த விற்பனையாளர்' },
  'Manufacture Industry': { English: 'Manufacture Industry', Tamil: 'உற்பத்தித் துறை' },
  'Warehouse': { English: 'Warehouse', Tamil: 'கிடங்கு' },
  'Others (Add New)': { English: 'Others (Add New)', Tamil: 'மற்றவை (புதியதைச் சேர்)' },
  'Grocery Shop': { English: 'Grocery Shop', Tamil: 'மளிகை கடை' },
  'Super Market': { English: 'Super Market', Tamil: 'பல்பொருள் அங்காடி' },
  'Departmental Store': { English: 'Departmental Store', Tamil: 'பல்பொருள் கடை' },
  'Hotel': { English: 'Hotel', Tamil: 'உணவகம்' },
  'Canteen': { English: 'Canteen', Tamil: 'உணவு விடுதி' },
  'Individual': { English: 'Individual', Tamil: 'தனிநபர்' },
};

const LanguageContext = createContext<LanguageContextType | undefined>(undefined);

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [language, setLanguage] = useState<Language>('English');

  const t = useCallback((key: string) => {
    if (!translations[key]) return key;
    return translations[key][language] || key;
  }, [language]);

  return (
    <LanguageContext.Provider value={{ language, setLanguage, t }}>
      {children}
    </LanguageContext.Provider>
  );
};

export const useLanguage = () => {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useLanguage must be used within a LanguageProvider');
  }
  return context;
};
