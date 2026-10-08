import type { ReactNode } from 'react';
import { Box, Paper, Skeleton, Stack, Typography } from '@mui/material';
import { visuallyHidden } from '@mui/utils';
import UpIcon from '@mui/icons-material/NorthEast';
import DownIcon from '@mui/icons-material/SouthEast';
import FlatIcon from '@mui/icons-material/East';
import { brand } from '../theme';
import { Sparkline } from './charts';

/** Change versus the previous period: green when up, red when down (the arrow and text carry it too). */
export function DeltaChip({ change, context = 'vs previous period' }: { change: number | null; context?: string }) {
  if (change === null || !Number.isFinite(change)) return null;
  const up = change >= 0.5;
  const down = change <= -0.5;
  const tone = up
    ? { bg: brand.successSoft, fg: '#0b6e63' }
    : down
      ? { bg: brand.dangerSoft, fg: '#b93535' }
      : { bg: '#f1f3f3', fg: brand.ink2 };
  const magnitude = Math.abs(change);
  const text = `${magnitude >= 10 ? magnitude.toFixed(0) : magnitude.toFixed(1)}%`;
  const Icon = up ? UpIcon : down ? DownIcon : FlatIcon;
  return (
    <Box
      component="span"
      title={`${text} ${context}`}
      sx={{
        position: 'relative', // contains the visually hidden text
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0.25,
        px: 0.75,
        py: 0.25,
        borderRadius: 1.5,
        bgcolor: tone.bg,
        color: tone.fg,
        fontSize: 12,
        fontWeight: 700,
        whiteSpace: 'nowrap',
      }}
    >
      <Box component="span" sx={visuallyHidden}>
        {up ? 'Up ' : down ? 'Down ' : 'No change, '}
      </Box>
      {text}
      <Icon sx={{ fontSize: 13 }} aria-hidden />
      <Box component="span" sx={visuallyHidden}>
        {` ${context}`}
      </Box>
    </Box>
  );
}

interface Props {
  label: string;
  value: ReactNode;
  change?: number | null;
  caption?: ReactNode;
  trend?: number[];
  icon?: ReactNode;
  badge?: ReactNode;
  action?: ReactNode;
  loading?: boolean;
}

export function KpiCard({ label, value, change, caption, trend, icon, badge, action, loading }: Props) {
  return (
    <Paper
      component="section"
      aria-label={label}
      sx={{ p: 2.5, height: '100%', display: 'flex', flexDirection: 'column', gap: 1.5 }}
    >
      <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1} sx={{ minHeight: 24 }}>
        <Typography variant="body2" sx={{ fontWeight: 600, color: brand.ink }}>
          {label}
        </Typography>
        {action}
      </Stack>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-end" spacing={1.5} sx={{ flex: 1 }}>
        <Box sx={{ minWidth: 0 }}>
          {loading ? (
            <Skeleton width={110} height={40} />
          ) : (
            <Stack direction="row" alignItems="center" spacing={1} useFlexGap flexWrap="wrap">
              <Typography variant="h5" component="p" sx={{ fontSize: { xs: '1.6rem', lg: '1.45rem', xl: '1.65rem' } }}>
                {value}
              </Typography>
              {change !== undefined && <DeltaChip change={change} />}
              {badge}
            </Stack>
          )}
          {caption && (
            <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 0.5 }}>
              {loading ? <Skeleton width={140} /> : caption}
            </Typography>
          )}
        </Box>
        {!loading && trend && trend.length > 1 ? (
          <Sparkline data={trend} width={84} />
        ) : icon ? (
          <Box
            aria-hidden
            sx={{
              width: 44,
              height: 44,
              borderRadius: 2.5,
              display: 'grid',
              placeItems: 'center',
              color: brand.teal,
              bgcolor: brand.tealSoft,
              flexShrink: 0,
            }}
          >
            {icon}
          </Box>
        ) : null}
      </Stack>
    </Paper>
  );
}
