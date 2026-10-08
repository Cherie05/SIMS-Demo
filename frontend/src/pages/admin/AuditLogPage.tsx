import { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useSnackbar } from 'notistack';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import DownloadIcon from '@mui/icons-material/FileDownloadOutlined';
import { getErrorMessage } from '../../api/client';
import { auditApi, type AuditQuery } from '../../api/endpoints';
import { DataTable, type Column } from '../../components/DataTable';
import { PageHeader } from '../../components/PageHeader';
import { StatusChip } from '../../components/StatusChip';
import { useDebounce } from '../../hooks/useDebounce';
import type { AuditLogEntry } from '../../types';
import { formatDateTime, humanize } from '../../utils/format';

const OUTCOMES = ['', 'success', 'failure', 'denied'] as const;
const QUICK_FILTERS = [
  { label: 'Sign-ins', action: 'auth.login' },
  { label: 'Security', action: 'auth.' },
  { label: 'Orders', action: 'order.' },
  { label: 'Users', action: 'user.' },
  { label: 'Settings', action: 'settings.' },
  { label: 'Denied', action: 'access.denied' },
];

const mono = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', fontSize: 13 };

function Json({ value }: { value: unknown }) {
  return (
    <Box
      component="pre"
      sx={{ ...mono, m: 0, p: 1.5, bgcolor: 'grey.50', borderRadius: 1, overflowX: 'auto', whiteSpace: 'pre-wrap' }}
    >
      {JSON.stringify(value, null, 2)}
    </Box>
  );
}

export default function AuditLogPage() {
  const { enqueueSnackbar } = useSnackbar();
  const [action, setAction] = useState('');
  const [outcome, setOutcome] = useState<(typeof OUTCOMES)[number]>('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(25);
  const [selected, setSelected] = useState<AuditLogEntry | null>(null);
  const [exporting, setExporting] = useState(false);
  const debouncedAction = useDebounce(action, 300);

  const filters: Omit<AuditQuery, 'page' | 'page_size'> = {
    action: debouncedAction.trim() || undefined,
    outcome,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  };
  const params: AuditQuery = { ...filters, page: page + 1, page_size: pageSize };
  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ['audit-logs', params],
    queryFn: ({ signal }) => auditApi.list(params, signal),
    placeholderData: keepPreviousData,
  });

  const exportCsv = async () => {
    setExporting(true);
    try {
      const { blob, filename } = await auditApi.exportCsv(filters);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      enqueueSnackbar(getErrorMessage(err), { variant: 'error' });
    } finally {
      setExporting(false);
    }
  };

  const columns: Column<AuditLogEntry>[] = [
    { key: 'time', header: 'When', render: (e) => formatDateTime(e.occurred_at), width: 170 },
    {
      key: 'actor',
      header: 'Who',
      render: (e) => (
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" noWrap>
            {e.actor_email ?? 'anonymous'}
          </Typography>
          {e.actor_role && (
            <Typography variant="caption" color="text.secondary">
              {humanize(e.actor_role)}
            </Typography>
          )}
        </Box>
      ),
    },
    {
      key: 'action',
      header: 'Action',
      render: (e) => (
        <Box component="span" sx={mono}>
          {e.action}
        </Box>
      ),
    },
    { key: 'outcome', header: 'Outcome', render: (e) => <StatusChip status={e.outcome} /> },
    {
      key: 'entity',
      header: 'Target',
      hideOnMobile: true,
      render: (e) =>
        e.entity_type ? `${humanize(e.entity_type)} ${e.entity_id ? `#${e.entity_id.slice(0, 12)}` : ''}` : '—',
    },
    { key: 'ip', header: 'IP', hideOnMobile: true, render: (e) => e.ip_address ?? '—' },
  ];

  return (
    <Box>
      <PageHeader
        title="Audit log"
        subtitle="Every security event and business change: who, what, when, from where, and what changed. Entries can't be edited or deleted."
        actions={
          <Button variant="outlined" startIcon={<DownloadIcon />} onClick={() => void exportCsv()} disabled={exporting}>
            {exporting ? 'Preparing…' : 'Export CSV'}
          </Button>
        }
      />
      <DataTable
        label="Audit log entries"
        rows={data?.items}
        columns={columns}
        rowKey={(e) => e.id}
        loading={isFetching}
        error={error ? getErrorMessage(error) : undefined}
        onRetry={() => void refetch()}
        total={data?.total}
        page={page}
        pageSize={pageSize}
        onPageChange={setPage}
        onPageSizeChange={(size) => {
          setPageSize(size);
          setPage(0);
        }}
        onRowClick={setSelected}
        emptyText="No entries match these filters"
        toolbar={
          <Stack spacing={1.5}>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
              <TextField
                size="small"
                label="Action starts with"
                placeholder="e.g. order.approved"
                value={action}
                onChange={(e) => {
                  setAction(e.target.value);
                  setPage(0);
                }}
                sx={{ minWidth: 220 }}
              />
              <TextField
                select
                size="small"
                label="Outcome"
                value={outcome}
                onChange={(e) => {
                  setOutcome(e.target.value as (typeof OUTCOMES)[number]);
                  setPage(0);
                }}
                sx={{ minWidth: 140 }}
              >
                {OUTCOMES.map((o) => (
                  <MenuItem key={o || 'any'} value={o}>
                    {o ? humanize(o) : 'Any'}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                size="small"
                type="date"
                label="From"
                value={dateFrom}
                onChange={(e) => {
                  setDateFrom(e.target.value);
                  setPage(0);
                }}
                slotProps={{ inputLabel: { shrink: true }, htmlInput: { max: dateTo || undefined } }}
              />
              <TextField
                size="small"
                type="date"
                label="To"
                value={dateTo}
                onChange={(e) => {
                  setDateTo(e.target.value);
                  setPage(0);
                }}
                slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: dateFrom || undefined } }}
              />
            </Stack>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
              {QUICK_FILTERS.map((f) => (
                <Button
                  key={f.label}
                  size="small"
                  variant={action === f.action ? 'contained' : 'outlined'}
                  onClick={() => {
                    setAction(action === f.action ? '' : f.action);
                    setPage(0);
                  }}
                >
                  {f.label}
                </Button>
              ))}
            </Stack>
          </Stack>
        }
      />

      <Dialog open={Boolean(selected)} onClose={() => setSelected(null)} maxWidth="md" fullWidth>
        {selected && (
          <>
            <DialogTitle sx={mono}>{selected.action}</DialogTitle>
            <DialogContent>
              <Stack spacing={1} sx={{ mb: 2 }}>
                <Typography variant="body2">
                  <strong>When:</strong> {formatDateTime(selected.occurred_at)} · <strong>Outcome:</strong>{' '}
                  {humanize(selected.outcome)}
                </Typography>
                <Typography variant="body2">
                  <strong>Who:</strong> {selected.actor_email ?? 'anonymous'}
                  {selected.actor_role ? ` (${humanize(selected.actor_role)})` : ''} from{' '}
                  {selected.ip_address ?? 'unknown IP'}
                </Typography>
                <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>
                  <strong>Device:</strong> {selected.user_agent ?? '—'}
                </Typography>
                <Typography variant="body2">
                  <strong>Request id:</strong>{' '}
                  <Box component="span" sx={mono}>
                    {selected.request_id ?? '—'}
                  </Box>
                </Typography>
              </Stack>
              {selected.changes && (
                <>
                  <Typography variant="subtitle2" component="h3" sx={{ mb: 0.5 }}>
                    Changes (old → new)
                  </Typography>
                  <Json value={selected.changes} />
                </>
              )}
              {selected.details && (
                <>
                  <Typography variant="subtitle2" component="h3" sx={{ mt: 2, mb: 0.5 }}>
                    Details
                  </Typography>
                  <Json value={selected.details} />
                </>
              )}
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setSelected(null)}>Close</Button>
            </DialogActions>
          </>
        )}
      </Dialog>
    </Box>
  );
}
