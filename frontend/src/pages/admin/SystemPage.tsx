import { useState, type ReactNode } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSnackbar } from 'notistack';
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControlLabel,
  MenuItem,
  Paper,
  Skeleton,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import { getErrorMessage } from '../../api/client';
import { systemApi } from '../../api/endpoints';
import { useAuth } from '../../auth/AuthContext';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { DataTable, type Column } from '../../components/DataTable';
import { PageHeader } from '../../components/PageHeader';
import { StatusChip } from '../../components/StatusChip';
import type { DependencyStatus, FeatureFlag, Job, JobStatus } from '../../types';
import { formatDateTime, formatNumber, humanize } from '../../utils/format';

const HEALTH_LABEL: Record<
  DependencyStatus['status'],
  { label: string; color: 'success' | 'warning' | 'error' | 'default' }
> = {
  ok: { label: 'Healthy', color: 'success' },
  degraded: { label: 'Degraded', color: 'warning' },
  down: { label: 'Down', color: 'error' },
  not_configured: { label: 'Not configured', color: 'default' },
  unknown: { label: 'Unknown', color: 'default' },
};

function Tile({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Paper component="section" aria-label={title} sx={{ p: 2, minWidth: 0 }}>
      <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600, letterSpacing: 0.3 }}>
        {title.toUpperCase()}
      </Typography>
      <Box sx={{ mt: 1 }}>{children}</Box>
    </Paper>
  );
}

function Health({ check }: { check: DependencyStatus }) {
  const { label, color } = HEALTH_LABEL[check.status];
  return (
    <Stack spacing={0.5}>
      <Box>
        <Chip size="small" color={color} label={label} />
      </Box>
      {check.detail && (
        <Typography variant="caption" color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>
          {check.detail}
        </Typography>
      )}
    </Stack>
  );
}

const uptime = (seconds: number) =>
  seconds >= 86400
    ? `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`
    : `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;

export default function SystemPage() {
  const { can } = useAuth();
  const canOperate = can('system:operate');
  const { enqueueSnackbar } = useSnackbar();
  const queryClient = useQueryClient();
  const [jobStatus, setJobStatus] = useState<JobStatus | ''>('DEAD');
  const [page, setPage] = useState(0);
  const [pendingFlag, setPendingFlag] = useState<FeatureFlag | null>(null);

  const status = useQuery({ queryKey: ['system', 'status'], queryFn: systemApi.status, refetchInterval: 15_000 });
  const flags = useQuery({ queryKey: ['feature-flags'], queryFn: systemApi.flags });
  const jobs = useQuery({
    queryKey: ['system', 'jobs', jobStatus, page],
    queryFn: ({ signal }) => systemApi.jobs({ status: jobStatus, page: page + 1, page_size: 10 }, signal),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });

  const retry = useMutation({
    mutationFn: (id: number) => systemApi.retryJob(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['system'] });
      enqueueSnackbar('Job queued again', { variant: 'success' });
    },
    onError: (err) => enqueueSnackbar(getErrorMessage(err), { variant: 'error' }),
  });
  const setFlag = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) => systemApi.setFlag(name, enabled),
    onSuccess: (flag) => {
      void queryClient.invalidateQueries({ queryKey: ['feature-flags'] });
      enqueueSnackbar(`${flag.name} switched ${flag.enabled ? 'on' : 'off'}`, { variant: 'success' });
    },
    onError: (err) => enqueueSnackbar(getErrorMessage(err), { variant: 'error' }),
  });

  const s = status.data;
  const workersAlive = s?.workers.filter((w) => w.alive).length ?? 0;

  const jobColumns: Column<Job>[] = [
    { key: 'id', header: '#', render: (j) => j.id, width: 70 },
    { key: 'type', header: 'Job', render: (j) => humanize(j.job_type.replace('email.', 'email_')) },
    { key: 'status', header: 'Status', render: (j) => <StatusChip status={j.status} /> },
    { key: 'attempts', header: 'Attempts', render: (j) => `${j.attempts}/${j.max_attempts}`, hideOnMobile: true },
    {
      key: 'ref',
      header: 'About',
      hideOnMobile: true,
      render: (j) =>
        Object.entries(j.reference)
          .map(([k, v]) => `${humanize(k)} ${v}`)
          .join(', ') || '—',
    },
    {
      key: 'error',
      header: 'Last error',
      hideOnMobile: true,
      render: (j) => (
        <Typography
          variant="caption"
          color={j.last_error ? 'error' : 'text.secondary'}
          sx={{ wordBreak: 'break-word' }}
        >
          {j.last_error ?? '—'}
        </Typography>
      ),
    },
    { key: 'created', header: 'Created', render: (j) => formatDateTime(j.created_at), hideOnMobile: true },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (j) =>
        j.status === 'DEAD' && canOperate ? (
          <Button size="small" onClick={() => retry.mutate(j.id)} disabled={retry.isPending}>
            Retry
          </Button>
        ) : null,
    },
  ];

  return (
    <Box>
      <PageHeader
        title="System"
        subtitle={
          s ? `Version ${s.version} · ${s.environment} · up ${uptime(s.uptime_seconds)}` : 'Health of the platform'
        }
      />
      {status.isError && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={
            <Button color="inherit" onClick={() => void status.refetch()}>
              Retry
            </Button>
          }
        >
          {getErrorMessage(status.error)}
        </Alert>
      )}
      {!s && !status.isError ? (
        <Skeleton variant="rounded" height={140} />
      ) : s ? (
        <Box
          sx={{
            display: 'grid',
            gap: 2,
            gridTemplateColumns: {
              xs: 'minmax(0, 1fr)',
              sm: 'repeat(2, minmax(0, 1fr))',
              md: 'repeat(5, minmax(0, 1fr))',
            },
            mb: 3,
          }}
        >
          <Tile title="Database">
            <Health check={s.database} />
          </Tile>
          <Tile title="Cache (Valkey)">
            <Health check={s.redis} />
          </Tile>
          <Tile title="Schema">
            <Health check={s.migrations} />
          </Tile>
          <Tile title="Workers">
            <Chip size="small" color={workersAlive ? 'success' : 'error'} label={`${workersAlive} running`} />
          </Tile>
          <Tile title="Email queue">
            <Typography variant="body2">
              {formatNumber((s.jobs.PENDING ?? 0) + (s.jobs.RETRY ?? 0) + (s.jobs.RUNNING ?? 0))} waiting ·{' '}
              <Box
                component="span"
                sx={{ color: s.jobs.DEAD ? 'error.main' : 'inherit', fontWeight: s.jobs.DEAD ? 700 : 400 }}
              >
                {formatNumber(s.jobs.DEAD ?? 0)} failed
              </Box>
            </Typography>
            {s.oldest_due_job_age_seconds > 60 && (
              <Typography variant="caption" color="warning.main">
                Oldest waiting {Math.round(s.oldest_due_job_age_seconds / 60)} min
              </Typography>
            )}
          </Tile>
        </Box>
      ) : null}

      <Box
        sx={{
          display: 'grid',
          gap: 2,
          gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'repeat(2, minmax(0, 1fr))' },
          mb: 3,
          alignItems: 'start',
        }}
      >
        <Paper component="section" aria-label="Feature flags" sx={{ p: { xs: 2, sm: 3 } }}>
          <Typography variant="h6" component="h2">
            Feature flags
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Kill switches for incidents - take effect immediately, no deploy needed. Every change is audited.
          </Typography>
          {flags.isLoading && <Skeleton variant="rounded" height={90} />}
          {flags.isError && (
            <Alert
              severity="error"
              action={
                <Button color="inherit" onClick={() => void flags.refetch()}>
                  Retry
                </Button>
              }
            >
              {getErrorMessage(flags.error)}
            </Alert>
          )}
          {flags.data?.map((flag) => (
            <Box key={flag.name} sx={{ py: 1, borderTop: 1, borderColor: 'divider' }}>
              <FormControlLabel
                control={
                  <Switch
                    checked={flag.enabled}
                    disabled={!canOperate || setFlag.isPending}
                    onChange={(e) =>
                      e.target.checked ? setFlag.mutate({ name: flag.name, enabled: true }) : setPendingFlag(flag)
                    }
                  />
                }
                label={
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {flag.name}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {flag.description}
                    </Typography>
                  </Box>
                }
              />
            </Box>
          ))}
        </Paper>

        <Paper component="section" aria-label="Workers and scheduled tasks" sx={{ p: { xs: 2, sm: 3 } }}>
          <Typography variant="h6" component="h2">
            Workers & housekeeping
          </Typography>
          <Stack spacing={1} sx={{ mt: 1.5 }}>
            {s?.workers.map((w) => (
              <Stack
                key={w.worker_id}
                direction={{ xs: 'column', sm: 'row' }}
                spacing={1}
                alignItems={{ sm: 'center' }}
                justifyContent="space-between"
                sx={{ minWidth: 0 }}
              >
                <Typography variant="body2" noWrap>
                  {w.worker_id}
                </Typography>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0 }}>
                  <Typography variant="caption" color="text.secondary">
                    {formatNumber(w.jobs_processed)} jobs · seen {formatDateTime(w.last_seen_at)}
                  </Typography>
                  <Chip size="small" color={w.alive ? 'success' : 'error'} label={w.alive ? 'Alive' : 'Stale'} />
                </Stack>
              </Stack>
            ))}
            {s && !s.workers.length && (
              <Alert severity="warning">No worker has reported in: emails are not being sent.</Alert>
            )}
          </Stack>
          <Typography variant="subtitle2" component="h3" sx={{ mt: 2.5, mb: 1 }}>
            Scheduled tasks
          </Typography>
          {s?.scheduled_tasks.map((t) => (
            <Stack
              key={t.name}
              direction={{ xs: 'column', sm: 'row' }}
              justifyContent="space-between"
              spacing={1}
              sx={{ py: 0.5 }}
            >
              <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>
                {t.name}
              </Typography>
              <Typography variant="caption" color={t.last_status === 'failed' ? 'error' : 'text.secondary'}>
                {t.last_status ?? 'never run'} · {formatDateTime(t.last_finished_at)} · {t.run_count} runs
              </Typography>
            </Stack>
          ))}
        </Paper>
      </Box>

      <DataTable
        label="Background jobs"
        rows={jobs.data?.items}
        columns={jobColumns}
        rowKey={(j) => j.id}
        loading={jobs.isFetching}
        error={jobs.isError ? getErrorMessage(jobs.error) : undefined}
        onRetry={() => void jobs.refetch()}
        total={jobs.data?.total}
        page={page}
        pageSize={10}
        onPageChange={setPage}
        emptyText={jobStatus === 'DEAD' ? 'No failed jobs' : 'No jobs'}
        toolbar={
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={2}
            alignItems={{ sm: 'center' }}
            justifyContent="space-between"
          >
            <Typography variant="h6" component="h2">
              Background jobs
            </Typography>
            <TextField
              select
              size="small"
              label="Status"
              value={jobStatus}
              onChange={(e) => {
                setJobStatus(e.target.value as JobStatus | '');
                setPage(0);
              }}
              sx={{ minWidth: 160 }}
            >
              {(['', 'DEAD', 'RETRY', 'PENDING', 'RUNNING', 'DONE', 'EXPIRED'] as const).map((value) => (
                <MenuItem key={value || 'all'} value={value}>
                  {value ? humanize(value) : 'All'}
                </MenuItem>
              ))}
            </TextField>
          </Stack>
        }
      />

      <ConfirmDialog
        open={Boolean(pendingFlag)}
        title={`Switch off ${pendingFlag?.name}?`}
        message={`${pendingFlag?.description}. This takes effect immediately for every user.`}
        confirmLabel="Switch off"
        confirmColor="error"
        onClose={() => setPendingFlag(null)}
        onConfirm={() => {
          if (pendingFlag) setFlag.mutate({ name: pendingFlag.name, enabled: false });
          setPendingFlag(null);
        }}
      />
    </Box>
  );
}
