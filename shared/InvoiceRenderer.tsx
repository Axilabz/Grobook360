// Shared Sales Invoice rendering engine.
//
// Used identically by both the Configuration screen's live preview
// (sample data) and the real Sales Invoice print view (SalesInvoice
// Management.tsx) — same component, different `invoice` prop — so the
// preview structurally cannot drift from the actual printed document
// (the source prompt's own §6/§27 requirement).
//
// IMPORTANT (documented gap, not silently resolved): this always renders
// using the tenant's CURRENT InvoiceTemplateConfig, not a snapshot taken
// at the time the invoice was issued — there is no template-versioning/
// document-snapshot table in this pass (see migration 0032's own module
// docstring). An already-issued invoice's printed appearance can change
// if the tenant later edits its configuration. This is a real gap
// against a "historical invoices must never change" requirement.
import React from 'react';
import { InvoiceTemplateConfig } from '../api/configuration';

export interface InvoiceLineData {
  id: string;
  description: string;
  hsn_code: string | null;
  quantity: string;
  uom: string;
  unit_price: string;
  discount_amount: string;
  taxable_amount: string;
  gst_rate: string;
  cgst_amount: string;
  sgst_amount: string;
  igst_amount: string;
  line_total: string;
}

export interface InvoiceRenderData {
  invoice_number: string;
  invoice_date: string;
  status: string;
  customer_name: string;
  customer_gstin: string | null;
  billing_address: string | null;
  lines: InvoiceLineData[];
  subtotal: string;
  discount_total: string;
  taxable_total: string;
  cgst_total: string;
  sgst_total: string;
  igst_total: string;
  grand_total: string;
}

export interface BusinessProfileData {
  business_name: string;
  gstin: string | null;
  address_line1: string | null;
  city: string | null;
  state_code: string | null;
  pin_code: string | null;
}

interface InvoiceRendererProps {
  config: InvoiceTemplateConfig;
  invoice: InvoiceRenderData;
  business: BusinessProfileData;
}

const numberToWordsInr = (value: string): string => {
  const n = Math.floor(Number(value) || 0);
  if (n === 0) return 'Zero Rupees Only';
  const ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten',
    'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen'];
  const tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety'];
  const twoDigits = (num: number): string => {
    if (num < 20) return ones[num];
    return tens[Math.floor(num / 10)] + (num % 10 ? ' ' + ones[num % 10] : '');
  };
  const threeDigits = (num: number): string => {
    if (num >= 100) return ones[Math.floor(num / 100)] + ' Hundred' + (num % 100 ? ' ' + twoDigits(num % 100) : '');
    return twoDigits(num);
  };
  let remaining = n;
  const crore = Math.floor(remaining / 10000000); remaining %= 10000000;
  const lakh = Math.floor(remaining / 100000); remaining %= 100000;
  const thousand = Math.floor(remaining / 1000); remaining %= 1000;
  const hundred = remaining;
  const parts: string[] = [];
  if (crore) parts.push(threeDigits(crore) + ' Crore');
  if (lakh) parts.push(threeDigits(lakh) + ' Lakh');
  if (thousand) parts.push(threeDigits(thousand) + ' Thousand');
  if (hundred) parts.push(threeDigits(hundred));
  return parts.join(' ') + ' Rupees Only';
};

const TEMPLATE_LAYOUT: Record<string, { headerStyle: string; fontSize: string; spacing: string }> = {
  CLASSIC: { headerStyle: 'text-center border-b-2 pb-4', fontSize: 'text-[13px]', spacing: 'p-8' },
  MODERN: { headerStyle: 'flex items-center justify-between rounded-t-lg px-6 py-4', fontSize: 'text-[13px]', spacing: 'p-8' },
  COMPACT: { headerStyle: 'flex items-center justify-between border-b pb-2', fontSize: 'text-[11px]', spacing: 'p-5' },
};

const InvoiceRenderer: React.FC<InvoiceRendererProps> = ({ config, invoice, business }) => {
  const layout = TEMPLATE_LAYOUT[config.template_id] || TEMPLATE_LAYOUT.CLASSIC;
  const isModern = config.template_id === 'MODERN';

  return (
    <div className={`bg-white ${layout.spacing} ${layout.fontSize}`} style={{ color: config.text_color, fontFamily: 'inherit' }}>
      <div
        className={layout.headerStyle}
        style={isModern ? { backgroundColor: config.primary_color, color: '#fff' } : { borderColor: config.primary_color }}
      >
        <div className="flex items-center gap-3">
          {config.show_logo && config.logo_data_uri && (
            <img src={config.logo_data_uri} alt="Business logo" className="h-12 w-12 object-contain rounded bg-white/10" />
          )}
          <div>
            <p className="text-[18px] font-bold" style={!isModern ? { color: config.primary_color } : undefined}>{business.business_name}</p>
            {config.show_business_address && (
              <p className="opacity-80">
                {[business.address_line1, business.city, business.state_code, business.pin_code].filter(Boolean).join(', ')}
              </p>
            )}
            {config.show_gstin && business.gstin && <p className="opacity-80">GSTIN: {business.gstin}</p>}
          </div>
        </div>
        {isModern && <p className="text-[20px] font-bold tracking-wide">TAX INVOICE</p>}
      </div>

      {!isModern && <p className="text-center text-[16px] font-semibold mt-3 mb-1" style={{ color: config.primary_color }}>TAX INVOICE</p>}

      <div className="grid grid-cols-2 gap-6 my-5">
        <div>
          <p className="text-[10px] uppercase opacity-60 mb-1">Bill To</p>
          <p className="font-medium">{invoice.customer_name}</p>
          {config.show_customer_gstin && invoice.customer_gstin && <p>GSTIN: {invoice.customer_gstin}</p>}
          {invoice.billing_address && <p className="opacity-80">{invoice.billing_address}</p>}
        </div>
        <div className="text-right">
          <p><span className="opacity-60">Invoice No:</span> <span className="font-medium">{invoice.invoice_number}</span></p>
          <p><span className="opacity-60">Invoice Date:</span> {invoice.invoice_date}</p>
          <p><span className="opacity-60">Status:</span> {invoice.status}</p>
        </div>
      </div>

      <table className="w-full text-left border-collapse mb-5">
        <thead>
          <tr style={{ backgroundColor: config.table_header_color }}>
            <th className="py-2 px-2">Item</th>
            {config.show_hsn && <th className="py-2 px-2">HSN</th>}
            <th className="py-2 px-2">Qty</th>
            <th className="py-2 px-2">Rate</th>
            {config.show_discount && <th className="py-2 px-2">Discount</th>}
            <th className="py-2 px-2">Taxable</th>
            {config.show_tax_breakup && <th className="py-2 px-2">GST</th>}
            <th className="py-2 px-2 text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {invoice.lines.map((line) => (
            <tr key={line.id} className="border-b" style={{ borderColor: config.secondary_color + '22' }}>
              <td className="py-1.5 px-2">{line.description}</td>
              {config.show_hsn && <td className="py-1.5 px-2">{line.hsn_code || '—'}</td>}
              <td className="py-1.5 px-2">{line.quantity} {line.uom}</td>
              <td className="py-1.5 px-2">₹{line.unit_price}</td>
              {config.show_discount && <td className="py-1.5 px-2">₹{line.discount_amount}</td>}
              <td className="py-1.5 px-2">₹{line.taxable_amount}</td>
              {config.show_tax_breakup && <td className="py-1.5 px-2">{line.gst_rate}%</td>}
              <td className="py-1.5 px-2 text-right">₹{line.line_total}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="flex justify-end mb-5">
        <div className="w-64 space-y-1">
          <div className="flex justify-between"><span className="opacity-60">Subtotal</span><span>₹{invoice.subtotal}</span></div>
          {config.show_discount && <div className="flex justify-between"><span className="opacity-60">Discount</span><span>−₹{invoice.discount_total}</span></div>}
          <div className="flex justify-between"><span className="opacity-60">Taxable Value</span><span>₹{invoice.taxable_total}</span></div>
          {config.show_tax_breakup && (
            <>
              <div className="flex justify-between"><span className="opacity-60">CGST</span><span>₹{invoice.cgst_total}</span></div>
              <div className="flex justify-between"><span className="opacity-60">SGST</span><span>₹{invoice.sgst_total}</span></div>
              <div className="flex justify-between"><span className="opacity-60">IGST</span><span>₹{invoice.igst_total}</span></div>
            </>
          )}
          <div className="flex justify-between font-semibold border-t pt-1" style={{ borderColor: config.primary_color, color: config.primary_color }}>
            <span>Grand Total</span><span>₹{invoice.grand_total}</span>
          </div>
        </div>
      </div>

      {config.show_amount_in_words && (
        <p className="mb-4"><span className="opacity-60">Amount in Words: </span>{numberToWordsInr(invoice.grand_total)}</p>
      )}

      {config.show_bank_details && (config.bank_name || config.bank_account_number) && (
        <div className="mb-4">
          <p className="text-[10px] uppercase opacity-60 mb-1" style={{ color: config.accent_color }}>Bank Details</p>
          {config.bank_name && <p>Bank: {config.bank_name}</p>}
          {config.bank_account_name && <p>Account Name: {config.bank_account_name}</p>}
          {config.bank_account_number && <p>Account No: {config.bank_account_number}</p>}
          {config.bank_ifsc && <p>IFSC: {config.bank_ifsc}</p>}
          {config.bank_upi_id && <p>UPI: {config.bank_upi_id}</p>}
        </div>
      )}

      {config.show_terms && config.terms_text && (
        <div className="mb-4">
          <p className="text-[10px] uppercase opacity-60 mb-1" style={{ color: config.accent_color }}>Terms &amp; Conditions</p>
          <p className="opacity-80 whitespace-pre-wrap">{config.terms_text}</p>
        </div>
      )}

      <p className="text-center opacity-50 mt-8" style={{ fontSize: '10px' }}>This is a computer-generated invoice.</p>
    </div>
  );
};

export default InvoiceRenderer;
