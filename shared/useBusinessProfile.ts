// Loads the tenant's Company Profile (name, address, phone, email, GSTIN)
// for InvoiceRenderer's header. GET /tenant needs configuration.view, so a
// user without it just gets the business name from their session (the
// extra header lines are omitted, never an error).
import { useEffect, useState } from 'react';
import { getTenantProfile } from '../api/tenant';
import { BusinessProfileData } from './InvoiceRenderer';

export function useBusinessProfile(fallbackName: string | undefined): BusinessProfileData {
  const [profile, setProfile] = useState<BusinessProfileData | null>(null);

  useEffect(() => {
    let cancelled = false;
    getTenantProfile()
      .then((p) => {
        if (cancelled) return;
        setProfile({
          business_name: p.business_name, gstin: p.gstin, address_line1: p.address_line1,
          city: p.city, state_code: p.state_code, pin_code: p.pin_code, phone: p.phone, email: p.email,
        });
      })
      .catch(() => { /* no configuration.view — fall back to name only */ });
    return () => { cancelled = true; };
  }, []);

  return profile ?? {
    business_name: fallbackName || 'Your Business', gstin: null, address_line1: null,
    city: null, state_code: null, pin_code: null, phone: null, email: null,
  };
}
