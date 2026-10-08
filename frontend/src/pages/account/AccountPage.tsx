import { useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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
  Paper,
  Skeleton,
  Stack,
  Typography,
} from '@mui/material';
import ComputerIcon from '@mui/icons-material/ComputerOutlined';
import { getErrorMessage } from '../../api/client';
import { authApi } from '../../api/endpoints';
import { useAuth } from '../../auth/AuthContext';
import { PageHeader } from '../../components/PageHeader';
import { formatDateTime, humanize } from '../../utils/format';
import { describeUserAgent } from '../../utils/userAgent';
import { PasswordField } from '../auth/PasswordField';
import { meetsPasswordPolicy } from '../auth/passwordPolicy';
import { PasswordConfirmDialog } from './PasswordConfirmDialog';
import { RecoveryCodes } from './RecoveryCodes';
import { TotpSetupDialog } from './TotpSetupDialog';

function Card({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <Paper component="section" aria-label={title} sx={{ p: { xs: 2, sm: 3 } }}>
      <Typography variant="h6" component="h2">
        {title}
      </Typography>
      {subtitle && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
          {subtitle}
        </Typography>
      )}
      {children}
    </Paper>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <Stack direction="row" justifyContent="space-between" spacing={2} sx={{ py: 0.75 }}>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" sx={{ fontWeight: 500, textAlign: 'right', minWidth: 0, overflowWrap: 'anywhere' }}>
        {value}
      </Typography>
    </Stack>
  );
}

function ChangePassword() {
  const { reloadUser } = useAuth();
  const { enqueueSnackbar } = useSnackbar();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const queryClient = useQueryClient();
  const change = useMutation({
    mutationFn: () => authApi.changePassword(current, next),
    onSuccess: () => {
      setCurrent('');
      setNext('');
      setConfirm('');
      void queryClient.invalidateQueries({ queryKey: ['sessions'] });
      void reloadUser().catch((err) => enqueueSnackbar(getErrorMessage(err), { variant: 'error' }));
      enqueueSnackbar('Password changed. Your other devices were signed out.', { variant: 'success' });
    },
  });
  const mismatch = confirm.length > 0 && confirm !== next;
  const ready = current.length > 0 && meetsPasswordPolicy(next) && confirm === next;

  return (
    <Card title="Password" subtitle="Changing it signs out every other device.">
      <Box
        component="form"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          if (ready && !change.isPending) change.mutate();
        }}
      >
        <Stack spacing={2} sx={{ maxWidth: 420 }}>
          {change.isError && <Alert severity="error">{getErrorMessage(change.error)}</Alert>}
          <PasswordField
            label="Current password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
          <PasswordField
            label="New password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            showStrength
          />
          <PasswordField
            label="Confirm new password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            error={mismatch}
            helperText={mismatch ? 'Passwords do not match' : ' '}
          />
          <Box>
            <Button type="submit" variant="contained" disabled={!ready || change.isPending}>
              {change.isPending ? 'Saving…' : 'Change password'}
            </Button>
          </Box>
        </Stack>
      </Box>
    </Card>
  );
}

function TwoStepVerification() {
  const { reloadUser } = useAuth();
  const { enqueueSnackbar } = useSnackbar();
  const queryClient = useQueryClient();
  const { data: mfa, isLoading, error, refetch } = useQuery({ queryKey: ['mfa'], queryFn: authApi.mfa });
  const [setupOpen, setSetupOpen] = useState(false);
  const [confirm, setConfirm] = useState<'disable' | 'regenerate' | null>(null);
  const [newCodes, setNewCodes] = useState<string[] | null>(null);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['mfa'] });
    void reloadUser().catch((err) => enqueueSnackbar(getErrorMessage(err), { variant: 'error' }));
  };

  if (!mfa)
    return (
      <Card title="Two-step verification">
        {error ? (
          <Alert
            severity="error"
            action={
              <Button color="inherit" onClick={() => void refetch()}>
                Retry
              </Button>
            }
          >
            {getErrorMessage(error)}
          </Alert>
        ) : isLoading ? (
          <Skeleton variant="rounded" height={160} />
        ) : null}
      </Card>
    );

  return (
    <Card
      title="Two-step verification"
      subtitle="Every sign-in needs a second step after the password, so a stolen password alone isn't enough."
    >
      <Row
        label="Second step"
        value={
          mfa.totp_enabled ? (
            <Chip size="small" color="success" label="Authenticator app" />
          ) : mfa.method === 'code' ? (
            'One-time code (email / server log)'
          ) : (
            'Off'
          )
        }
      />
      {mfa.totp_enabled && (
        <>
          <Row label="Turned on" value={formatDateTime(mfa.totp_enabled_at)} />
          <Row label="Recovery codes left" value={mfa.recovery_codes_remaining} />
        </>
      )}
      {mfa.totp_enabled && mfa.recovery_codes_remaining <= 3 && (
        <Alert severity="warning" sx={{ mt: 1 }}>
          You're running low on recovery codes. Generate a new set.
        </Alert>
      )}
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ mt: 2 }}>
        {mfa.totp_enabled ? (
          <>
            <Button variant="outlined" onClick={() => setConfirm('regenerate')}>
              New recovery codes
            </Button>
            <Button color="error" onClick={() => setConfirm('disable')}>
              Turn off authenticator app
            </Button>
          </>
        ) : (
          <Button variant="contained" onClick={() => setSetupOpen(true)}>
            Set up authenticator app
          </Button>
        )}
      </Stack>

      <TotpSetupDialog
        open={setupOpen}
        onClose={() => setSetupOpen(false)}
        onEnabled={() => {
          refresh();
          enqueueSnackbar('Authenticator app turned on', { variant: 'success' });
        }}
      />
      <PasswordConfirmDialog
        open={confirm === 'disable'}
        title="Turn off the authenticator app?"
        description="Sign-in will go back to one-time codes, and your recovery codes will stop working."
        confirmLabel="Turn off"
        destructive
        onClose={() => setConfirm(null)}
        onConfirm={async (password) => {
          await authApi.totpDisable(password);
          setConfirm(null);
          refresh();
          enqueueSnackbar('Authenticator app turned off', { variant: 'success' });
        }}
      />
      <PasswordConfirmDialog
        open={confirm === 'regenerate'}
        title="Generate new recovery codes?"
        description="Your current recovery codes will stop working."
        confirmLabel="Generate"
        onClose={() => setConfirm(null)}
        onConfirm={async (password) => {
          setNewCodes((await authApi.regenerateRecoveryCodes(password)).recovery_codes);
          setConfirm(null);
          refresh();
        }}
      />
      <Dialog open={Boolean(newCodes)} onClose={() => setNewCodes(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Your new recovery codes</DialogTitle>
        <DialogContent>{newCodes && <RecoveryCodes codes={newCodes} />}</DialogContent>
        <DialogActions>
          <Button variant="contained" onClick={() => setNewCodes(null)}>
            I've saved my codes
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}

function Sessions() {
  const { logout } = useAuth();
  const { enqueueSnackbar } = useSnackbar();
  const queryClient = useQueryClient();
  const { data: sessions, isLoading, error, refetch } = useQuery({ queryKey: ['sessions'], queryFn: authApi.sessions });
  const revoke = useMutation({
    mutationFn: (id: string) => authApi.revokeSession(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['sessions'] });
      enqueueSnackbar('Device signed out', { variant: 'success' });
    },
    onError: (err) => enqueueSnackbar(getErrorMessage(err), { variant: 'error' }),
  });
  const revokeOthers = useMutation({
    mutationFn: () => authApi.revokeAllSessions(true),
    onSuccess: ({ revoked }) => {
      void queryClient.invalidateQueries({ queryKey: ['sessions'] });
      enqueueSnackbar(`Signed out of ${revoked} other device${revoked === 1 ? '' : 's'}`, { variant: 'success' });
    },
    onError: (err) => enqueueSnackbar(getErrorMessage(err), { variant: 'error' }),
  });
  const others = sessions?.filter((s) => !s.current) ?? [];

  return (
    <Card title="Devices" subtitle="Where your account is signed in. Sign out anything you don't recognise.">
      {isLoading && <Skeleton variant="rounded" height={120} />}
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
      <Stack spacing={1.5} component="ul" sx={{ listStyle: 'none', p: 0, m: 0 }}>
        {sessions?.map((session) => (
          <Stack
            key={session.id}
            component="li"
            direction={{ xs: 'column', sm: 'row' }}
            spacing={1.5}
            alignItems={{ sm: 'center' }}
            sx={{ p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}
          >
            <ComputerIcon sx={{ color: 'text.secondary', display: { xs: 'none', sm: 'block' } }} />
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Stack direction="row" spacing={1} alignItems="center">
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {describeUserAgent(session.user_agent)}
                </Typography>
                {session.current && <Chip size="small" color="primary" variant="outlined" label="This device" />}
              </Stack>
              <Typography variant="caption" color="text.secondary" component="div">
                {session.ip_address ?? 'unknown IP'} · signed in {formatDateTime(session.authenticated_at)} · last
                active {formatDateTime(session.last_seen_at)}
                {session.mfa_method ? ` · ${humanize(session.mfa_method)}` : ''}
              </Typography>
            </Box>
            {session.current ? (
              <Button size="small" onClick={() => void logout()}>
                Sign out
              </Button>
            ) : (
              <Button size="small" color="error" onClick={() => revoke.mutate(session.id)} disabled={revoke.isPending}>
                Sign out
              </Button>
            )}
          </Stack>
        ))}
      </Stack>
      <Button sx={{ mt: 2 }} disabled={!others.length || revokeOthers.isPending} onClick={() => revokeOthers.mutate()}>
        Sign out of all other devices
      </Button>
    </Card>
  );
}

export default function AccountPage() {
  const { user } = useAuth();
  if (!user) return null;
  return (
    <Box>
      <PageHeader title="Account & security" subtitle="Your sign-in details, second factor and devices." />
      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' }, alignItems: 'start' }}>
        <Stack spacing={2}>
          <Card title="Profile">
            <Row label="Name" value={user.name} />
            <Row label="Email" value={user.email} />
            <Row label="Role" value={humanize(user.role)} />
            <Row label="Last sign-in" value={formatDateTime(user.last_login_at)} />
            <Row label="Password changed" value={formatDateTime(user.password_changed_at)} />
          </Card>
          <TwoStepVerification />
        </Stack>
        <Stack spacing={2}>
          <ChangePassword />
          <Sessions />
        </Stack>
      </Box>
    </Box>
  );
}
