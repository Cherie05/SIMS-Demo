import { Box } from '@mui/material';
import type { ApprovalStatus, EmailStatus, InventoryTxnType, JobStatus, OrderStatus } from '../types';
import { humanize } from '../utils/format';

type Status =
  OrderStatus | ApprovalStatus | EmailStatus | InventoryTxnType | JobStatus | 'success' | 'failure' | 'denied';

// Soft, tinted pills: colour supports the label, it never replaces it.
const TONES = {
  success: { bg: '#e3f5f0', fg: '#0b6e63' },
  warning: { bg: '#fdf3e2', fg: '#94570a' },
  danger: { bg: '#fdeeee', fg: '#b93535' },
  info: { bg: '#eaf0fd', fg: '#3453ba' },
  violet: { bg: '#efeffd', fg: '#4e55b8' },
  neutral: { bg: '#f1f3f3', fg: '#56625f' },
};

const STATUS_TONE: Record<Status, keyof typeof TONES> = {
  PENDING_APPROVAL: 'warning',
  PENDING: 'warning',
  APPROVED: 'info',
  COMPLETED: 'success',
  REJECTED: 'danger',
  CANCELLED: 'neutral',
  SENT: 'success',
  FAILED: 'danger',
  SKIPPED: 'neutral',
  QUEUED: 'info',
  OPENING: 'neutral',
  SALE: 'violet',
  RESTOCK: 'success',
  ADJUSTMENT: 'warning',
  RUNNING: 'info',
  RETRY: 'warning',
  DONE: 'success',
  DEAD: 'danger',
  EXPIRED: 'neutral',
  success: 'success',
  failure: 'danger',
  denied: 'warning',
};

export function StatusChip({ status, size = 'small' }: { status: Status | string; size?: 'small' | 'medium' }) {
  // Unknown values (a newer API than this page) still render, in a neutral tone.
  const tone = TONES[STATUS_TONE[status as Status] ?? 'neutral'];
  return (
    <Box
      component="span"
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0.75,
        px: size === 'medium' ? 1.25 : 1,
        py: size === 'medium' ? 0.5 : 0.25,
        borderRadius: 1.5,
        bgcolor: tone.bg,
        color: tone.fg,
        fontSize: size === 'medium' ? 13 : 12,
        fontWeight: 600,
        lineHeight: 1.5,
        whiteSpace: 'nowrap',
      }}
    >
      <Box component="span" aria-hidden sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: 'currentColor' }} />
      {humanize(status)}
    </Box>
  );
}
