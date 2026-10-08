import { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Alert, Box, Button, Link, Stack, TextField, Typography } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import TerminalIcon from '@mui/icons-material/TerminalOutlined';
import { getErrorCode, getErrorMessage } from '../../api/client';
import { authApi } from '../../api/endpoints';
import { useAuth } from '../../auth/AuthContext';
import type { PasswordForgotResult } from '../../types';
import { AuthHeading, AuthLayout } from './AuthLayout';
import { OtpInput } from './OtpInput';
import { PasswordField } from './PasswordField';
import { meetsPasswordPolicy } from './passwordPolicy';

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Step =
  { name: 'email' } | { name: 'reset'; email: string; sent: PasswordForgotResult; at: number } | { name: 'done' };

export default function ForgotPasswordPage() {
  const { endLocalSession } = useAuth();
  const [step, setStep] = useState<Step>({ name: 'email' });
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const request = async (address: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const sent = await authApi.forgotPassword(address.trim());
      setStep({ name: 'reset', email: address.trim(), sent, at: Date.now() });
      setNow(Date.now());
      setCode('');
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (step.name !== 'reset' || busy) return;
    setBusy(true);
    setError(null);
    try {
      await authApi.resetPassword(step.email, code, password);
      endLocalSession();
      setStep({ name: 'done' });
    } catch (err) {
      setError(getErrorMessage(err));
      if (getErrorCode(err) === 'RESET_CODE_INVALID') setCode('');
    } finally {
      setBusy(false);
    }
  };

  const back = (
    <Link
      component={RouterLink}
      to="/login"
      underline="hover"
      sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, mt: 3 }}
    >
      <ArrowBackIcon sx={{ fontSize: 16 }} /> Back to sign in
    </Link>
  );

  if (step.name === 'done') {
    return (
      <AuthLayout>
        <AuthHeading
          title="Password changed"
          subtitle="You've been signed out everywhere. Sign in with your new password."
        />
        <Button component={RouterLink} to="/login" variant="contained" size="large" fullWidth>
          Sign in
        </Button>
      </AuthLayout>
    );
  }

  if (step.name === 'email') {
    return (
      <AuthLayout>
        <AuthHeading
          title="Reset your password"
          subtitle="Enter your work email and we'll send you a code to set a new password."
        />
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        <Box
          component="form"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            if (EMAIL.test(email.trim())) void request(email);
          }}
        >
          <Stack spacing={2.25}>
            <TextField
              label="Email"
              type="email"
              autoComplete="username"
              autoFocus
              fullWidth
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Button type="submit" variant="contained" size="large" disabled={busy || !EMAIL.test(email.trim())}>
              {busy ? 'Sending…' : 'Send code'}
            </Button>
          </Stack>
        </Box>
        {back}
      </AuthLayout>
    );
  }

  const elapsed = Math.max(0, Math.floor((now - step.at) / 1000));
  const resendIn = Math.max(0, step.sent.resend_available_in - elapsed);
  const expiresIn = Math.max(0, step.sent.expires_in - elapsed);
  const mismatch = confirm.length > 0 && confirm !== password;
  const ready =
    expiresIn > 0 && code.length === step.sent.code_length && meetsPasswordPolicy(password) && confirm === password;

  return (
    <AuthLayout>
      <AuthHeading title="Choose a new password" subtitle={step.sent.message} />
      {step.sent.delivery === 'log' && (
        <Alert severity="info" icon={<TerminalIcon fontSize="inherit" />} sx={{ mb: 3 }}>
          In this environment codes are written to the <strong>server log</strong> (
          <Box component="code" sx={{ fontSize: 13 }}>
            docker compose logs -f backend
          </Box>
          ).
        </Alert>
      )}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      <Box
        component="form"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) void reset();
        }}
      >
        <Stack spacing={2.25}>
          <Box>
            <Typography variant="body2" sx={{ mb: 1, fontWeight: 500 }} id="reset-code-label">
              Code
            </Typography>
            <OtpInput
              length={step.sent.code_length}
              value={code}
              onChange={setCode}
              disabled={busy || expiresIn === 0}
              autoFocus
            />
            <Typography variant="body2" color={expiresIn === 0 ? 'error' : 'text.secondary'} sx={{ mt: 1 }}>
              {expiresIn === 0
                ? 'This code has expired. Request a new one.'
                : `Code expires in ${Math.floor(expiresIn / 60)}:${String(expiresIn % 60).padStart(2, '0')}`}
            </Typography>
          </Box>
          <PasswordField
            label="New password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
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
          <Button type="submit" variant="contained" size="large" disabled={busy || !ready}>
            {busy ? 'Saving…' : 'Set new password'}
          </Button>
        </Stack>
      </Box>
      <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems="center">
        {back}
        <Button size="small" sx={{ mt: 3 }} disabled={resendIn > 0 || busy} onClick={() => void request(step.email)}>
          {resendIn > 0 ? `Send a new code in ${resendIn}s` : 'Send a new code'}
        </Button>
      </Stack>
    </AuthLayout>
  );
}
