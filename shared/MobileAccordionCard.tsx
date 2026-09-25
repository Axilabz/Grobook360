// Reusable collapsed-by-default mobile list card — replaces the
// always-expanded "md:hidden" card pattern duplicated across every
// management screen's mobile view. Collapsed state shows only the
// header row (title/subtitle/badge); tapping it reveals the details +
// action buttons passed as children. Each card manages its own open
// state independently (no "close others" behavior — a list of several
// open cards is fine and keeps this component free of any parent-level
// coordination).
import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';

export interface MobileAccordionCardProps {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  badge?: React.ReactNode;
  /** Details + action buttons, only rendered while expanded. */
  children: React.ReactNode;
  defaultOpen?: boolean;
}

const MobileAccordionCard: React.FC<MobileAccordionCardProps> = ({ title, subtitle, badge, children, defaultOpen = false }) => {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-3 p-4 text-left"
        aria-expanded={open}
      >
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-gray-900 dark:text-white text-[15px] truncate">{title}</div>
          {subtitle && <div className="text-[13px] text-gray-500 dark:text-gray-400 truncate">{subtitle}</div>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {badge}
          <ChevronDown size={16} className={`text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} />
        </div>
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-gray-100 dark:border-gray-800 pt-3">
          {children}
        </div>
      )}
    </div>
  );
};

export default MobileAccordionCard;
