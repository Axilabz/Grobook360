import React, { useState, useEffect, lazy, Suspense } from 'react';
import Layout from './components/Layout';
import SignIn from './components/SignIn';
import SignUp from './components/SignUp';
import ForgotPassword from './components/ForgotPassword';
import ResetPassword from './components/ResetPassword';
import DashboardLayout from './components/DashboardLayout';
import Home from './components/Home';
import { AuthView } from './types';
import { ToastProvider } from './context/ToastContext';
import { useTheme } from './context/ThemeContext';
import { useAuth } from './context/AuthContext';
import { NavigationProvider, useNavigation } from './context/NavigationContext';
import ProtectedRoute from './shared/ProtectedRoute';
import LoadingState from './shared/LoadingState';
import AccessDenied from './shared/AccessDenied';
import { isViewAuthorized } from './shared/routePermissions';

// Screens load on demand: the first paint no longer pays for all 25 modules.
const CustomerManagement = lazy(() => import('./components/CustomerManagement'));
const SupplierManagement = lazy(() => import('./components/SupplierManagement'));
const ProductManagement = lazy(() => import('./components/ProductManagement'));
const InventoryManagement = lazy(() => import('./components/InventoryManagement'));
const EstimateManagement = lazy(() => import('./components/EstimateManagement'));
const SalesOrderManagement = lazy(() => import('./components/SalesOrderManagement'));
const DeliveryChallanManagement = lazy(() => import('./components/DeliveryChallanManagement'));
const SalesInvoiceManagement = lazy(() => import('./components/SalesInvoiceManagement'));
const SalesReturnManagement = lazy(() => import('./components/SalesReturnManagement'));
const CreditDebitNoteManagement = lazy(() => import('./components/CreditDebitNoteManagement'));
const PurchaseOrderManagement = lazy(() => import('./components/PurchaseOrderManagement'));
const GoodsReceiptManagement = lazy(() => import('./components/GoodsReceiptManagement'));
const PurchaseInvoiceManagement = lazy(() => import('./components/PurchaseInvoiceManagement'));
const PurchaseReturnManagement = lazy(() => import('./components/PurchaseReturnManagement'));
const CustomerReceiptManagement = lazy(() => import('./components/CustomerReceiptManagement'));
const SupplierPaymentManagement = lazy(() => import('./components/SupplierPaymentManagement'));
const AccountingManagement = lazy(() => import('./components/AccountingManagement'));
const GstManagement = lazy(() => import('./components/GstManagement'));
const ReportsManagement = lazy(() => import('./components/ReportsManagement'));
const AnalysisManagement = lazy(() => import('./components/AnalysisManagement'));
const SyncCenter = lazy(() => import('./components/SyncCenter'));
const PayrollManagement = lazy(() => import('./components/PayrollManagement'));
const ViewCompany = lazy(() => import('./components/ViewCompany'));
const UserManagement = lazy(() => import('./components/UserManagement'));
const ConfigurationManagement = lazy(() => import('./components/ConfigurationManagement'));

// Helper component to consume NavigationContext and pass navigate to DashboardLayout
const DashboardWithNavigation: React.FC<{ currentView: string; children: React.ReactNode; onLogout: () => void }> = ({
  currentView,
  children,
  onLogout,
}) => {
  const { navigate } = useNavigation();
  return (
    <DashboardLayout currentView={currentView} onNavigate={navigate} onLogout={onLogout}>
      {children}
    </DashboardLayout>
  );
};

// A reset link (e.g. https://app.example.com/reset-password?token=...) must
// open the Reset Password screen regardless of whether the browser already
// holds an authenticated session elsewhere — read it once at startup.
function readResetTokenFromUrl(): string | null {
  try {
    return new URLSearchParams(window.location.search).get('token');
  } catch {
    return null;
  }
}

const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<AuthView>(AuthView.SIGN_IN);
  const [dashboardView, setDashboardView] = useState('Home');
  const [resetToken] = useState<string | null>(readResetTokenFromUrl);
  const { theme } = useTheme();
  const { isAuthenticated, authenticationLoading, logout, hasPermission } = useAuth();

  // Handle Theme Application
  useEffect(() => {
    const root = window.document.documentElement;
    // Force light mode for unauthenticated users (SignIn/SignUp)
    // Use user preference (theme) only when authenticated
    const targetTheme = isAuthenticated ? theme : 'light';

    root.classList.remove('light', 'dark');
    root.classList.add(targetTheme);
  }, [isAuthenticated, theme]);

  if (resetToken) {
    return (
      <ToastProvider>
        <Layout currentView={AuthView.RESET_PASSWORD}>
          <ResetPassword
            token={resetToken}
            onChangeView={(view) => {
              // Once the user leaves the reset flow, drop the token from the
              // visible URL so a stale/consumed token doesn't linger in
              // browser history for this tab.
              window.history.replaceState({}, '', window.location.pathname);
              setCurrentView(view);
            }}
          />
        </Layout>
      </ToastProvider>
    );
  }

  if (authenticationLoading) {
    return (
      <div className="min-h-screen w-full flex items-center justify-center bg-white dark:bg-gray-950">
        <LoadingState label="Loading…" />
      </div>
    );
  }

  const authScreens = (
    <ToastProvider>
      <Layout currentView={currentView}>
        {currentView === AuthView.SIGN_IN && (
          <SignIn onChangeView={setCurrentView} onLoginSuccess={() => setDashboardView('Home')} />
        )}
        {currentView === AuthView.SIGN_UP && <SignUp onChangeView={setCurrentView} />}
        {currentView === AuthView.FORGOT_PASSWORD && <ForgotPassword onChangeView={setCurrentView} />}
      </Layout>
    </ToastProvider>
  );

  return (
    <ProtectedRoute fallback={authScreens}>
      <ToastProvider>
        <NavigationProvider onNavigateInternal={setDashboardView}>
          <DashboardWithNavigation currentView={dashboardView} onLogout={logout}>
            {/* RBAC Alignment Phase: single choke-point route guard. Hiding
                a Sidebar link was never sufficient authorization on its own
                (every dashboardView branch below used to render
                unconditionally once merely authenticated) — this checks the
                SAME permission codes Sidebar.tsx uses to decide nav
                visibility, so nav and route access can never disagree. */}
            {!isViewAuthorized(dashboardView, hasPermission) ? (
              <AccessDenied onGoHome={() => setDashboardView('Home')} />
            ) : (
              <Suspense fallback={<LoadingState label="Loading…" />}>
            {dashboardView === 'Home' && <Home />}
            {dashboardView === 'Customers' && <CustomerManagement />}
            {dashboardView === 'Suppliers' && <SupplierManagement />}
            {dashboardView === 'Products' && <ProductManagement />}
            {dashboardView === 'Inventory' && <InventoryManagement />}
            {dashboardView === 'Estimates' && <EstimateManagement />}
            {dashboardView === 'Sales Orders' && <SalesOrderManagement />}
            {dashboardView === 'Delivery Challans' && <DeliveryChallanManagement />}
            {dashboardView === 'Sales Invoices' && <SalesInvoiceManagement />}
            {dashboardView === 'Sales Returns' && <SalesReturnManagement />}
            {dashboardView === 'Credit/Debit Notes' && <CreditDebitNoteManagement />}
            {dashboardView === 'Purchase Orders' && <PurchaseOrderManagement />}
            {dashboardView === 'Goods Receipts' && <GoodsReceiptManagement />}
            {dashboardView === 'Purchase Invoices' && <PurchaseInvoiceManagement />}
            {dashboardView === 'Purchase Returns' && <PurchaseReturnManagement />}
            {dashboardView === 'Customer Receipts' && <CustomerReceiptManagement />}
            {dashboardView === 'Supplier Payments' && <SupplierPaymentManagement />}
            {dashboardView === 'Accounting' && <AccountingManagement />}
            {dashboardView === 'GST Filing' && <GstManagement />}
            {dashboardView === 'Reports' && <ReportsManagement />}
            {dashboardView === 'Analysis' && <AnalysisManagement />}
            {dashboardView === 'Sync Center' && <SyncCenter />}
            {dashboardView === 'Payroll' && <PayrollManagement />}
            {dashboardView === 'View Company' && <ViewCompany />}
            {dashboardView === 'Users' && <UserManagement />}
            {dashboardView === 'Configuration' && <ConfigurationManagement />}
            {/* Fallback for other routes not implemented yet */}
            {dashboardView !== 'Home' && dashboardView !== 'Customers' && dashboardView !== 'Suppliers' && dashboardView !== 'Products' && dashboardView !== 'Inventory' && dashboardView !== 'Estimates' && dashboardView !== 'Sales Orders' && dashboardView !== 'Delivery Challans' && dashboardView !== 'Sales Invoices' && dashboardView !== 'Sales Returns' && dashboardView !== 'Credit/Debit Notes' && dashboardView !== 'Purchase Orders' && dashboardView !== 'Goods Receipts' && dashboardView !== 'Purchase Invoices' && dashboardView !== 'Purchase Returns' && dashboardView !== 'Customer Receipts' && dashboardView !== 'Supplier Payments' && dashboardView !== 'Accounting' && dashboardView !== 'GST Filing' && dashboardView !== 'Reports' && dashboardView !== 'Analysis' && dashboardView !== 'Sync Center' && dashboardView !== 'Payroll' && dashboardView !== 'View Company' && dashboardView !== 'Users' && dashboardView !== 'Configuration' && (
              <div className="p-8 text-center text-gray-500">
                  <h2 className="text-xl font-semibold">Page Under Construction</h2>
                  <p>You navigated to: {dashboardView}</p>
              </div>
            )}
              </Suspense>
            )}
          </DashboardWithNavigation>
        </NavigationProvider>
      </ToastProvider>
    </ProtectedRoute>
  );
};

export default App;
