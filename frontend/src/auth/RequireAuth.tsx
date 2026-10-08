import { Box, CircularProgress } from '@mui/material';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import type { Permission, Role } from '../types';
import { useAuth } from './AuthContext';

/**
 * Route guard: requires a signed-in user, optionally with one of the given roles or a permission.
 * This is navigation only - every API call is authorised again on the server.
 */
export function RequireAuth({ roles, permission }: { roles?: Role[]; permission?: Permission }) {
  const { user, initializing, signedOut, can } = useAuth();
  const location = useLocation();

  if (initializing) {
    return (
      <Box sx={{ display: 'grid', placeItems: 'center', height: '100vh' }}>
        <CircularProgress aria-label="Loading" />
      </Box>
    );
  }
  if (!user) {
    // After a deliberate sign-out the next person starts on the dashboard, not the previous user's page.
    return <Navigate to="/login" replace state={signedOut ? undefined : { from: location.pathname }} />;
  }
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />;
  if (permission && !can(permission)) return <Navigate to="/" replace />;
  return <Outlet />;
}
