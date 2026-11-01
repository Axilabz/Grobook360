import { describe, expect, it } from 'vitest';
import { ROUTE_PERMISSIONS, isViewAuthorized } from '../../shared/routePermissions';

// RBAC Alignment Phase: this is the single choke-point App.tsx uses to
// decide whether a dashboardView may render at all — previously nothing
// checked this and every view rendered once a user was merely
// authenticated. Full-app-mount testing was judged too fragile here
// (every management screen fetches real API data on mount); this tests
// the guard logic directly instead, which is what actually matters.
describe('routePermissions (RBAC Alignment Phase route guard)', () => {
  it('permits a permission-free view regardless of granted permissions', () => {
    expect(isViewAuthorized('Home', () => false)).toBe(true);
    expect(isViewAuthorized('Sync Center', () => false)).toBe(true);
  });

  it('denies a single-permission view when the permission is missing', () => {
    expect(isViewAuthorized('Suppliers', () => false)).toBe(false);
  });

  it('permits a single-permission view when the permission is granted', () => {
    expect(isViewAuthorized('Suppliers', (code) => code === 'suppliers.view')).toBe(true);
  });

  it('treats a multi-permission (OR) view as authorized if ANY listed code is granted', () => {
    expect(isViewAuthorized('Credit/Debit Notes', (code) => code === 'debit_note.view')).toBe(true);
    expect(isViewAuthorized('Credit/Debit Notes', () => false)).toBe(false);
  });

  it('denies a Salesperson-shaped permission set exactly where the new matrix says No Access', () => {
    // Mirrors backend ROLE_DEFAULT_PERMISSIONS["SALESPERSON"] post-alignment:
    // no suppliers.*, no accounting.*, no gst.*, no purchase_order.* etc.
    const salespersonPermissions = new Set([
      'customers.view', 'customers.create', 'customers.update',
      'products.view', 'inventory.view',
      'sales_invoice.view', 'sales_invoice.create', 'sales_invoice.edit', 'sales_invoice.cancel',
      'customer_receipt.view', 'customer_receipt.create', 'customer_receipt.edit',
      'reports.view_dashboard', 'reports.view_sales', 'reports.view_inventory',
    ]);
    const has = (code: string) => salespersonPermissions.has(code);

    expect(isViewAuthorized('Suppliers', has)).toBe(false);
    expect(isViewAuthorized('Accounting', has)).toBe(false);
    expect(isViewAuthorized('GST Filing', has)).toBe(false);
    expect(isViewAuthorized('Purchase Orders', has)).toBe(false);
    expect(isViewAuthorized('Users', has)).toBe(false);
    expect(isViewAuthorized('Configuration', has)).toBe(false);
    // But still authorized for what Salesperson keeps:
    expect(isViewAuthorized('Customers', has)).toBe(true);
    expect(isViewAuthorized('Sales Invoices', has)).toBe(true);
    expect(isViewAuthorized('Home', has)).toBe(true);
  });

  it('denies a Manager-shaped permission set exactly where the new matrix narrowed it', () => {
    // Mirrors backend ROLE_DEFAULT_PERMISSIONS["MANAGER"] post-alignment:
    // roles.view/permissions.view removed -> "Users" nav item unaffected
    // (gated by users.view, which Manager keeps), but the Header's own
    // "User Permission" button (gated by roles.view) must disappear —
    // that's covered in Header.tsx, not this route map. This test just
    // confirms the route map's own permission codes are the ones that
    // changed, so a Manager missing roles.view is irrelevant to any
    // dashboardView (no view in ROUTE_PERMISSIONS requires roles.view).
    expect(Object.values(ROUTE_PERMISSIONS).flat().includes('roles.view')).toBe(false);
  });
});
