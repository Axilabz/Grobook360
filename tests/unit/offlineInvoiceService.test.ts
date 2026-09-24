import { describe, expect, it } from 'vitest';
import { calculateProvisionalLine, calculateProvisionalTotals, generateLocalReference } from '../../pwa/offlineInvoiceService';

describe('generateLocalReference (PROMPT-028 §28)', () => {
  it('produces a temporary reference clearly distinct from a real server document number', () => {
    const ref = generateLocalReference('INV');
    expect(ref).toMatch(/^OFF-INV-[0-9A-F]{8}$/);
  });

  it('generates a different reference on each call', () => {
    expect(generateLocalReference('INV')).not.toBe(generateLocalReference('INV'));
  });
});

describe('calculateProvisionalLine (PROMPT-028 §14 — discount BEFORE GST, provisional only)', () => {
  it('applies discount before computing GST (mirrors the server gst_calculation_service rule)', () => {
    // Quantity 10, Unit Price 1000 -> Gross 10,000; Discount 500; Taxable 9,500; GST 18% -> 1,710
    const result = calculateProvisionalLine({ product_id: 'p1', product_name: 'Widget', quantity: 10, uom_id: 'u1', unit_price: 1000, gst_rate: 18, discount_percent: 5 });
    expect(result.gross_amount).toBe(10000);
    expect(result.discount_amount).toBe(500);
    expect(result.taxable_amount).toBe(9500);
    expect(result.gst_amount).toBe(1710);
    expect(result.line_total).toBe(11210);
  });

  it('defaults discount to zero when not provided', () => {
    const result = calculateProvisionalLine({ product_id: 'p1', product_name: 'Widget', quantity: 1, uom_id: 'u1', unit_price: 100, gst_rate: 18 });
    expect(result.discount_amount).toBe(0);
    expect(result.taxable_amount).toBe(100);
  });

  it('never produces a negative taxable value even if discount exceeds gross', () => {
    const result = calculateProvisionalLine({ product_id: 'p1', product_name: 'Widget', quantity: 1, uom_id: 'u1', unit_price: 100, gst_rate: 18, discount_percent: 150 });
    expect(result.taxable_amount).toBe(0);
  });
});

describe('calculateProvisionalTotals', () => {
  it('sums line-level taxable/GST/total across multiple lines', () => {
    const lines = [
      calculateProvisionalLine({ product_id: 'p1', product_name: 'A', quantity: 1, uom_id: 'u1', unit_price: 100, gst_rate: 18 }),
      calculateProvisionalLine({ product_id: 'p2', product_name: 'B', quantity: 2, uom_id: 'u1', unit_price: 50, gst_rate: 12 }),
    ];
    const totals = calculateProvisionalTotals(lines);
    expect(totals.taxable_total).toBe(200);
    expect(totals.gst_total).toBe(18 + 12);
    expect(totals.grand_total).toBe(200 + 18 + 12);
  });
});
