import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSnackbar } from 'notistack';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid2 as Grid,
  InputAdornment,
  MenuItem,
  Paper,
  Skeleton,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import PersonAddIcon from '@mui/icons-material/PersonAddAlt1Outlined';
import { settingsApi, usersApi } from '../../api/endpoints';
import { getErrorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { DataTable, type Column } from '../../components/DataTable';
import { PageHeader } from '../../components/PageHeader';
import { applyServerErrors } from '../../utils/forms';
import { formatDate, formatMoney, humanize } from '../../utils/format';
import type { Role, User } from '../../types';

const ROLES: Role[] = ['SALES', 'MANAGER', 'ADMIN'];

// ------------------------------------------------------------------ business rules

const settingsSchema = z.object({
  approval_threshold: z.coerce.number({ invalid_type_error: 'Enter an amount' }).min(0, 'Cannot be negative'),
  tax_rate: z.coerce.number({ invalid_type_error: 'Enter a rate' }).min(0).max(100, 'At most 100%'),
});
type SettingsValues = z.infer<typeof settingsSchema>;

function BusinessRules() {
  const { data, error, refetch } = useQuery({ queryKey: ['settings'], queryFn: settingsApi.get });
  return (
    <Paper sx={{ p: 2.5, mb: 3 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
        Business rules
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Orders with a total above the threshold need manager approval. Changes apply to new orders only.
      </Typography>
      {/* Mount the form only once values exist, so fields start filled and labels float correctly. */}
      {error && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={
            <Button color="inherit" onClick={() => void refetch()}>
              Retry
            </Button>
          }
        >
          {getErrorMessage(error)}
        </Alert>
      )}
      {data ? <BusinessRulesForm current={data} /> : !error && <Skeleton variant="rounded" height={56} />}
    </Paper>
  );
}

function BusinessRulesForm({ current }: { current: SettingsValues }) {
  const queryClient = useQueryClient();
  const { enqueueSnackbar } = useSnackbar();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isDirty },
  } = useForm<SettingsValues>({ resolver: zodResolver(settingsSchema), defaultValues: current });

  const mutation = useMutation({
    mutationFn: settingsApi.update,
    onSuccess: (saved) => {
      queryClient.setQueryData(['settings'], saved);
      reset(saved);
      enqueueSnackbar('Business rules updated', { variant: 'success' });
    },
    onError: (err) => enqueueSnackbar(getErrorMessage(err), { variant: 'error' }),
  });

  return (
    <>
      <Box component="form" noValidate onSubmit={handleSubmit((v) => mutation.mutate(v))}>
        <Grid container spacing={2} alignItems="flex-start">
          <Grid size={{ xs: 12, sm: 5 }}>
            <TextField
              label="Approval threshold"
              type="number"
              fullWidth
              {...register('approval_threshold')}
              error={!!errors.approval_threshold}
              helperText={errors.approval_threshold?.message ?? `Currently ${formatMoney(current.approval_threshold)}`}
              slotProps={{
                input: { startAdornment: <InputAdornment position="start">₹</InputAdornment> },
                htmlInput: { step: '0.01', min: 0 },
              }}
            />
          </Grid>
          <Grid size={{ xs: 12, sm: 4 }}>
            <TextField
              label="Tax rate"
              type="number"
              fullWidth
              {...register('tax_rate')}
              error={!!errors.tax_rate}
              helperText={errors.tax_rate?.message ?? ' '}
              slotProps={{
                input: { endAdornment: <InputAdornment position="end">%</InputAdornment> },
                htmlInput: { step: '0.01', min: 0, max: 100 },
              }}
            />
          </Grid>
          <Grid size={{ xs: 12, sm: 3 }}>
            <Button
              type="submit"
              variant="contained"
              fullWidth
              sx={{ height: 56 }}
              disabled={!isDirty || mutation.isPending}
            >
              {mutation.isPending ? 'Saving…' : 'Save'}
            </Button>
          </Grid>
        </Grid>
      </Box>
    </>
  );
}

// ------------------------------------------------------------------ users

const userSchema = z.object({
  name: z.string().trim().min(2, 'At least 2 characters').max(120),
  email: z.string().trim().email('Enter a valid email'),
  password: z
    .string()
    .min(8, 'At least 8 characters')
    .refine((v) => new TextEncoder().encode(v).length <= 72, 'At most 72 bytes')
    .refine((v) => /\p{L}/u.test(v) && /\d/.test(v), 'Include at least one letter and one number'),
  role: z.enum(['SALES', 'MANAGER', 'ADMIN']),
});
type UserValues = z.infer<typeof userSchema>;

function AddUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { enqueueSnackbar } = useSnackbar();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<UserValues>({ resolver: zodResolver(userSchema) });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = form;

  useEffect(() => {
    if (open) {
      setError(null);
      reset({ name: '', email: '', password: '', role: 'SALES' });
    }
  }, [open, reset]);

  const mutation = useMutation({
    mutationFn: usersApi.create,
    onSuccess: (user) => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      enqueueSnackbar(`${user.name} can now sign in`, { variant: 'success' });
      onClose();
    },
    onError: (err) => {
      if (!applyServerErrors(err, form.setError, { DUPLICATE_EMAIL: 'email' })) setError(getErrorMessage(err));
    },
  });

  return (
    <Dialog open={open} onClose={mutation.isPending ? undefined : onClose} maxWidth="xs" fullWidth>
      <form noValidate onSubmit={handleSubmit((v) => mutation.mutate(v))}>
        <DialogTitle>Add user</DialogTitle>
        <DialogContent>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Name" {...register('name')} error={!!errors.name} helperText={errors.name?.message} />
            <TextField
              label="Email"
              type="email"
              {...register('email')}
              error={!!errors.email}
              helperText={errors.email?.message}
            />
            <TextField
              label="Temporary password"
              type="password"
              autoComplete="new-password"
              {...register('password')}
              error={!!errors.password}
              helperText={errors.password?.message}
            />
            <TextField select label="Role" defaultValue="SALES" {...register('role')}>
              {ROLES.map((role) => (
                <MenuItem key={role} value={role}>
                  {humanize(role)}
                </MenuItem>
              ))}
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={mutation.isPending}>
            Add user
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}

function Users() {
  const { user: me } = useAuth();
  const queryClient = useQueryClient();
  const { enqueueSnackbar } = useSnackbar();
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const [adding, setAdding] = useState(false);

  const params = { page: page + 1, page_size: pageSize };
  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ['users', params],
    queryFn: ({ signal }) => usersApi.list(params, signal),
    placeholderData: keepPreviousData,
  });

  const update = useMutation({
    mutationFn: ({ id, changes }: { id: number; changes: { role?: Role; is_active?: boolean } }) =>
      usersApi.update(id, changes),
    onSuccess: (u) => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      enqueueSnackbar(`${u.name} updated`, { variant: 'success' });
    },
    onError: (err) => enqueueSnackbar(getErrorMessage(err), { variant: 'error' }),
  });

  const columns: Column<User>[] = [
    {
      key: 'name',
      header: 'User',
      render: (u) => (
        <Box>
          <Typography variant="body2" component="div" sx={{ fontWeight: 500 }}>
            {u.name} {u.id === me?.id && <Chip size="small" label="You" sx={{ ml: 0.5, height: 18 }} />}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {u.email}
          </Typography>
        </Box>
      ),
    },
    {
      key: 'role',
      header: 'Role',
      render: (u) => (
        <TextField
          select
          size="small"
          value={u.role}
          disabled={u.id === me?.id || update.isPending}
          onChange={(e) => update.mutate({ id: u.id, changes: { role: e.target.value as Role } })}
          sx={{ minWidth: 130 }}
          slotProps={{ htmlInput: { 'aria-label': `Role for ${u.name}` } }}
        >
          {ROLES.map((role) => (
            <MenuItem key={role} value={role}>
              {humanize(role)}
            </MenuItem>
          ))}
        </TextField>
      ),
    },
    {
      key: 'since',
      header: 'Since',
      hideOnMobile: true,
      render: (u) =>
        u.is_verified ? (
          formatDate(u.created_at)
        ) : (
          <Tooltip title="Signed up but hasn't confirmed their email code yet">
            <Chip size="small" label="Email unverified" sx={{ bgcolor: '#fdf3e2', color: '#94570a' }} />
          </Tooltip>
        ),
    },
    {
      key: 'active',
      header: 'Active',
      align: 'right',
      render: (u) => (
        <Tooltip describeChild title={u.id === me?.id ? 'You cannot deactivate yourself' : ''}>
          <span>
            <Switch
              checked={u.is_active}
              slotProps={{ input: { 'aria-label': `${u.name} account active` } }}
              disabled={u.id === me?.id || update.isPending}
              onChange={(e) => update.mutate({ id: u.id, changes: { is_active: e.target.checked } })}
            />
          </span>
        </Tooltip>
      ),
    },
  ];

  return (
    <>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
        <Box>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            Users
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Managers and admins can approve orders; managers receive approval emails.
          </Typography>
        </Box>
        <Button
          variant="outlined"
          startIcon={<PersonAddIcon />}
          onClick={() => setAdding(true)}
          sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}
        >
          Add user
        </Button>
      </Box>
      <DataTable
        rows={data?.items}
        columns={columns}
        rowKey={(u) => u.id}
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
      />
      <AddUserDialog open={adding} onClose={() => setAdding(false)} />
    </>
  );
}

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings & users" subtitle="Approval rules and who can access the system" />
      <BusinessRules />
      <Users />
    </>
  );
}
