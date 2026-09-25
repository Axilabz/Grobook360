import React, { useState, useEffect } from 'react';
import Layout from './components/Layout';
import SignIn from './components/SignIn';
import SignUp from './components/SignUp';
import ForgotPassword from './components/ForgotPassword';
import ResetPassword from './components/ResetPassword';
import DashboardLayout from './components/DashboardLayout';
import Home from './components/Home';
import CustomerManagement from './components/CustomerManagement';
import SupplierManagement from './components/SupplierManagement';
import ProductManagement from './components/ProductManagement';
import InventoryManagement from './components/InventoryManagement';
import EstimateManagement from './components/EstimateManagement';
import SalesOrderManagement from './components/SalesOrderManagement';
import DeliveryChallanManagement from './components/DeliveryChallanManagement';
import SalesInvoiceManagement from './components/SalesInvoiceManagement';
import SalesReturnManagement from './components/SalesReturnManagement';
import CreditDebitNoteManagement from './components/CreditDebitNoteManagement';
import PurchaseOrderManagement from './components/PurchaseOrderManagement';
import GoodsReceiptManagement from './components/GoodsReceiptManagement';
import PurchaseInvoiceManagement from './components/PurchaseInvoiceManagement';
import PurchaseReturnManagement from './components/PurchaseReturnManagement';
import CustomerReceiptManagement from './components/CustomerReceiptManagement';
import SupplierPaymentManagement from './components/SupplierPaymentManagement';
import AccountingManagement from './components/AccountingManagement';
import GstManagement from './components/GstManagement';
import ReportsManagement from './components/ReportsManagement';
import SyncCenter from './components/SyncCenter';
import PayrollManagement from './components/PayrollManagement';
import ViewCompany from './components/ViewCompany';
import UserManagement from './components/UserManagement';
import ConfigurationManagement from './components/ConfigurationManagement';
import { AuthView } from './types';
import { ToastProvider } from './context/ToastContext';
import { useTheme } from './context/ThemeContext';
import { useAuth } from './context/AuthContext';
import { NavigationProvider, useNavigation } from './context/NavigationContext';
import ProtectedRoute from './shared/ProtectedRoute';
import LoadingState from './shared/LoadingState';

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
  const { isAuthenticated, authenticationLoading, logout } = useAuth();

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
            {dashboardView === 'Sync Center' && <SyncCenter />}
            {dashboardView === 'Payroll' && <PayrollManagement />}
            {dashboardView === 'View Company' && <ViewCompany />}
            {dashboardView === 'Users' && <UserManagement />}
            {dashboardView === 'Configuration' && <ConfigurationManagement />}
            {/* Fallback for other routes not implemented yet */}
            {dashboardView !== 'Home' && dashboardView !== 'Customers' && dashboardView !== 'Suppliers' && dashboardView !== 'Products' && dashboardView !== 'Inventory' && dashboardView !== 'Estimates' && dashboardView !== 'Sales Orders' && dashboardView !== 'Delivery Challans' && dashboardView !== 'Sales Invoices' && dashboardView !== 'Sales Returns' && dashboardView !== 'Credit/Debit Notes' && dashboardView !== 'Purchase Orders' && dashboardView !== 'Goods Receipts' && dashboardView !== 'Purchase Invoices' && dashboardView !== 'Purchase Returns' && dashboardView !== 'Customer Receipts' && dashboardView !== 'Supplier Payments' && dashboardView !== 'Accounting' && dashboardView !== 'GST Filing' && dashboardView !== 'Reports' && dashboardView !== 'Sync Center' && dashboardView !== 'Payroll' && dashboardView !== 'View Company' && dashboardView !== 'Users' && dashboardView !== 'Configuration' && (
              <div className="p-8 text-center text-gray-500">
                  <h2 className="text-xl font-semibold">Page Under Construction</h2>
                  <p>You navigated to: {dashboardView}</p>
              </div>
            )}
          </DashboardWithNavigation>
        </NavigationProvider>
      </ToastProvider>
    </ProtectedRoute>
  );
};

export default App;
