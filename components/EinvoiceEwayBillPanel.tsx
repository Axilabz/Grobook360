import React, { useState, useEffect, useCallback } from 'react';
import { FileCheck2, Truck, RefreshCw, Ban, Loader2, AlertTriangle, X, QrCode } from 'lucide-react';
import Input from './Input';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { ApiError } from '../api/client';
import { EinvoiceDetail, getEinvoice, generateEinvoice, refreshEinvoiceStatus, cancelEinvoice } from '../api/einvoice';
import { EwayBillDetail, getEwayBillByInvoice, generateEwayBill, refreshEwayBillStatus, cancelEwayBill } from '../api/ewayBills';

const STATUS_BADGE: Record<string, string> = {
  NOT_APPLICABLE: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400',
  READY: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  QUEUED: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  PROCESSING: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  GENERATED: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  FAILED: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  CANCEL_REQUESTED: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  CANCELLED: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
  STATUS_UNKNOWN: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
};

const STATUS_LABEL: Record<string, string> = {
  NOT_APPLICABLE: 'Not Applicable', READY: 'Ready', QUEUED: 'Queued', PROCESSING: 'Processing',
  GENERATED: 'Generated', FAILED: 'Failed', CANCEL_REQUESTED: 'Cancelling…', CANCELLED: 'Cancelled',
  STATUS_UNKNOWN: 'Unknown',
};

interface Props {
  invoiceId: string;
  invoiceStatus: string;
}

const EinvoiceEwayBillPanel: React.FC<Props> = ({ invoiceId, invoiceStatus }) => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const canGenerateEinvoice = hasPermission('einvoice.generate');
  const canCancelEinvoice = hasPermission('einvoice.cancel');
  const canViewEinvoice = hasPermission('einvoice.view');
  const canGenerateEwb = hasPermission('eway_bill.generate');
  const canCancelEwb = hasPermission('eway_bill.cancel');
  const canViewEwb = hasPermission('eway_bill.view');

  const [einvoice, setEinvoice] = useState<EinvoiceDetail | null>(null);
  const [ewayBill, setEwayBill] = useState<EwayBillDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isActing, setIsActing] = useState(false);
  const [showEwbForm, setShowEwbForm] = useState(false);
  const [cancelTarget, setCancelTarget] = useState<'einvoice' | 'ewaybill' | null>(null);
  const [cancelReason, setCancelReason] = useState('');

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      if (canViewEinvoice) setEinvoice(await getEinvoice(invoiceId));
      if (canViewEwb) setEwayBill(await getEwayBillByInvoice(invoiceId));
    } catch {
      // Non-fatal — the panel simply shows nothing for that section.
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceId]);

  useEffect(() => { if (invoiceStatus === 'POSTED') load(); }, [load, invoiceStatus]);

  if (invoiceStatus !== 'POSTED') return null;

  const runAction = async (fn: () => Promise<unknown>, successMsg: string) => {
    setIsActing(true);
    try {
      await fn();
      showToast(successMsg, 'success');
      await load();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Something went wrong.', 'error');
    } finally {
      setIsActing(false);
      setCancelTarget(null);
      setCancelReason('');
    }
  };

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-md p-4 space-y-4">
      <h4 className="text-[13px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
        GST Integration
      </h4>

      {isLoading ? (
        <div className="flex justify-center py-4"><Loader2 size={20} className="animate-spin text-gray-400" /></div>
      ) : (
        <>
          {/* E-Invoice */}
          {canViewEinvoice && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <FileCheck2 size={15} className="text-gray-500 dark:text-gray-400" />
                <span className="text-[13px] font-medium text-gray-800 dark:text-gray-200">E-Invoice</span>
                {einvoice && (
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${STATUS_BADGE[einvoice.status]}`}>
                    {STATUS_LABEL[einvoice.status]}
                  </span>
                )}
              </div>

              {einvoice?.status === 'GENERATED' && (
                <div className="text-[12px] text-gray-600 dark:text-gray-300 space-y-0.5 pl-6">
                  <p>IRN: <span className="font-mono break-all">{einvoice.irn}</span></p>
                  <p>Ack Number: {einvoice.ack_number} · Ack Date: {einvoice.ack_date ? new Date(einvoice.ack_date).toLocaleString() : '—'}</p>
                  {einvoice.has_signed_qr && (
                    <p className="flex items-center gap-1 text-green-700 dark:text-green-400"><QrCode size={12} /> Signed QR available</p>
                  )}
                </div>
              )}
              {einvoice && einvoice.status !== 'GENERATED' && einvoice.applicability_reason && (
                <p className="text-[12px] text-gray-500 dark:text-gray-400 pl-6">{einvoice.applicability_reason}</p>
              )}
              {einvoice?.provider_response_message && ['FAILED', 'STATUS_UNKNOWN'].includes(einvoice.status) && (
                <p className="text-[12px] text-red-600 dark:text-red-400 pl-6">{einvoice.provider_response_message}</p>
              )}

              <div className="flex flex-wrap gap-2 pl-6">
                {canGenerateEinvoice && (!einvoice || ['READY', 'NOT_APPLICABLE', 'FAILED', 'STATUS_UNKNOWN'].includes(einvoice.status)) && (
                  <button disabled={isActing} onClick={() => runAction(() => generateEinvoice(invoiceId), 'E-Invoice generated.')} className="px-3 py-1.5 rounded-md bg-[#0066ff] hover:bg-blue-700 text-white text-[12px] font-medium disabled:opacity-60">
                    Generate E-Invoice
                  </button>
                )}
                {canViewEinvoice && einvoice && ['PROCESSING', 'STATUS_UNKNOWN', 'GENERATED'].includes(einvoice.status) && (
                  <button disabled={isActing} onClick={() => runAction(() => refreshEinvoiceStatus(invoiceId), 'Status refreshed.')} className="flex items-center gap-1 px-3 py-1.5 rounded-md border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[12px] font-medium disabled:opacity-60">
                    <RefreshCw size={12} /> Refresh Status
                  </button>
                )}
                {canCancelEinvoice && einvoice?.status === 'GENERATED' && (
                  <button disabled={isActing} onClick={() => setCancelTarget('einvoice')} className="flex items-center gap-1 px-3 py-1.5 rounded-md border border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 text-[12px] font-medium disabled:opacity-60">
                    <Ban size={12} /> Cancel E-Invoice
                  </button>
                )}
              </div>
            </div>
          )}

          {/* E-Way Bill */}
          {canViewEwb && (
            <div className="space-y-2 pt-3 border-t border-gray-100 dark:border-gray-800">
              <div className="flex items-center gap-2 flex-wrap">
                <Truck size={15} className="text-gray-500 dark:text-gray-400" />
                <span className="text-[13px] font-medium text-gray-800 dark:text-gray-200">E-Way Bill</span>
                {ewayBill && (
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${STATUS_BADGE[ewayBill.status]}`}>
                    {STATUS_LABEL[ewayBill.status]}
                  </span>
                )}
              </div>

              {ewayBill?.status === 'GENERATED' && (
                <div className="text-[12px] text-gray-600 dark:text-gray-300 space-y-0.5 pl-6">
                  <p>E-Way Bill #: <span className="font-mono">{ewayBill.eway_bill_number}</span></p>
                  <p>Valid From: {ewayBill.valid_from ? new Date(ewayBill.valid_from).toLocaleString() : '—'}</p>
                  {ewayBill.vehicle_number && <p>Vehicle: {ewayBill.vehicle_number} · Mode: {ewayBill.transport_mode}</p>}
                </div>
              )}
              {ewayBill?.provider_response_message && ['FAILED', 'STATUS_UNKNOWN'].includes(ewayBill.status) && (
                <p className="text-[12px] text-red-600 dark:text-red-400 pl-6">{ewayBill.provider_response_message}</p>
              )}

              <div className="flex flex-wrap gap-2 pl-6">
                {canGenerateEwb && (!ewayBill || ['READY', 'NOT_APPLICABLE', 'FAILED', 'STATUS_UNKNOWN'].includes(ewayBill.status)) && (
                  <button disabled={isActing} onClick={() => setShowEwbForm(true)} className="px-3 py-1.5 rounded-md bg-[#0066ff] hover:bg-blue-700 text-white text-[12px] font-medium disabled:opacity-60">
                    Generate E-Way Bill
                  </button>
                )}
                {canViewEwb && ewayBill?.id && ['PROCESSING', 'STATUS_UNKNOWN', 'GENERATED'].includes(ewayBill.status) && (
                  <button disabled={isActing} onClick={() => runAction(() => refreshEwayBillStatus(ewayBill.id as string), 'Status refreshed.')} className="flex items-center gap-1 px-3 py-1.5 rounded-md border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[12px] font-medium disabled:opacity-60">
                    <RefreshCw size={12} /> Refresh Status
                  </button>
                )}
                {canCancelEwb && ewayBill?.status === 'GENERATED' && ewayBill.id && (
                  <button disabled={isActing} onClick={() => setCancelTarget('ewaybill')} className="flex items-center gap-1 px-3 py-1.5 rounded-md border border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 text-[12px] font-medium disabled:opacity-60">
                    <Ban size={12} /> Cancel E-Way Bill
                  </button>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {showEwbForm && (
        <GenerateEwayBillModal
          invoiceId={invoiceId}
          onClose={() => setShowEwbForm(false)}
          onSaved={() => { setShowEwbForm(false); load(); }}
        />
      )}

      {cancelTarget && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-sm p-6">
            <div className="flex items-center gap-3 mb-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full shrink-0 bg-red-100 dark:bg-red-900/30">
                <AlertTriangle size={20} className="text-red-600 dark:text-red-400" />
              </div>
              <h3 className="text-[17px] font-semibold text-gray-900 dark:text-white">
                Cancel {cancelTarget === 'einvoice' ? 'E-Invoice' : 'E-Way Bill'}
              </h3>
            </div>
            <p className="text-[13px] text-gray-600 dark:text-gray-300 mb-3">
              This action will be submitted to the integration provider and cannot be undone. It will not affect inventory.
            </p>
            <Input label="Cancellation Reason" value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} />
            <div className="grid grid-cols-2 gap-3 mt-4">
              <button onClick={() => { setCancelTarget(null); setCancelReason(''); }} className="py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-[14px] font-medium">Back</button>
              <button
                disabled={!cancelReason.trim() || isActing}
                onClick={() => {
                  if (cancelTarget === 'einvoice') runAction(() => cancelEinvoice(invoiceId, cancelReason), 'E-Invoice cancelled.');
                  else if (ewayBill?.id) runAction(() => cancelEwayBill(ewayBill.id as string, cancelReason), 'E-Way Bill cancelled.');
                }}
                className="py-2.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-[14px] font-medium disabled:opacity-60"
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const GenerateEwayBillModal: React.FC<{ invoiceId: string; onClose: () => void; onSaved: () => void }> = ({ invoiceId, onClose, onSaved }) => {
  const { showToast } = useToast();
  const [transportMode, setTransportMode] = useState('ROAD');
  const [vehicleNumber, setVehicleNumber] = useState('');
  const [transporterName, setTransporterName] = useState('');
  const [distanceKm, setDistanceKm] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSave = async () => {
    setIsSubmitting(true);
    try {
      await generateEwayBill({
        invoice_id: invoiceId,
        transport_mode: transportMode,
        vehicle_number: vehicleNumber || null,
        transporter_name: transporterName || null,
        distance_km: distanceKm || null,
      });
      showToast('E-Way Bill generated successfully.', 'success');
      onSaved();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.', 'error');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-fade-in">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-md">
        <div className="sticky top-0 flex items-center justify-between p-4 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 z-20">
          <h3 className="text-[16px] font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2"><Truck size={16} /> Generate E-Way Bill</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><X size={18} /></button>
        </div>
        <div className="p-5 space-y-3">
          <div>
            <label className="block text-[13px] font-medium text-gray-600 dark:text-gray-300 mb-1">Transport Mode</label>
            <select value={transportMode} onChange={(e) => setTransportMode(e.target.value)} className="w-full border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-[14px] px-3 py-2">
              <option value="ROAD">Road</option>
              <option value="RAIL">Rail</option>
              <option value="AIR">Air</option>
              <option value="SHIP">Ship</option>
            </select>
          </div>
          <Input label="Vehicle Number" value={vehicleNumber} onChange={(e) => setVehicleNumber(e.target.value)} placeholder="e.g. TN01AB1234" />
          <Input label="Transporter Name (Optional)" value={transporterName} onChange={(e) => setTransporterName(e.target.value)} />
          <Input label="Distance (km, Optional)" type="number" value={distanceKm} onChange={(e) => setDistanceKm(e.target.value)} />
          <p className="text-[12px] text-gray-400">This action will not change inventory.</p>
          <button onClick={handleSave} disabled={isSubmitting} className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-[#0066ff] hover:bg-blue-700 text-white text-[14px] font-medium disabled:opacity-70">
            {isSubmitting && <Loader2 size={16} className="animate-spin" />} Generate
          </button>
        </div>
      </div>
    </div>
  );
};

export default EinvoiceEwayBillPanel;
