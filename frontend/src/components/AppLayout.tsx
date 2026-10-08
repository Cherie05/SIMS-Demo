import { Suspense, useMemo, useState, type MouseEvent, type ReactNode } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  AppBar,
  Avatar,
  Box,
  ButtonBase,
  Divider,
  Drawer,
  IconButton,
  LinearProgress,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Stack,
  Toolbar,
  Typography,
} from '@mui/material';
import { visuallyHidden } from '@mui/utils';
import DashboardIcon from '@mui/icons-material/GridViewOutlined';
import NewOrderIcon from '@mui/icons-material/AddCircleOutlineOutlined';
import ReceiptIcon from '@mui/icons-material/ReceiptLongOutlined';
import ApprovalIcon from '@mui/icons-material/FactCheckOutlined';
import InventoryIcon from '@mui/icons-material/Inventory2Outlined';
import PeopleIcon from '@mui/icons-material/PeopleAltOutlined';
import LedgerIcon from '@mui/icons-material/SwapVertOutlined';
import SettingsIcon from '@mui/icons-material/SettingsOutlined';
import AuditIcon from '@mui/icons-material/HistoryEduOutlined';
import SystemIcon from '@mui/icons-material/MonitorHeartOutlined';
import ShieldIcon from '@mui/icons-material/ShieldOutlined';
import HelpIcon from '@mui/icons-material/HelpOutlineOutlined';
import KeyboardIcon from '@mui/icons-material/KeyboardOutlined';
import LogoutIcon from '@mui/icons-material/LogoutOutlined';
import ExpandIcon from '@mui/icons-material/UnfoldMoreOutlined';
import MenuIcon from '@mui/icons-material/Menu';
import { useAuth } from '../auth/AuthContext';
import { approvalsApi } from '../api/endpoints';
import { brand } from '../theme';
import { useAuthConfig } from '../pages/auth/useAuthConfig';
import type { Permission } from '../types';
import { humanize } from '../utils/format';
import { ErrorBoundary } from './ErrorBoundary';
import { HelpDialog } from './HelpDialog';
import { IdleTimeout } from './IdleTimeout';
import { Kbd } from './Kbd';
import { OfflineBanner } from './OfflineBanner';
import { readShortcutsEnabled, useGlobalShortcuts, writeShortcutsEnabled } from './shortcuts';

const DRAWER_WIDTH = 264;

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  shortcut: string;
  /** Shown only to users holding this permission (the API enforces it regardless). */
  permission?: Permission;
  badge?: 'approvals';
}

const SECTIONS: { title?: string; items: NavItem[] }[] = [
  {
    items: [
      { to: '/', label: 'Dashboard', icon: <DashboardIcon />, shortcut: 'D' },
      { to: '/orders/new', label: 'New order', icon: <NewOrderIcon />, shortcut: 'N' },
      { to: '/orders', label: 'Sales orders', icon: <ReceiptIcon />, shortcut: 'O' },
      {
        to: '/approvals',
        label: 'Approvals',
        icon: <ApprovalIcon />,
        shortcut: 'A',
        permission: 'order:approve',
        badge: 'approvals',
      },
    ],
  },
  {
    title: 'Inventory',
    items: [
      { to: '/products', label: 'Products', icon: <InventoryIcon />, shortcut: 'P' },
      { to: '/customers', label: 'Customers', icon: <PeopleIcon />, shortcut: 'C' },
      { to: '/inventory', label: 'Stock ledger', icon: <LedgerIcon />, shortcut: 'L' },
    ],
  },
  {
    title: 'Administration',
    items: [
      { to: '/audit', label: 'Audit log', icon: <AuditIcon />, shortcut: 'U', permission: 'audit:read' },
      { to: '/system', label: 'System', icon: <SystemIcon />, shortcut: 'Y', permission: 'system:read' },
    ],
  },
];
const SETTINGS: NavItem = {
  to: '/settings',
  label: 'Settings',
  icon: <SettingsIcon />,
  shortcut: 'S',
  permission: 'settings:write',
};

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join('');

const itemSx = {
  borderRadius: 2,
  mb: 0.5,
  px: 1.25,
  py: 0.875,
  gap: 0.5,
  color: brand.ink2,
  '& .MuiListItemIcon-root': { minWidth: 34, color: brand.ink2 },
  '& .MuiSvgIcon-root': { fontSize: 20 },
  '&:hover': { bgcolor: brand.hover },
  '&.active': {
    bgcolor: brand.sidebarActive,
    color: brand.ink,
    '& .MuiListItemIcon-root': { color: brand.ink },
    '& .nav-label': { fontWeight: 600 },
  },
};

const labelProps = { primary: { className: 'nav-label', fontSize: 14, fontWeight: 500 } };

function CountBadge({ count }: { count: number }) {
  return (
    <Box
      component="span"
      sx={{
        px: 0.75,
        minWidth: 20,
        height: 20,
        borderRadius: 10,
        bgcolor: brand.badge,
        color: '#ffffff',
        fontSize: 11,
        fontWeight: 700,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {count > 99 ? '99+' : count}
      <Box component="span" sx={visuallyHidden}>
        pending
      </Box>
    </Box>
  );
}

export function AppLayout() {
  const { user, logout, can } = useAuth();
  const authConfig = useAuthConfig();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);
  const [shortcutsOn, setShortcutsOn] = useState(readShortcutsEnabled);
  const isApprover = can('order:approve');

  const { data: pending } = useQuery({
    queryKey: ['approvals', 'pending-count'],
    queryFn: () => approvalsApi.list({ status: 'PENDING', page_size: 1 }),
    enabled: isApprover,
    refetchInterval: 30_000,
  });

  const navItems = useMemo(
    () => [...SECTIONS.flatMap((s) => s.items), SETTINGS].filter((item) => !item.permission || can(item.permission)),
    [can],
  );
  const shortcutActions = useMemo(() => {
    const actions: Record<string, () => void> = { '?': () => setHelpOpen(true) };
    for (const item of navItems) actions[item.shortcut.toLowerCase()] = () => navigate(item.to);
    return actions;
  }, [navItems, navigate]);
  useGlobalShortcuts(shortcutActions, shortcutsOn);

  const isVisible = (item: NavItem) => navItems.includes(item);

  const renderItem = (item: NavItem) => (
    <ListItemButton
      key={item.to}
      component={NavLink}
      to={item.to}
      end={item.to === '/' || item.to === '/orders'}
      onClick={() => setMobileOpen(false)}
      sx={itemSx}
    >
      <ListItemIcon>{item.icon}</ListItemIcon>
      <ListItemText primary={item.label} slotProps={labelProps} />
      {item.badge === 'approvals' && Boolean(pending?.total) && <CountBadge count={pending!.total} />}
      {shortcutsOn && (
        <Kbd hidden hideOnSmall>
          {item.shortcut}
        </Kbd>
      )}
    </ListItemButton>
  );

  const openMenu = (event: MouseEvent<HTMLElement>) => setMenuAnchor(event.currentTarget);

  const sidebar = (
    <Box
      component="aside"
      aria-label="Sidebar"
      sx={{ display: 'flex', flexDirection: 'column', height: '100%', bgcolor: brand.sidebar, p: 2 }}
    >
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ px: 1, py: 1, mb: 2.5 }}>
        <Box component="img" src="/favicon.svg" alt="" sx={{ width: 38, height: 38, borderRadius: 2.5 }} />
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontWeight: 700, color: brand.teal, lineHeight: 1.2 }}>SIMS</Typography>
          <Typography variant="caption" sx={{ color: brand.muted }}>
            Sales & Inventory
          </Typography>
        </Box>
      </Stack>

      <Box component="nav" aria-label="Main navigation" sx={{ flex: 1, overflowY: 'auto', mx: -0.5, px: 0.5 }}>
        {SECTIONS.map((section) => {
          const items = section.items.filter(isVisible);
          if (!items.length) return null;
          return (
            <Box key={section.title ?? 'main'} sx={{ mb: 2 }}>
              {section.title && (
                <Typography
                  variant="caption"
                  sx={{ display: 'block', px: 1.25, mb: 0.75, color: brand.muted, fontWeight: 600, letterSpacing: 0.4 }}
                >
                  {section.title.toUpperCase()}
                </Typography>
              )}
              <List component="div" disablePadding>
                {items.map(renderItem)}
              </List>
            </Box>
          );
        })}
      </Box>

      <List component="div" disablePadding>
        <ListItemButton onClick={() => setHelpOpen(true)} sx={itemSx}>
          <ListItemIcon>
            <HelpIcon />
          </ListItemIcon>
          <ListItemText primary="Help" slotProps={labelProps} />
          {shortcutsOn && (
            <Kbd hidden hideOnSmall>
              ?
            </Kbd>
          )}
        </ListItemButton>
        {isVisible(SETTINGS) && renderItem(SETTINGS)}
      </List>
      <Divider sx={{ my: 1.5 }} />
      <ButtonBase
        onClick={openMenu}
        aria-haspopup="menu"
        sx={{
          width: '100%',
          p: 1,
          gap: 1.25,
          borderRadius: 2,
          justifyContent: 'flex-start',
          textAlign: 'left',
          '&:hover': { bgcolor: brand.hover },
        }}
      >
        <Avatar
          aria-hidden
          sx={{ width: 36, height: 36, bgcolor: brand.tealSoft, color: brand.tealDark, fontWeight: 700, fontSize: 14 }}
        >
          {initials(user?.name ?? '?')}
        </Avatar>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }} noWrap>
            {user?.name}
          </Typography>
          <Typography variant="caption" sx={{ color: brand.muted, display: 'block' }} noWrap>
            {user?.email}
          </Typography>
        </Box>
        <ExpandIcon fontSize="small" sx={{ color: brand.muted }} />
      </ButtonBase>
    </Box>
  );

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <AppBar
        position="fixed"
        color="inherit"
        sx={{ display: { md: 'none' }, bgcolor: '#ffffff', borderBottom: `1px solid ${brand.line}` }}
      >
        <Toolbar sx={{ gap: 1 }}>
          <IconButton edge="start" onClick={() => setMobileOpen(true)} aria-label="Open menu">
            <MenuIcon />
          </IconButton>
          <Box component="img" src="/favicon.svg" alt="" sx={{ width: 28, height: 28 }} />
          <Typography component="div" sx={{ fontWeight: 700, color: brand.teal, flex: 1 }}>
            SIMS
          </Typography>
          <IconButton
            onClick={openMenu}
            aria-label={`${initials(user?.name ?? '?')} account menu for ${user?.name}`}
            aria-haspopup="menu"
          >
            <Avatar
              aria-hidden
              sx={{
                width: 30,
                height: 30,
                bgcolor: brand.tealSoft,
                color: brand.tealDark,
                fontWeight: 700,
                fontSize: 13,
              }}
            >
              {initials(user?.name ?? '?')}
            </Avatar>
          </IconButton>
        </Toolbar>
      </AppBar>

      <Box sx={{ width: { md: DRAWER_WIDTH }, flexShrink: { md: 0 } }}>
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          ModalProps={{ keepMounted: true }}
          sx={{ display: { xs: 'block', md: 'none' }, '& .MuiDrawer-paper': { width: DRAWER_WIDTH } }}
        >
          {sidebar}
        </Drawer>
        <Drawer
          variant="permanent"
          open
          sx={{
            display: { xs: 'none', md: 'block' },
            '& .MuiDrawer-paper': { width: DRAWER_WIDTH, borderRight: `1px solid ${brand.line}` },
          }}
        >
          {sidebar}
        </Drawer>
      </Box>

      <Menu
        anchorEl={menuAnchor}
        open={Boolean(menuAnchor)}
        onClose={() => setMenuAnchor(null)}
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
        transformOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        slotProps={{ paper: { sx: { minWidth: 240 } } }}
      >
        <Box sx={{ px: 2, py: 1 }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {user?.name}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {humanize(user?.role ?? '')} · {user?.email}
          </Typography>
        </Box>
        <Divider />
        <MenuItem
          onClick={() => {
            setMenuAnchor(null);
            navigate('/account');
          }}
        >
          <ListItemIcon>
            <ShieldIcon fontSize="small" />
          </ListItemIcon>
          Account & security
        </MenuItem>
        <MenuItem
          onClick={() => {
            setMenuAnchor(null);
            setHelpOpen(true);
          }}
        >
          <ListItemIcon>
            <KeyboardIcon fontSize="small" />
          </ListItemIcon>
          Keyboard shortcuts
        </MenuItem>
        <MenuItem
          onClick={() => {
            setMenuAnchor(null);
            void logout();
          }}
        >
          <ListItemIcon>
            <LogoutIcon fontSize="small" />
          </ListItemIcon>
          Sign out
        </MenuItem>
      </Menu>

      <HelpDialog
        open={helpOpen}
        onClose={() => setHelpOpen(false)}
        shortcuts={navItems.map((item) => ({ key: item.shortcut, label: `Go to ${item.label.toLowerCase()}` }))}
        enabled={shortcutsOn}
        onToggle={(enabled) => {
          setShortcutsOn(enabled);
          writeShortcutsEnabled(enabled);
        }}
      />

      <IdleTimeout timeoutSeconds={authConfig.data?.session_idle_timeout_seconds ?? 3600} />
      <Box component="main" sx={{ flexGrow: 1, minWidth: 0, bgcolor: '#ffffff' }}>
        <Box sx={{ mt: { xs: 7, md: 0 } }}>
          <OfflineBanner />
        </Box>
        <Box sx={{ maxWidth: 1440, mx: 'auto', px: { xs: 2, sm: 3, lg: 5 }, py: { xs: 2.5, md: 4 } }}>
          {/* Page chunks load lazily; keep the navigation visible while they do. */}
          <ErrorBoundary resetKey={location.pathname}>
            <Suspense fallback={<LinearProgress sx={{ borderRadius: 1 }} />}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </Box>
      </Box>
    </Box>
  );
}
