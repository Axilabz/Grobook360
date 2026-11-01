import React, { useState, useEffect, useRef } from 'react';
import {
  Home, Layers, ShoppingCart, ShoppingBag, Book, Wallet,
  FileCheck, Banknote, FileText, BarChart, Bell, ChevronDown, ChevronRight, ChevronLeft, Users, RefreshCw
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

interface SidebarProps {
  isCollapsed: boolean;
  toggleSidebar: () => void;
  onNavigate: (view: string) => void;
}

interface HoveredItemState {
  top: number;
  label: string;
  subItems?: string[];
}

const Sidebar: React.FC<SidebarProps> = ({ isCollapsed, toggleSidebar, onNavigate }) => {
  // Requirement 6: By default all modules closed
  const [openMenus, setOpenMenus] = useState<string[]>([]);

  // Track active states for highlighting
  const [activeParent, setActiveParent] = useState<string>('Home');
  const [activeChild, setActiveChild] = useState<string>('');

  // Tooltip State
  const [hoveredItem, setHoveredItem] = useState<HoveredItemState | null>(null);
  const hoverTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { hasPermission } = useAuth();

  const menuItems = [
    { label: 'Home', icon: <Home size={20} />, path: '/' },
    {
      label: 'Items',
      icon: <Layers size={20} />,
      // Visibility here is UX only — hiding the item is NOT authorization
      // (PROMPT-006 S27 pattern). The API independently re-checks
      // products.view/inventory.view regardless (PROMPT-009/010).
      subItems: [
        ...(hasPermission('products.view') ? ['Products'] : []),
        ...(hasPermission('inventory.view') ? ['Inventory'] : []),
      ],
    },
    { label: 'Sales',
      icon: <ShoppingCart size={20} />,
      // Visibility here is UX only — hiding the item is NOT authorization
      // (PROMPT-006 S27 pattern). The API independently re-checks
      // customers.view regardless (PROMPT-007).
      subItems: [
        ...(hasPermission('customers.view') ? ['Customers'] : []),
        ...(hasPermission('sales_estimate.view') ? ['Estimates'] : []),
        ...(hasPermission('sales_order.view') ? ['Sales Orders'] : []),
        ...(hasPermission('delivery_challan.view') ? ['Delivery Challans'] : []),
        ...(hasPermission('sales_invoice.view') ? ['Sales Invoices'] : []),
        ...(hasPermission('sales_return.view') ? ['Sales Returns'] : []),
        ...((hasPermission('credit_note.view') || hasPermission('debit_note.view')) ? ['Credit/Debit Notes'] : []),
      ] },
    {
      label: 'Purchase',
      icon: <ShoppingBag size={20} />,
      // Visibility here is UX only — hiding the item is NOT authorization
      // (PROMPT-006 S27 pattern). The API independently re-checks
      // suppliers.view/purchase_order.view/etc. regardless (PROMPT-008/019).
      // subItems is `undefined` (not `[]`) when every entry is hidden,
      // since an empty array is still truthy and would render a dropdown
      // arrow with nothing under it.
      subItems: (() => {
        const items = [
          ...(hasPermission('suppliers.view') ? ['Suppliers'] : []),
          ...(hasPermission('purchase_order.view') ? ['Purchase Orders'] : []),
          ...(hasPermission('goods_receipt.view') ? ['Goods Receipts'] : []),
          ...(hasPermission('purchase_invoice.view') ? ['Purchase Invoices'] : []),
          ...(hasPermission('purchase_return.view') ? ['Purchase Returns'] : []),
        ];
        return items.length > 0 ? items : undefined;
      })(),
    },
    {
      label: 'Payments',
      icon: <Wallet size={20} />,
      // Visibility here is UX only — hiding the item is NOT authorization
      // (PROMPT-006 S27 pattern). The API independently re-checks
      // customer_receipt.view/supplier_payment.view regardless (PROMPT-024).
      subItems: (() => {
        const items = [
          ...(hasPermission('customer_receipt.view') ? ['Customer Receipts'] : []),
          ...(hasPermission('supplier_payment.view') ? ['Supplier Payments'] : []),
        ];
        return items.length > 0 ? items : undefined;
      })(),
    },
    {
      label: 'Accountant',
      icon: <Book size={20} />,
      // Visibility here is UX only — hiding the item is NOT authorization
      // (PROMPT-006 S27 pattern). The API independently re-checks
      // accounting.view_journals/etc. regardless (PROMPT-025).
      subItems: (() => {
        const items = [
          ...(hasPermission('accounting.view_journals') ? ['Accounting'] : []),
        ];
        return items.length > 0 ? items : undefined;
      })(),
    },
    // Visibility here is UX only — hiding the item is NOT authorization
    // (PROMPT-006 S27 pattern). The API independently re-checks gst.view
    // regardless (PROMPT-026).
    ...(hasPermission('gst.view') ? [{ label: 'GST Filing', icon: <FileCheck size={20} /> }] : []),
    // Visibility here is UX only — hiding the item is NOT authorization
    // (PROMPT-006 S27 pattern). The API independently re-checks
    // employees.view/payroll.view/etc. regardless (PROMPT-029).
    ...(hasPermission('employees.view') || hasPermission('payroll.view') ? [{ label: 'Payroll', icon: <Banknote size={20} /> }] : []),
    // Visibility here is UX only — hiding the item is NOT authorization
    // (PROMPT-006 S27 pattern). The API independently re-checks
    // reports.view_dashboard/etc. regardless (PROMPT-027).
    ...(hasPermission('reports.view_dashboard') || hasPermission('reports.view_sales') ? [{ label: 'Reports', icon: <FileText size={20} /> }] : []),
    // Visibility here is UX only — hiding the item is NOT authorization
    // (PROMPT-006 S27 pattern). The API independently re-checks the same
    // reports.view_* codes regardless — Analysis has no permission codes
    // of its own, it's an alternate interactive VIEW over the same
    // authorized data Reports already exposes.
    ...(hasPermission('reports.view_dashboard') || hasPermission('reports.view_sales') || hasPermission('reports.view_purchase') || hasPermission('reports.view_inventory')
      ? [{ label: 'Analysis', icon: <BarChart size={20} /> }] : []),
    // No permission gate — the sync queue is local-device data scoped to
    // this authenticated user/tenant session, not a tenant-wide
    // financial report (PROMPT-028 §42).
    { label: 'Sync Center', icon: <RefreshCw size={20} /> },
    { label: 'Notification', icon: <Bell size={20} /> },
    // Visibility here is UX only — hiding the item is NOT authorization
    // (PROMPT-006 S27). The API independently re-checks users.view regardless.
    ...(hasPermission('users.view') ? [{ label: 'Users', icon: <Users size={20} /> }] : []),
  ];

  // RBAC Alignment Phase (§5 Sidebar Rules: "Hide a parent module if the
  // user has no access to any of its child pages", "Do not display empty
  // sub-menus"). Items/Sales/Purchase/Payments/Accountant always build a
  // `subItems` key above (possibly an empty array, or `undefined` via the
  // "if nothing survived, return undefined" pattern) — a leaf item with no
  // `subItems` key at all (Home, GST Filing, Payroll, Reports, Analysis,
  // Sync Center, Notification, Users) is already permission-gated by the
  // spread above and always kept here.
  const visibleMenuItems = menuItems.filter((item) => {
    if (!('subItems' in item)) return true;
    return Array.isArray(item.subItems) && item.subItems.length > 0;
  });

  const handleParentClick = (label: string, hasSubItems: boolean) => {
    // If it has sub-items, toggle the menu
    if (hasSubItems) {
        if (isCollapsed) {
            // If sidebar is collapsed and user clicks a parent with subs, 
            // typically we might want to expand sidebar or show a tooltip.
            // For this design, we'll expand the sidebar to show subs.
            toggleSidebar();
            setOpenMenus([label]);
        } else {
             setOpenMenus(prev =>
                prev.includes(label) ? prev.filter(item => item !== label) : [...prev, label]
             );
        }
    } else {
        // Requirement 1 & 3: Set active parent
        setActiveParent(label);
        setActiveChild(''); // Clear child selection
        onNavigate(label); // Navigate to parent route
        
        // Requirement 4: On mobile, if a module is selected, collapse sidebar to view page
        if (window.innerWidth < 768) {
            toggleSidebar();
        }
    }
  };

  const handleSubItemClick = (parentLabel: string, subLabel: string) => {
      // Requirement 2: Highlight selected sub-module
      setActiveParent(parentLabel);
      setActiveChild(subLabel);
      onNavigate(subLabel); // Navigate to sub route

      // Requirement 4: Mobile behavior
      if (window.innerWidth < 768) {
        toggleSidebar();
      }
      
      // Close tooltip if open
      setHoveredItem(null);
  };

  const handleMouseEnter = (e: React.MouseEvent, item: any) => {
    if (!isCollapsed) return;

    if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current);

    const rect = e.currentTarget.getBoundingClientRect();
    setHoveredItem({
        top: rect.top,
        label: item.label,
        subItems: item.subItems
    });
  };

  const handleMouseLeave = () => {
    if (!isCollapsed) return;
    
    hoverTimeoutRef.current = setTimeout(() => {
        setHoveredItem(null);
    }, 150); // Small delay to allow moving to the tooltip
  };

  // Clear hover state when sidebar expands
  useEffect(() => {
    if (!isCollapsed) {
        setHoveredItem(null);
    }
  }, [isCollapsed]);

  // Mobile drawer open: sits above every page's own fixed content header
  // (z-[55], see e.g. ProductManagement.tsx) so it isn't covered by
  // whatever screen is open underneath, but stays below the app's top
  // Header bar (z-[60]) so that remains reachable. Desktop icon rail is
  // deliberately ABOVE every page's own content/header (z-[65], above the
  // app's own top Header bar at z-[60]) so the whole sidebar — the rail,
  // its collapse toggle, and its collapsed-state hover flyout — always
  // renders as one consistent front layer, never partially hidden behind
  // a page's own (inconsistently z-indexed) sticky header. It stays below
  // modal dialogs (z-[70] and up) so an open modal still covers it.
  //
  // NOTE: any word placed inside the className template literal below —
  // even inside a "/* comment */" — becomes a real, space-separated class
  // token the browser will try to match (className is just a string).
  // A previous version of this comment used the word "sticky" here, which
  // collided with Tailwind's own `.sticky { position: sticky }` utility
  // and silently broke this element's `fixed` positioning. Keep
  // explanatory prose like this OUTSIDE the template literal.
  return (
    <>
      <aside
        className={`
          fixed left-0 top-16 bottom-0 bg-[#f1f5f9] dark:bg-gray-900
          transition-transform duration-300 md:transition-all
          ${isCollapsed ? 'z-[65]' : 'z-[58] md:z-[65]'} flex flex-col
          overflow-hidden md:overflow-visible
          w-[80vw] max-w-[320px] shadow-xl md:shadow-none
          ${isCollapsed ? '-translate-x-full md:translate-x-0 border-0 md:w-16 md:border-r md:border-gray-200 dark:md:border-gray-700' : 'translate-x-0 border-r border-gray-200 dark:border-gray-700 md:max-w-none md:w-64'}
        `}
      >
        {/* Toggle Button Container - High z-index to stay above content */}
        <div className="absolute -right-3 top-2 z-[66] hidden md:block">
          <button
            onClick={toggleSidebar}
            className="bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-sm p-0.5 text-gray-600 dark:text-gray-300 shadow-sm transition-colors"
          >
            {isCollapsed ? <ChevronRight size={16} strokeWidth={2.5} /> : <ChevronLeft size={16} strokeWidth={2.5} />}
          </button>
        </div>

        <div className="flex-1 overflow-y-auto py-6 custom-scrollbar overflow-x-hidden relative z-30">
          <ul className="space-y-2 px-2">
            {visibleMenuItems.map((item) => {
              const isOpen = openMenus.includes(item.label);
              const isActive = activeParent === item.label;
              
              // Requirement 1: Selected modules should be thin box with color #8AC0FF
              // Applied when the parent is active (either directly or via a child)
              const activeStyle = isActive 
                  ? 'border border-[#8AC0FF] bg-[#eff6ff] dark:bg-blue-900/30 text-[#0066ff] dark:text-blue-400' 
                  : 'border border-transparent text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-800';

              // Styles specific to collapsed (Square) vs expanded (Rectangle) view
              const layoutClasses = isCollapsed
                  ? 'w-10 h-10 justify-center mx-auto mb-2' // Fixed square size, centered
                  : 'px-4 py-3 mx-1';

              return (
                <li key={item.label}>
                  <div
                    className={`
                      relative flex items-center cursor-pointer transition-all duration-200 select-none rounded-md whitespace-nowrap
                      ${layoutClasses}
                      ${activeStyle}
                    `}
                    onClick={() => handleParentClick(item.label, !!item.subItems)}
                    onMouseEnter={(e) => handleMouseEnter(e, item)}
                    onMouseLeave={handleMouseLeave}
                  >
                    <span className={`shrink-0 ${isActive ? 'text-[#0066ff] dark:text-blue-400' : ''}`}>
                        {item.icon}
                    </span>
                    
                    {!isCollapsed && (
                      <>
                        <span className={`ml-4 text-[14px] md:text-[15px] lg:text-[16px] font-medium flex-1 ${isActive ? 'font-semibold' : ''}`}>
                          {item.label}
                        </span>
                        {item.subItems && (
                          <ChevronDown
                            size={16}
                            className={`transition-transform duration-200 ${isOpen ? 'rotate-180' : ''} ${isActive ? 'text-[#0066ff] dark:text-blue-400' : 'text-gray-500 dark:text-gray-400'}`}
                          />
                        )}
                      </>
                    )}
                  </div>

                  {/* Submenu (Expanded State) */}
                  {!isCollapsed && item.subItems && isOpen && (
                    <ul className="mt-1 ml-4 border-l-2 border-gray-200 dark:border-gray-700 space-y-1">
                      {item.subItems.map((sub) => {
                         const isSubActive = activeChild === sub;
                         return (
                          <li key={sub}>
                            <div
                              onClick={(e) => {
                                  e.stopPropagation();
                                  handleSubItemClick(item.label, sub);
                              }}
                              className={`
                                pl-4 pr-4 py-2 text-[13px] md:text-[14px] lg:text-[15px] cursor-pointer transition-all duration-200 rounded-md block my-1 mr-2
                                /* Requirement 2: Highlight sub module only if selected */
                                ${isSubActive 
                                  ? 'bg-[#0066ff] text-white font-medium shadow-sm' 
                                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800'}
                              `}
                            >
                              {sub}
                            </div>
                          </li>
                         );
                      })}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      </aside>

      {/* Tooltip / Hover Menu for Collapsed Sidebar (Desktop Only) — part of
          the same front layer as the icon rail/toggle above (z-[67], one
          step above them), so it renders cleanly on top of a page's own
          header or content wherever it lands next to the hovered icon,
          exactly like any standard flyout/popover. Still below modal
          dialogs (z-[70]+). */}
      {isCollapsed && hoveredItem && (
        <div
          className="fixed left-16 z-[67] w-56 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-r-lg shadow-xl animate-fade-in hidden md:block overflow-hidden"
          style={{ top: hoveredItem.top }}
          onMouseEnter={() => {
             if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current);
          }}
          onMouseLeave={() => {
             setHoveredItem(null);
          }}
        >
            <div className="bg-gray-50 dark:bg-gray-900 px-4 py-3 border-b border-gray-100 dark:border-gray-700">
                <p className="font-semibold text-gray-800 dark:text-gray-200">{hoveredItem.label}</p>
            </div>
            
            {hoveredItem.subItems && hoveredItem.subItems.length > 0 && (
                <div className="p-2 bg-white dark:bg-gray-800">
                    <ul className="space-y-1">
                        {hoveredItem.subItems.map((sub) => {
                             const isSubActive = activeParent === hoveredItem.label && activeChild === sub;
                             return (
                                <li 
                                    key={sub}
                                    onClick={() => handleSubItemClick(hoveredItem.label, sub)}
                                    className={`
                                        px-3 py-2 text-sm rounded-md cursor-pointer transition-colors
                                        ${isSubActive 
                                            ? 'bg-[#0066ff] text-white font-medium' 
                                            : 'text-gray-600 dark:text-gray-400 hover:bg-blue-50 dark:hover:bg-gray-700 hover:text-[#0066ff] dark:hover:text-blue-400'}
                                    `}
                                >
                                    {sub}
                                </li>
                             );
                        })}
                    </ul>
                </div>
            )}
        </div>
      )}
    </>
  );
};

export default Sidebar;