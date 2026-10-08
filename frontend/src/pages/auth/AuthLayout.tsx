import type { ReactNode } from 'react';
import { Box, Stack, Typography } from '@mui/material';
import ShieldIcon from '@mui/icons-material/VerifiedUserOutlined';
import InventoryIcon from '@mui/icons-material/Inventory2Outlined';
import MailIcon from '@mui/icons-material/MarkEmailReadOutlined';
import { brand } from '../../theme';

const FEATURES = [
  { icon: <InventoryIcon fontSize="small" />, text: 'Orders checked against live stock' },
  { icon: <MailIcon fontSize="small" />, text: 'Manager approvals with email notifications' },
  { icon: <ShieldIcon fontSize="small" />, text: 'Two-step sign-in with one-time codes' },
];

/** Decorative preview of the dashboard, echoing the product inside. Hidden from screen readers. */
function PreviewCard() {
  return (
    <Box
      aria-hidden
      sx={{
        bgcolor: '#ffffff',
        color: brand.ink,
        borderRadius: 3,
        p: 2.5,
        width: 300,
        boxShadow: '0 24px 48px rgba(4, 47, 42, 0.28)',
        transform: 'rotate(-2deg)',
      }}
    >
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        Today&apos;s revenue
      </Typography>
      <Stack direction="row" alignItems="flex-end" justifyContent="space-between" sx={{ mt: 1 }}>
        <Box>
          <Typography sx={{ fontSize: 28, fontWeight: 700, lineHeight: 1 }}>₹ 2.4L</Typography>
          <Box
            component="span"
            sx={{
              display: 'inline-block',
              mt: 1,
              px: 0.75,
              py: 0.25,
              borderRadius: 1,
              fontSize: 12,
              fontWeight: 700,
              bgcolor: brand.successSoft,
              color: brand.tealDark,
            }}
          >
            ↗ 14%
          </Box>
        </Box>
        <svg width="120" height="48" viewBox="0 0 120 48">
          <path
            d="M0 30 C 15 10, 25 8, 40 24 S 65 44, 80 30 S 105 6, 120 12 L120 48 L0 48 Z"
            fill="#16a08f"
            opacity="0.12"
          />
          <path
            d="M0 30 C 15 10, 25 8, 40 24 S 65 44, 80 30 S 105 6, 120 12"
            fill="none"
            stroke="#16a08f"
            strokeWidth="2.5"
          />
        </svg>
      </Stack>
    </Box>
  );
}

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '5fr 6fr' } }}>
      <Box
        component="aside"
        aria-label="About SIMS"
        sx={{
          display: { xs: 'none', lg: 'flex' },
          flexDirection: 'column',
          justifyContent: 'space-between',
          p: 6,
          color: '#e9f6f3',
          background: `radial-gradient(1200px 600px at -10% -10%, #19a594 0%, transparent 60%),
                       radial-gradient(900px 600px at 110% 110%, #0a5d54 0%, transparent 60%),
                       linear-gradient(160deg, #0f8b7d 0%, #0b6e63 100%)`,
        }}
      >
        <Stack direction="row" spacing={1.5} alignItems="center">
          <Box
            component="img"
            src="/favicon.svg"
            alt=""
            sx={{ width: 40, height: 40, borderRadius: 2, outline: '2px solid rgba(255,255,255,.25)' }}
          />
          <Box>
            <Typography sx={{ color: '#fff', fontWeight: 700, fontSize: 18, lineHeight: 1.1 }}>SIMS</Typography>
            <Typography variant="caption" sx={{ color: 'rgba(233,246,243,.75)' }}>
              Sales & Inventory
            </Typography>
          </Box>
        </Stack>

        <Box>
          <Typography
            component="p"
            sx={{ color: '#fff', fontWeight: 700, fontSize: 36, lineHeight: 1.15, maxWidth: 460 }}
          >
            Sales, stock and approvals in one calm place.
          </Typography>
          <Stack spacing={1.5} sx={{ mt: 4 }}>
            {FEATURES.map((feature) => (
              <Stack key={feature.text} direction="row" spacing={1.5} alignItems="center">
                <Box
                  sx={{
                    width: 32,
                    height: 32,
                    borderRadius: 2,
                    display: 'grid',
                    placeItems: 'center',
                    bgcolor: 'rgba(255,255,255,.14)',
                  }}
                >
                  {feature.icon}
                </Box>
                <Typography sx={{ color: '#e9f6f3' }}>{feature.text}</Typography>
              </Stack>
            ))}
          </Stack>
          <Box sx={{ mt: 6, ml: 1 }}>
            <PreviewCard />
          </Box>
        </Box>

        <Typography variant="caption" sx={{ color: 'rgba(233,246,243,.7)' }}>
          © {new Date().getFullYear()} SIMS · Sales & Inventory Management
        </Typography>
      </Box>

      <Box
        component="main"
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          px: { xs: 2, sm: 4 },
          py: { xs: 4, sm: 6 },
          bgcolor: '#ffffff',
        }}
      >
        <Box sx={{ width: '100%', maxWidth: 420 }}>
          <Stack direction="row" spacing={1.25} alignItems="center" sx={{ mb: 4, display: { lg: 'none' } }}>
            <Box component="img" src="/favicon.svg" alt="" sx={{ width: 36, height: 36 }} />
            <Typography sx={{ fontWeight: 700, color: brand.teal }}>SIMS</Typography>
          </Stack>
          {children}
        </Box>
      </Box>
    </Box>
  );
}

export function AuthHeading({ title, subtitle }: { title: string; subtitle?: ReactNode }) {
  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="h4" sx={{ fontSize: { xs: '1.6rem', sm: '1.85rem' } }}>
        {title}
      </Typography>
      {subtitle && (
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          {subtitle}
        </Typography>
      )}
    </Box>
  );
}
