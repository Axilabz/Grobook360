// Configuration Center — Invoice Template Configuration (primary scope
// of this module per the source prompt's own §4 "Invoice Template
// Management is the primary requirement"). Business Profile editing is
// deliberately NOT duplicated here — it already has a home (Profile →
// View Company) and §11 explicitly warns against a second copy of the
// same master data.
import React, { useState, useEffect, useCallback } from 'react';
import {
  Palette, Image as ImageIcon, Eye, EyeOff, Save, RotateCcw, Upload, X, Check, Building2,
} from 'lucide-react';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import { ApiError } from '../api/client';
import {
  getInvoiceTemplateConfig, updateInvoiceTemplateConfig, uploadBusinessLogo, removeBusinessLogo,
  InvoiceTemplateConfig, InvoiceTemplateId,
} from '../api/configuration';
import InvoiceRenderer, { InvoiceRenderData, BusinessProfileData } from '../shared/InvoiceRenderer';
import LoadingState from '../shared/LoadingState';

const TEMPLATES: { id: InvoiceTemplateId; name: string; description: string }[] = [
  { id: 'CLASSIC', name: 'Classic', description: 'Centered header, traditional layout.' },
  { id: 'MODERN', name: 'Modern', description: 'Colored banner header, bold accents.' },
  { id: 'COMPACT', name: 'Compact', description: 'Tighter spacing, smaller type — fits more on one page.' },
];

const COLOR_PRESETS: { name: string; primary: string; secondary: string; accent: string }[] = [
  { name: 'Blue', primary: '#2563EB', secondary: '#0F172A', accent: '#10B981' },
  { name: 'Green', primary: '#059669', secondary: '#064E3B', accent: '#F59E0B' },
  { name: 'Orange', primary: '#EA580C', secondary: '#7C2D12', accent: '#2563EB' },
  { name: 'Purple', primary: '#7C3AED', secondary: '#2E1065', accent: '#F59E0B' },
  { name: 'Teal', primary: '#0D9488', secondary: '#134E4A', accent: '#F97316' },
  { name: 'Slate', primary: '#475569', secondary: '#1E293B', accent: '#0EA5E9' },
];

type BooleanConfigKey =
  | 'show_logo' | 'show_business_address' | 'show_gstin' | 'show_customer_gstin' | 'show_hsn' | 'show_discount'
  | 'show_tax_breakup' | 'show_bank_details' | 'show_terms' | 'show_amount_in_words' | 'show_round_off';

const DISPLAY_TOGGLES: { key: BooleanConfigKey; label: string }[] = [
  { key: 'show_logo', label: 'Show Logo' },
  { key: 'show_business_address', label: 'Show Business Address' },
  { key: 'show_gstin', label: 'Show GSTIN' },
  { key: 'show_customer_gstin', label: 'Show Customer GSTIN' },
  { key: 'show_hsn', label: 'Show HSN/SAC' },
  { key: 'show_discount', label: 'Show Discount' },
  { key: 'show_tax_breakup', label: 'Show Tax Breakup' },
  { key: 'show_bank_details', label: 'Show Bank Details' },
  { key: 'show_terms', label: 'Show Terms & Conditions' },
  { key: 'show_amount_in_words', label: 'Show Amount in Words' },
  { key: 'show_round_off', label: 'Show Round Off' },
];

const SAMPLE_INVOICE: InvoiceRenderData = {
  invoice_number: 'INV-2026-27-0001', invoice_date: '2026-09-25', status: 'POSTED',
  customer_name: 'Sri Lakshmi Stores', customer_gstin: '33AAACS1234F1Z5', billing_address: 'No. 12, Market Street, Chennai, TN 600001',
  lines: [
    { id: '1', description: 'Ponni Rice 25Kg Bag', hsn_code: '1006', quantity: '5', uom: 'KG', unit_price: '1200.00', discount_amount: '0.00', taxable_amount: '6000.00', gst_rate: '5', cgst_amount: '150.00', sgst_amount: '150.00', igst_amount: '0.00', line_total: '6300.00' },
    { id: '2', description: 'Sunflower Cooking Oil 1L', hsn_code: '1512', quantity: '20', uom: 'LTR', unit_price: '135.00', discount_amount: '54.00', taxable_amount: '2646.00', gst_rate: '5', cgst_amount: '66.15', sgst_amount: '66.15', igst_amount: '0.00', line_total: '2778.30' },
  ],
  subtotal: '8700.00', discount_total: '54.00', taxable_total: '8646.00', cgst_total: '216.15', sgst_total: '216.15', igst_total: '0.00', grand_total: '9078.30',
};

type ConfigFormState = Omit<InvoiceTemplateConfig, 'id' | 'logo_data_uri' | 'row_version'>;

function toFormState(c: InvoiceTemplateConfig): ConfigFormState {
  const { id, logo_data_uri, row_version, ...rest } = c;
  return rest;
}

const HEX_PATTERN = /^#[0-9A-Fa-f]{6}$/;

const ConfigurationManagement: React.FC = () => {
  const { showToast } = useToast();
  const { hasPermission, currentTenant } = useAuth();
  const canManage = hasPermission('configuration.manage');

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<InvoiceTemplateConfig | null>(null);
  const [form, setForm] = useState<ConfigFormState | null>(null);
  const [logoDataUri, setLogoDataUri] = useState<string | null>(null);
  const [rowVersion, setRowVersion] = useState(1);
  const [uploadingLogo, setUploadingLogo] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getInvoiceTemplateConfig();
      setSaved(data);
      setForm(toFormState(data));
      setLogoDataUri(data.logo_data_uri);
      setRowVersion(data.row_version);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Unable to load configuration.', 'error');
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => { load(); }, [load]);

  const isDirty = saved && form && (
    JSON.stringify(toFormState(saved)) !== JSON.stringify(form) || saved.logo_data_uri !== logoDataUri
  );

  const update = <K extends keyof ConfigFormState>(key: K, value: ConfigFormState[K]) => {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  const handleSave = async () => {
    if (!form || !canManage) return;
    for (const field of ['primary_color', 'secondary_color', 'accent_color', 'text_color', 'table_header_color'] as const) {
      if (!HEX_PATTERN.test(form[field])) {
        showToast(`${field.replace('_', ' ')} must be a valid hex color (e.g. #2563EB).`, 'error');
        return;
      }
    }
    setSaving(true);
    try {
      const updated = await updateInvoiceTemplateConfig({ ...form, expected_row_version: rowVersion });
      setSaved(updated);
      setForm(toFormState(updated));
      setRowVersion(updated.row_version);
      showToast('Invoice configuration updated successfully.', 'success');
    } catch (err) {
      if (err instanceof ApiError && err.status === 412) {
        showToast('This configuration was changed by someone else. Reloading the latest version.', 'error');
        await load();
      } else {
        showToast(err instanceof ApiError ? err.message : 'Unable to save configuration.', 'error');
      }
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    if (!saved) return;
    setForm(toFormState(saved));
    setLogoDataUri(saved.logo_data_uri);
  };

  const handleLogoUpload = async (file: File) => {
    if (!canManage) return;
    setUploadingLogo(true);
    try {
      const updated = await uploadBusinessLogo(file);
      setLogoDataUri(updated.logo_data_uri);
      setRowVersion(updated.row_version);
      setSaved((prev) => (prev ? { ...prev, logo_data_uri: updated.logo_data_uri, row_version: updated.row_version } : prev));
      showToast('Logo uploaded.', 'success');
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Unable to upload logo.', 'error');
    } finally {
      setUploadingLogo(false);
    }
  };

  const handleLogoRemove = async () => {
    if (!canManage) return;
    try {
      const updated = await removeBusinessLogo();
      setLogoDataUri(null);
      setRowVersion(updated.row_version);
      setSaved((prev) => (prev ? { ...prev, logo_data_uri: null, row_version: updated.row_version } : prev));
      showToast('Logo removed.', 'success');
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Unable to remove logo.', 'error');
    }
  };

  const previewConfig: InvoiceTemplateConfig | null = form && saved ? { ...form, id: saved.id, logo_data_uri: logoDataUri, row_version: rowVersion } : null;
  const business: BusinessProfileData = {
    business_name: currentTenant?.business_name || 'Your Business', gstin: null,
    address_line1: null, city: null, state_code: null, pin_code: null,
  };

  return (
    <div className="max-w-[98%] mx-auto p-4 md:p-6 animate-fade-in">
      <div className="sticky top-16 z-[55] bg-white dark:bg-gray-950 -mx-4 md:-mx-6 px-4 md:px-6 py-4 -mt-4 md:-mt-6 mb-6 border-b border-gray-100 dark:border-gray-800 shadow-sm">
        <h2 className="text-[22px] md:text-[26px] font-semibold text-gray-800 dark:text-gray-100 tracking-tight">Configuration</h2>
        <p className="text-[13px] text-gray-500 dark:text-gray-400 mt-0.5">Invoice template, colors, and display settings for new Sales Invoices.</p>
      </div>

      {loading || !form || !previewConfig ? (
        <LoadingState label="Loading configuration…" />
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {/* Left: configuration panel */}
          <div className="space-y-6">
            {!canManage && (
              <div className="p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-400 text-[13px]">
                You have view-only access. Contact an Owner to change these settings.
              </div>
            )}

            {/* Template gallery */}
            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <h3 className="text-[15px] font-semibold text-gray-800 dark:text-gray-200 mb-3 flex items-center gap-2"><Building2 size={16} /> Invoice Template</h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {TEMPLATES.map((t) => (
                  <button
                    key={t.id}
                    disabled={!canManage}
                    onClick={() => update('template_id', t.id)}
                    className={`text-left p-3 rounded-lg border-2 transition-colors ${form.template_id === t.id ? 'border-[#0066ff] bg-blue-50 dark:bg-blue-900/20' : 'border-gray-200 dark:border-gray-700 hover:border-gray-300'}`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-[14px] text-gray-900 dark:text-gray-100">{t.name}</span>
                      {form.template_id === t.id && <Check size={16} className="text-[#0066ff]" />}
                    </div>
                    <p className="text-[12px] text-gray-500 dark:text-gray-400">{t.description}</p>
                  </button>
                ))}
              </div>
            </div>

            {/* Color customization */}
            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <h3 className="text-[15px] font-semibold text-gray-800 dark:text-gray-200 mb-3 flex items-center gap-2"><Palette size={16} /> Invoice Appearance</h3>
              <p className="text-[12px] text-gray-500 dark:text-gray-400 mb-2">Color Presets</p>
              <div className="flex flex-wrap gap-2 mb-4">
                {COLOR_PRESETS.map((p) => (
                  <button
                    key={p.name}
                    disabled={!canManage}
                    onClick={() => setForm((prev) => prev ? { ...prev, primary_color: p.primary, secondary_color: p.secondary, accent_color: p.accent } : prev)}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-full border border-gray-200 dark:border-gray-700 text-[12px] text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
                  >
                    <span className="w-3 h-3 rounded-full" style={{ backgroundColor: p.primary }} /> {p.name}
                  </button>
                ))}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {([
                  ['primary_color', 'Primary Color'], ['secondary_color', 'Secondary Color'], ['accent_color', 'Accent Color'],
                  ['text_color', 'Text Color'], ['table_header_color', 'Table Header'],
                ] as const).map(([key, label]) => (
                  <div key={key}>
                    <label className="text-[12px] text-gray-500 dark:text-gray-400 block mb-1">{label}</label>
                    <div className="flex items-center gap-2">
                      <input type="color" disabled={!canManage} value={form[key]} onChange={(e) => update(key, e.target.value.toUpperCase() as any)} className="w-9 h-9 rounded border border-gray-200 dark:border-gray-700 cursor-pointer disabled:cursor-not-allowed" />
                      <input
                        type="text" disabled={!canManage} value={form[key]}
                        onChange={(e) => update(key, e.target.value.toUpperCase() as any)}
                        className={`flex-1 px-2.5 py-1.5 rounded-lg border text-[13px] font-mono bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 ${HEX_PATTERN.test(form[key]) ? 'border-gray-300 dark:border-gray-600' : 'border-red-400'}`}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Logo */}
            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <h3 className="text-[15px] font-semibold text-gray-800 dark:text-gray-200 mb-3 flex items-center gap-2"><ImageIcon size={16} /> Business Logo</h3>
              <div className="flex items-center gap-4">
                {logoDataUri ? (
                  <img src={logoDataUri} alt="Business logo" className="w-16 h-16 object-contain rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800" />
                ) : (
                  <div className="w-16 h-16 rounded border border-dashed border-gray-300 dark:border-gray-600 flex items-center justify-center text-gray-400"><ImageIcon size={20} /></div>
                )}
                {canManage && (
                  <div className="flex gap-2">
                    <label className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-[13px] text-gray-700 dark:text-gray-200 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800">
                      <Upload size={14} /> {uploadingLogo ? 'Uploading…' : logoDataUri ? 'Replace' : 'Upload Logo'}
                      <input
                        type="file" accept="image/png,image/jpeg,image/webp" className="hidden" disabled={uploadingLogo}
                        onChange={(e) => { const f = e.target.files?.[0]; if (f) handleLogoUpload(f); e.target.value = ''; }}
                      />
                    </label>
                    {logoDataUri && (
                      <button onClick={handleLogoRemove} className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-red-300 dark:border-red-800 text-[13px] text-red-600">
                        <X size={14} /> Remove
                      </button>
                    )}
                  </div>
                )}
              </div>
              <p className="text-[11px] text-gray-400 mt-2">PNG, JPEG, or WebP · up to 500KB</p>
            </div>

            {/* Display options */}
            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <h3 className="text-[15px] font-semibold text-gray-800 dark:text-gray-200 mb-3 flex items-center gap-2"><Eye size={16} /> Invoice Display Options</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
                {DISPLAY_TOGGLES.map((t) => (
                  <label key={String(t.key)} className="flex items-center justify-between gap-3 py-2">
                    <span className="text-[13px] text-gray-700 dark:text-gray-300">{t.label}</span>
                    <button
                      type="button" disabled={!canManage} aria-pressed={form[t.key]}
                      onClick={() => update(t.key, !form[t.key] as any)}
                      className={`shrink-0 inline-flex items-center w-11 h-6 rounded-full transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed ${form[t.key] ? 'bg-[#0066ff]' : 'bg-gray-300 dark:bg-gray-600'}`}
                    >
                      <span
                        className="inline-block w-5 h-5 bg-white rounded-full shadow transform transition-transform duration-200"
                        style={{ transform: form[t.key] ? 'translateX(22px)' : 'translateX(2px)' }}
                      />
                    </button>
                  </label>
                ))}
              </div>

              {form.show_terms && (
                <div className="mt-3">
                  <label className="text-[12px] text-gray-500 dark:text-gray-400 block mb-1">Terms &amp; Conditions</label>
                  <textarea
                    disabled={!canManage} rows={2} maxLength={2000} value={form.terms_text || ''}
                    onChange={(e) => update('terms_text', e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-[13px]"
                  />
                </div>
              )}

              {form.show_bank_details && (
                <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {([
                    ['bank_name', 'Bank Name'], ['bank_account_name', 'Account Name'], ['bank_account_number', 'Account Number'],
                    ['bank_ifsc', 'IFSC'], ['bank_upi_id', 'UPI ID'],
                  ] as const).map(([key, label]) => (
                    <input
                      key={key} disabled={!canManage} placeholder={label} value={form[key] || ''}
                      onChange={(e) => update(key, e.target.value as any)}
                      className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 text-[13px]"
                    />
                  ))}
                </div>
              )}
            </div>

            {canManage && (
              <div className="flex items-center gap-2 sticky bottom-0 bg-white dark:bg-gray-950 py-3 -mx-1 px-1">
                <button
                  onClick={handleSave} disabled={saving || !isDirty}
                  className="flex items-center gap-1.5 px-4 py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 disabled:opacity-50 text-white text-[14px] font-semibold"
                >
                  <Save size={15} /> {saving ? 'Saving…' : 'Save Changes'}
                </button>
                <button
                  onClick={handleReset} disabled={!isDirty}
                  className="flex items-center gap-1.5 px-4 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 disabled:opacity-50 text-gray-700 dark:text-gray-200 text-[14px] font-medium"
                >
                  <RotateCcw size={15} /> Reset
                </button>
                {isDirty && <span className="text-[12px] text-amber-600 dark:text-amber-400">You have unsaved changes.</span>}
              </div>
            )}
          </div>

          {/* Right: live preview */}
          <div className="bg-gray-100 dark:bg-gray-950 rounded-xl border border-gray-200 dark:border-gray-700 p-4 overflow-auto max-h-[85vh] sticky top-32 self-start">
            <p className="text-[12px] text-gray-500 dark:text-gray-400 mb-2 flex items-center gap-1.5"><Eye size={13} /> Live Preview (sample data)</p>
            <div className="shadow-lg rounded overflow-hidden">
              <InvoiceRenderer config={previewConfig} invoice={SAMPLE_INVOICE} business={business} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ConfigurationManagement;
