// Shared number/currency formatting for the Analysis module — mirrors
// components/Home.tsx's own `formatInr` exactly so a ₹ figure reads
// identically whether it's on the Dashboard or in Analysis.

export function formatInr(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const n = typeof value === 'string' ? Number(value) : value;
  if (Number.isNaN(n)) return '₹0.00';
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function formatCompactInr(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const n = typeof value === 'string' ? Number(value) : value;
  if (Number.isNaN(n)) return '₹0';
  if (Math.abs(n) >= 10000000) return '₹' + (n / 10000000).toFixed(1) + 'Cr';
  if (Math.abs(n) >= 100000) return '₹' + (n / 100000).toFixed(1) + 'L';
  if (Math.abs(n) >= 1000) return '₹' + (n / 1000).toFixed(1) + 'K';
  return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

export function formatQuantity(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const n = typeof value === 'string' ? Number(value) : value;
  if (Number.isNaN(n)) return '0';
  return n.toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

export function formatPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return 'N/A';
  const n = typeof value === 'string' ? Number(value) : value;
  if (Number.isNaN(n)) return 'N/A';
  return (n >= 0 ? '+' : '') + n.toFixed(1) + '%';
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}
