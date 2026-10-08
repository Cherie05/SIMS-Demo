import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Box, LinearProgress } from '@mui/material';
import { RequireAuth } from './auth/RequireAuth';
import { AppLayout } from './components/AppLayout';
import LoginPage from './pages/auth/LoginPage';

// Pages are code-split so the first load only pulls what the current screen needs.
const SignupPage = lazy(() => import('./pages/auth/SignupPage'));
const ForgotPasswordPage = lazy(() => import('./pages/auth/ForgotPasswordPage'));
const AccountPage = lazy(() => import('./pages/account/AccountPage'));
const AuditLogPage = lazy(() => import('./pages/admin/AuditLogPage'));
const SystemPage = lazy(() => import('./pages/admin/SystemPage'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const ProductsPage = lazy(() => import('./pages/products/ProductsPage'));
const CustomersPage = lazy(() => import('./pages/customers/CustomersPage'));
const OrdersPage = lazy(() => import('./pages/orders/OrdersPage'));
const NewOrderPage = lazy(() => import('./pages/orders/NewOrderPage'));
const OrderDetailPage = lazy(() => import('./pages/orders/OrderDetailPage'));
const ApprovalsPage = lazy(() => import('./pages/approvals/ApprovalsPage'));
const InventoryPage = lazy(() => import('./pages/inventory/InventoryPage'));
const SettingsPage = lazy(() => import('./pages/settings/SettingsPage'));

const PageLoader = () => (
  <Box sx={{ position: 'fixed', top: 0, left: 0, right: 0, zIndex: 2000 }}>
    <LinearProgress />
  </Box>
);

export default function App() {
  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<AppLayout />}>
            <Route index element={<DashboardPage />} />
            <Route path="orders" element={<OrdersPage />} />
            <Route path="orders/new" element={<NewOrderPage />} />
            <Route path="orders/:orderId" element={<OrderDetailPage />} />
            <Route path="products" element={<ProductsPage />} />
            <Route path="customers" element={<CustomersPage />} />
            <Route path="inventory" element={<InventoryPage />} />
            <Route path="account" element={<AccountPage />} />
            <Route element={<RequireAuth permission="order:approve" />}>
              <Route path="approvals" element={<ApprovalsPage />} />
            </Route>
            <Route element={<RequireAuth permission="settings:write" />}>
              <Route path="settings" element={<SettingsPage />} />
            </Route>
            <Route element={<RequireAuth permission="audit:read" />}>
              <Route path="audit" element={<AuditLogPage />} />
            </Route>
            <Route element={<RequireAuth permission="system:read" />}>
              <Route path="system" element={<SystemPage />} />
            </Route>
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
