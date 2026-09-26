// Party 360 Profile — ONE reusable component for both Customer and
// Supplier, branching only on `partyType` for terminology/labels (per
// the source prompt's own §32/§47 "one architecture, not two" mandate).
// Every number is read verbatim from GET /parties/{partyType}/{partyId}
// (backend-authoritative) — nothing is recalculated here.
import React, { useEffect, useState, useCallback } from 'react';
import {
  X, TrendingUp, Wallet, FileText, ShoppingCart, RefreshCw, Package, Receipt,
} from 'lucide-react';
import { useToast } from '../context/ToastContext';
import { ApiError } from '../api/client';
import { getPartyProfile, PartyProfile as PartyProfileData, PartyType } from '../api/parties';
import LoadingState from './LoadingState';
import EmptyState from './EmptyState';

function formatInr(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const n = typeof value === 'string' ? Number(value) : value;
  if (Number.isNaN(n)) return '₹0.00';
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const STATUS_BADGE: Record<string, string> = {
  ACTIVE: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  INACTIVE: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};

const TRANSACTION_LABEL: Record<string, string> = {
  SALES_INVOICE: 'Sales Invoice', SALES_ORDER: 'Sales Order', DELIVERY_CHALLAN: 'Delivery Challan',
  SALES_RETURN: 'Sales Return', CUSTOMER_RECEIPT: 'Payment Received',
  PURCHASE_INVOICE: 'Purchase Invoice', PURCHASE_ORDER: 'Purchase Order', GOODS_RECEIPT: 'Goods Receipt',
  PURCHASE_RETURN: 'Purchase Return', SUPPLIER_PAYMENT: 'Payment Made',
};

export interface PartyProfileProps {
  partyType: PartyType;
  partyId: string;
  onClose: () => void;
  onEdit?: () => void;
}

const PartyProfile: React.FC<PartyProfileProps> = ({ partyType, partyId, onClose, onEdit }) => {
  const { showToast } = useToast();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [profile, setProfile] = useState<PartyProfileData | null>(null);

  const isCustomer = partyType === 'customer';

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const data = await getPartyProfile(partyType, partyId);
      setProfile(data);
    } catch (err) {
      setError(true);
      showToast(err instanceof ApiError ? err.message : `Unable to load ${partyType} profile.`, 'error');
    } finally {
      setLoading(false);
    }
  }, [partyType, partyId, showToast]);

  useEffect(() => { load(); }, [load]);

  const agingTotal: number = profile
    ? (Object.values(profile.outstanding_aging) as string[]).reduce((sum: number, v: string) => sum + Number(v), 0)
    : 0;

  return (
    <div className="fixed inset-0 z-[70] bg-black/40 backdrop-blur-sm flex items-start md:items-center justify-center p-0 md:p-4 overflow-y-auto animate-fade-in">
      <div className="bg-white dark:bg-gray-900 w-full md:max-w-4xl md:rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 min-h-full md:min-h-0 md:max-h-[90vh] flex flex-col">
        {/* Header bar */}
        <div className="flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-800 shrink-0">
          <h3 className="text-[16px] font-semibold text-gray-800 dark:text-gray-100">
            {isCustomer ? 'Customer' : 'Supplier'} 360 Profile
          </h3>
          <div className="flex items-center gap-2">
            <button onClick={load} className="p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-300"><RefreshCw size={16} className={loading ? 'animate-spin' : ''} /></button>
            <button onClick={onClose} className="p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-300"><X size={20} /></button>
          </div>
        </div>

        <div className="overflow-y-auto p-5 space-y-5">
          {loading ? (
            <LoadingState label={`Loading ${partyType} profile…`} />
          ) : error || !profile ? (
            <EmptyState title={`Unable to load ${partyType} profile.`} description="Please try again." action={<button onClick={load} className="text-[13px] text-[#0066ff] font-medium">Retry</button>} />
          ) : (
            <>
              {/* Party header */}
              <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3 pb-4 border-b border-gray-100 dark:border-gray-800">
                <div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <h2 className="text-[20px] font-bold text-gray-900 dark:text-white">{profile.header.name}</h2>
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[profile.header.status]}`}>{profile.header.status}</span>
                  </div>
                  <p className="text-[13px] text-gray-500 dark:text-gray-400 mt-0.5">
                    {profile.header.code} · {isCustomer ? 'Customer' : 'Supplier'}
                    {profile.header.gstin && ` · GSTIN: ${profile.header.gstin}`}
                  </p>
                  <p className="text-[13px] text-gray-500 dark:text-gray-400">
                    {[profile.header.phone, profile.header.email].filter(Boolean).join(' · ')}
                  </p>
                  {(profile.header.address || profile.header.city) && (
                    <p className="text-[13px] text-gray-500 dark:text-gray-400">
                      {[profile.header.address, profile.header.city, profile.header.state_code, profile.header.pincode].filter(Boolean).join(', ')}
                    </p>
                  )}
                </div>
                {onEdit && (
                  <button onClick={onEdit} className="shrink-0 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 text-[13px] font-medium">
                    Edit {isCustomer ? 'Customer' : 'Supplier'}
                  </button>
                )}
              </div>

              {/* KPI cards */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="p-4 rounded-xl border bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800">
                  <p className="text-[12px] text-blue-700 dark:text-blue-400 font-medium flex items-center gap-1"><TrendingUp size={13} /> {isCustomer ? 'Total Sales' : 'Total Purchases'}</p>
                  <p className="text-[18px] font-bold text-blue-700 dark:text-blue-400 mt-1">{formatInr(isCustomer ? profile.kpis.total_sales : profile.kpis.total_purchases)}</p>
                </div>
                <div className="p-4 rounded-xl border bg-purple-50 dark:bg-purple-900/20 border-purple-200 dark:border-purple-800">
                  <p className="text-[12px] text-purple-700 dark:text-purple-400 font-medium flex items-center gap-1"><Wallet size={13} /> Outstanding {isCustomer ? '(Receivable)' : '(Payable)'}</p>
                  <p className="text-[18px] font-bold text-purple-700 dark:text-purple-400 mt-1">{formatInr(profile.kpis.outstanding)}</p>
                </div>
                <div className="p-4 rounded-xl border bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800">
                  <p className="text-[12px] text-green-700 dark:text-green-400 font-medium flex items-center gap-1"><Receipt size={13} /> {isCustomer ? 'Total Collected' : 'Total Paid'}</p>
                  <p className="text-[18px] font-bold text-green-700 dark:text-green-400 mt-1">{formatInr(isCustomer ? profile.kpis.collected : profile.kpis.paid)}</p>
                </div>
                <div className="p-4 rounded-xl border bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700">
                  <p className="text-[12px] text-gray-600 dark:text-gray-400 font-medium flex items-center gap-1"><FileText size={13} /> {isCustomer ? 'Invoices' : 'Purchase Invoices'} / {isCustomer ? 'Orders' : 'POs'}</p>
                  <p className="text-[18px] font-bold text-gray-800 dark:text-gray-200 mt-1">{profile.kpis.invoice_count} / {profile.kpis.order_count}</p>
                </div>
              </div>
              {profile.kpis.last_transaction_date && (
                <p className="text-[12px] text-gray-500 dark:text-gray-400 -mt-2">Last transaction: {profile.kpis.last_transaction_date}</p>
              )}

              {/* Outstanding aging */}
              <div className="border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                <h4 className="text-[14px] font-semibold text-gray-800 dark:text-gray-200 mb-3">{isCustomer ? 'Receivable' : 'Payable'} Aging</h4>
                {agingTotal === 0 ? (
                  <EmptyState title={`No outstanding ${isCustomer ? 'receivable' : 'payable'}.`} />
                ) : (
                  <>
                    <div className="flex h-3 rounded-full overflow-hidden mb-3 bg-gray-100 dark:bg-gray-800">
                      {(['current', 'days_1_30', 'days_31_60', 'days_61_90', 'days_90_plus'] as const).map((bucket, i) => {
                        const val = Number(profile.outstanding_aging[bucket]);
                        const pct = agingTotal > 0 ? (val / agingTotal) * 100 : 0;
                        const colors = ['bg-green-500', 'bg-yellow-400', 'bg-orange-400', 'bg-red-400', 'bg-red-700'];
                        return pct > 0 ? <div key={bucket} className={colors[i]} style={{ width: `${pct}%` }} /> : null;
                      })}
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-[12px]">
                      <span>Current: <strong>{formatInr(profile.outstanding_aging.current)}</strong></span>
                      <span>1-30d: <strong>{formatInr(profile.outstanding_aging.days_1_30)}</strong></span>
                      <span>31-60d: <strong>{formatInr(profile.outstanding_aging.days_31_60)}</strong></span>
                      <span>61-90d: <strong>{formatInr(profile.outstanding_aging.days_61_90)}</strong></span>
                      <span className="text-red-600 dark:text-red-400">90+ days: <strong>{formatInr(profile.outstanding_aging.days_90_plus)}</strong></span>
                      <span>No due date: <strong>{formatInr(profile.outstanding_aging.no_due_date)}</strong></span>
                    </div>
                  </>
                )}
              </div>

              {/* Top products */}
              <div className="border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                <h4 className="text-[14px] font-semibold text-gray-800 dark:text-gray-200 mb-3 flex items-center gap-1.5"><Package size={15} /> Top Products</h4>
                {profile.top_products.length === 0 ? (
                  <EmptyState title={isCustomer ? 'No products purchased yet.' : 'No products purchased from this supplier yet.'} />
                ) : (
                  <div className="space-y-1.5">
                    {profile.top_products.map((p) => (
                      <div key={p.product_id} className="flex items-center justify-between py-1.5 border-b border-gray-50 dark:border-gray-800 last:border-0">
                        <div>
                          <p className="text-[13px] font-medium text-gray-900 dark:text-gray-100">{p.product_name}</p>
                          <p className="text-[11px] text-gray-500 dark:text-gray-400">Qty {p.quantity} · Last: {p.last_transaction_date || '—'}</p>
                        </div>
                        <span className="text-[13px] font-semibold text-gray-700 dark:text-gray-300">{formatInr(p.value)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Payment history */}
              <div className="border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                <h4 className="text-[14px] font-semibold text-gray-800 dark:text-gray-200 mb-3 flex items-center gap-1.5"><Wallet size={15} /> {isCustomer ? 'Payment / Collection History' : 'Payment History'}</h4>
                {profile.payment_history.length === 0 ? (
                  <EmptyState title="No payment history available." />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-[12px] text-left">
                      <thead>
                        <tr className="text-gray-500 dark:text-gray-400 uppercase text-[10px]">
                          <th className="py-1.5 pr-2">Date</th><th className="py-1.5 pr-2">Reference</th><th className="py-1.5 pr-2">Method</th>
                          <th className="py-1.5 pr-2 text-right">Amount</th><th className="py-1.5 pr-2 text-right">Unallocated</th><th className="py-1.5 text-right">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                        {profile.payment_history.map((p, i) => (
                          <tr key={i}>
                            <td className="py-1.5 pr-2 text-gray-600 dark:text-gray-400">{p.date}</td>
                            <td className="py-1.5 pr-2 font-medium text-gray-900 dark:text-gray-100">{p.reference}</td>
                            <td className="py-1.5 pr-2 text-gray-600 dark:text-gray-400">{p.method}</td>
                            <td className="py-1.5 pr-2 text-right font-semibold text-gray-900 dark:text-gray-100">{formatInr(p.amount)}</td>
                            <td className="py-1.5 pr-2 text-right text-gray-500 dark:text-gray-400">{formatInr(p.unallocated_amount)}</td>
                            <td className="py-1.5 text-right text-gray-500 dark:text-gray-400">{p.status}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Recent transactions */}
              <div className="border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                <h4 className="text-[14px] font-semibold text-gray-800 dark:text-gray-200 mb-3 flex items-center gap-1.5"><ShoppingCart size={15} /> Recent Transactions</h4>
                {profile.recent_transactions.length === 0 ? (
                  <EmptyState title="No transactions yet." />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-[12px] text-left">
                      <thead>
                        <tr className="text-gray-500 dark:text-gray-400 uppercase text-[10px]">
                          <th className="py-1.5 pr-2">Date</th><th className="py-1.5 pr-2">Type</th><th className="py-1.5 pr-2">Reference</th>
                          <th className="py-1.5 pr-2 text-right">Amount</th><th className="py-1.5 text-right">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                        {profile.recent_transactions.map((t, i) => (
                          <tr key={i}>
                            <td className="py-1.5 pr-2 text-gray-600 dark:text-gray-400">{t.date}</td>
                            <td className="py-1.5 pr-2 text-gray-700 dark:text-gray-300">{TRANSACTION_LABEL[t.type] || t.type}</td>
                            <td className="py-1.5 pr-2 font-medium text-gray-900 dark:text-gray-100">{t.reference}</td>
                            <td className="py-1.5 pr-2 text-right font-semibold text-gray-900 dark:text-gray-100">{t.amount ? formatInr(t.amount) : '—'}</td>
                            <td className="py-1.5 text-right text-gray-500 dark:text-gray-400">{t.status}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default PartyProfile;
