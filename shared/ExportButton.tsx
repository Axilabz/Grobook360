// Reusable Excel/PDF export control for the Global Export Framework.
//
// Self-gates on `exportPermission` (mirrors the app's established
// `canCreate`/`canEdit` inline-permission-check convention) so a caller
// only needs to pass the resource key + current filter state, not
// duplicate the hasPermission check — the backend independently
// re-verifies the same permission regardless of whether this button
// renders (api/exports.ts's requestExport surfaces a 403 as a toast if
// it somehow gets called anyway).
import React, { useState, useRef, useEffect } from 'react';
import { Download, ChevronDown, FileSpreadsheet, FileText, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { requestExport, ExportError, ExportFormat, ExportScope } from '../api/exports';

export interface ExportButtonProps {
  resource: string;
  exportPermission: string;
  /** Current list-screen filter state — exported records mirror what's on screen (§6 of the source prompt: preserve search/filter/sort). */
  search?: string;
  status?: string;
  dateFrom?: string;
  dateTo?: string;
  partyId?: string;
  page: number;
  pageSize: number;
  /** Total records matching current filters, so the "All Filtered" option can be hidden/labeled when there's nothing beyond the current page. */
  totalItems?: number;
}

const ExportButton: React.FC<ExportButtonProps> = ({
  resource, exportPermission, search, status, dateFrom, dateTo, partyId, page, pageSize, totalItems,
}) => {
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  if (!hasPermission(exportPermission)) return null;

  const run = async (format: ExportFormat, scope: ExportScope) => {
    const key = `${format}-${scope}`;
    setBusy(key);
    setOpen(false);
    try {
      await requestExport({
        resource, format, scope, search, status, dateFrom, dateTo, partyId,
        page, pageSize,
      });
      showToast(`Export ready — ${format.toUpperCase()} downloaded.`, 'success');
    } catch (err) {
      showToast(err instanceof ExportError ? err.message : 'Export failed. Please try again.', 'error');
    } finally {
      setBusy(null);
    }
  };

  const isBusy = busy !== null;

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={isBusy}
        className="border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 font-semibold text-[14px] px-4 py-2 rounded-lg transition-colors flex items-center justify-center gap-2 whitespace-nowrap hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-60"
      >
        {isBusy ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
        Export
        <ChevronDown size={14} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-64 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-[65] overflow-hidden">
          <div className="px-3 py-2 text-[11px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide border-b border-gray-100 dark:border-gray-700">
            Excel (.xlsx)
          </div>
          <button
            onClick={() => run('xlsx', 'CURRENT_PAGE')}
            className="w-full flex items-center gap-2 px-3 py-2.5 text-[14px] text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 text-left"
          >
            <FileSpreadsheet size={16} className="text-green-600 shrink-0" /> Current Page
          </button>
          <button
            onClick={() => run('xlsx', 'ALL_FILTERED')}
            className="w-full flex items-center gap-2 px-3 py-2.5 text-[14px] text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 text-left"
          >
            <FileSpreadsheet size={16} className="text-green-600 shrink-0" />
            All Filtered Records{typeof totalItems === 'number' ? ` (${totalItems})` : ''}
          </button>

          <div className="px-3 py-2 text-[11px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide border-b border-t border-gray-100 dark:border-gray-700">
            PDF (.pdf)
          </div>
          <button
            onClick={() => run('pdf', 'CURRENT_PAGE')}
            className="w-full flex items-center gap-2 px-3 py-2.5 text-[14px] text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 text-left"
          >
            <FileText size={16} className="text-red-600 shrink-0" /> Current Page
          </button>
          <button
            onClick={() => run('pdf', 'ALL_FILTERED')}
            className="w-full flex items-center gap-2 px-3 py-2.5 text-[14px] text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 text-left"
          >
            <FileText size={16} className="text-red-600 shrink-0" />
            All Filtered Records{typeof totalItems === 'number' ? ` (${totalItems})` : ''}
          </button>
        </div>
      )}
    </div>
  );
};

export default ExportButton;
