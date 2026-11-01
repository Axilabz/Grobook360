// Central route-level permission registry for the RBAC Alignment Phase.
//
// `Sidebar.tsx` already gates nav-item VISIBILITY by these same permission
// codes, but hiding a menu item was never a substitute for authorization —
// before this registry, every `dashboardView` branch in App.tsx rendered
// unconditionally once a user was merely authenticated, regardless of role.
// This map is consumed once in App.tsx to gate the actual render, so nav
// visibility and route access always agree (same codes, one source of truth).
//
// `null` = no permission required (Home, Sync Center are tenant-session
// scoped, not a gated business module — see Sidebar.tsx's own comments).
// `string[]` = any ONE of the listed codes is sufficient (OR), matching the
// equivalent `hasPermission(a) || hasPermission(b)` checks already used in
// Sidebar.tsx for the same views.
export const ROUTE_PERMISSIONS: Record<string, string | string[] | null> = {
  'Home': null,
  'Customers': 'customers.view',
  'Suppliers': 'suppliers.view',
  'Products': 'products.view',
  'Inventory': 'inventory.view',
  'Estimates': 'sales_estimate.view',
  'Sales Orders': 'sales_order.view',
  'Delivery Challans': 'delivery_challan.view',
  'Sales Invoices': 'sales_invoice.view',
  'Sales Returns': 'sales_return.view',
  'Credit/Debit Notes': ['credit_note.view', 'debit_note.view'],
  'Purchase Orders': 'purchase_order.view',
  'Goods Receipts': 'goods_receipt.view',
  'Purchase Invoices': 'purchase_invoice.view',
  'Purchase Returns': 'purchase_return.view',
  'Customer Receipts': 'customer_receipt.view',
  'Supplier Payments': 'supplier_payment.view',
  'Accounting': 'accounting.view_journals',
  'GST Filing': 'gst.view',
  'Reports': ['reports.view_dashboard', 'reports.view_sales'],
  'Analysis': ['reports.view_dashboard', 'reports.view_sales', 'reports.view_purchase', 'reports.view_inventory'],
  'Sync Center': null,
  'Payroll': ['employees.view', 'payroll.view'],
  'View Company': 'configuration.view',
  'Users': 'users.view',
  'Configuration': 'configuration.view',
};

/** True if the given dashboardView may be rendered for a user with `hasPermission`. */
export function isViewAuthorized(view: string, hasPermission: (code: string) => boolean): boolean {
  const required = ROUTE_PERMISSIONS[view];
  if (required == null) return true;
  if (Array.isArray(required)) return required.some(hasPermission);
  return hasPermission(required);
}
