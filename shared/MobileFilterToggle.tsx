// Small chevron/filter toggle button used next to a mobile list screen's
// page title — pairs with the "hidden md:flex" idiom already used
// elsewhere in this codebase (e.g. ExportButton's own dropdown) to
// collapse that screen's search/filter/export/add toolbar by default on
// mobile, since stacking all of it full-width pushed the actual list
// below the fold on small screens.
import React from 'react';
import { SlidersHorizontal, ChevronDown } from 'lucide-react';

export interface MobileFilterToggleProps {
  open: boolean;
  onClick: () => void;
}

const MobileFilterToggle: React.FC<MobileFilterToggleProps> = ({ open, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    aria-expanded={open}
    className="md:hidden shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 text-[13px]"
  >
    <SlidersHorizontal size={14} />
    <ChevronDown size={14} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
  </button>
);

export default MobileFilterToggle;
