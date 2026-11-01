import React from 'react';
import { TrendingUp, TrendingDown, Minus, Info } from 'lucide-react';
import { formatCompactInr, formatQuantity, formatPercent } from '../formatters';

export interface KpiValue {
  current: string; previous: string | null; change: string | null; change_percent: string | null;
}
export interface UnavailableKpi {
  value: null; reason: string;
}

function isUnavailable(kpi: KpiValue | UnavailableKpi): kpi is UnavailableKpi {
  return 'reason' in kpi;
}

export interface KpiCardProps {
  title: string;
  kpi: KpiValue | UnavailableKpi;
  format?: 'currency' | 'quantity' | 'count';
  definition?: string;
  onClick?: () => void;
}

const KpiCard: React.FC<KpiCardProps> = ({ title, kpi, format = 'currency', definition, onClick }) => {
  const formatValue = (v: string | number) => {
    if (format === 'currency') return formatCompactInr(v);
    if (format === 'count') return Number(v).toLocaleString('en-IN');
    return formatQuantity(v);
  };

  return (
    <div
      onClick={onClick}
      className={`bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4 shadow-sm transition-colors ${onClick ? 'cursor-pointer hover:border-blue-300 dark:hover:border-blue-700' : ''}`}
    >
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-[12px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{title}</span>
        {definition && (
          <div className="group relative">
            <Info size={14} className="text-gray-300 dark:text-gray-600 cursor-help" />
            <div className="absolute right-0 top-5 w-56 p-2.5 bg-gray-900 dark:bg-gray-700 text-white text-[11px] rounded-lg shadow-xl invisible group-hover:visible opacity-0 group-hover:opacity-100 transition-opacity z-50">
              {definition}
            </div>
          </div>
        )}
      </div>

      {isUnavailable(kpi) ? (
        <div>
          <p className="text-[20px] font-semibold text-gray-300 dark:text-gray-600">Unavailable</p>
          <p className="text-[11px] text-gray-400 dark:text-gray-500 mt-1 leading-snug">{kpi.reason}</p>
        </div>
      ) : (
        <div>
          <p className="text-[22px] font-bold text-gray-900 dark:text-gray-100">{formatValue(kpi.current)}</p>
          <div className="flex items-center gap-1.5 mt-1 h-5">
            {kpi.change_percent === null ? (
              <span className="text-[11px] text-gray-400 dark:text-gray-500">No comparison data</span>
            ) : (
              (() => {
                const pct = Number(kpi.change_percent);
                const Icon = pct > 0 ? TrendingUp : pct < 0 ? TrendingDown : Minus;
                const colorClass = pct > 0 ? 'text-green-600 dark:text-green-400' : pct < 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-500 dark:text-gray-400';
                return (
                  <span className={`flex items-center gap-1 text-[12px] font-medium ${colorClass}`}>
                    <Icon size={13} /> {formatPercent(pct)} <span className="text-gray-400 dark:text-gray-500 font-normal">vs previous</span>
                  </span>
                );
              })()
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default KpiCard;
