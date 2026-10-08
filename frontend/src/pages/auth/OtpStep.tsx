import { useEffect, useRef, useState } from 'react';
import { useSnackbar } from 'notistack';
import { Alert, Box, Button, Link, Stack, TextField, Typography } from '@mui/material';
import TerminalIcon from '@mui/icons-material/TerminalOutlined';
import PhonelinkLockIcon from '@mui/icons-material/PhonelinkLockOutlined';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { getErrorCode, getErrorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import type { CurrentUser, OtpChallenge } from '../../types';
import { AuthHeading } from './AuthLayout';
import { OtpInput } from './OtpInput';

const formatClock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;

/** Codes that mean this challenge can't be used any more: the user has to start over. */
const DEAD_CHALLENGE = new Set(['OTP_LOCKED', 'OTP_INVALID_CHALLENGE', 'OTP_RESEND_LIMIT']);
const RECOVERY_CODE = /^[A-Za-z0-9]{5}-?[A-Za-z0-9]{5}$/;

interface Props {
  challenge: OtpChallenge;
  onVerified: (user: CurrentUser) => void;
  onStartOver: () => void;
}

export function OtpStep({ challenge: initial, onVerified, onStartOver }: Props) {
  const { verifyOtp, verifyRecoveryCode, resendOtp } = useAuth();
  const { enqueueSnackbar } = useSnackbar();
  const [challenge, setChallenge] = useState(initial);
  const [code, setCode] = useState('');
  const [recoveryMode, setRecoveryMode] = useState(false);
  const [recoveryCode, setRecoveryCode] = useState('');
  const [error, setError] = useState<{ message: string; dead: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [now, setNow] = useState(() => Date.now());
  const [issuedAt, setIssuedAt] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const elapsed = Math.floor((now - issuedAt) / 1000);
  const expiresIn = Math.max(0, challenge.expires_in - elapsed);
  const resendIn = Math.max(0, challenge.resend_available_in - elapsed);
  const expired = expiresIn === 0;
  const signingUp = challenge.purpose === 'SIGNUP';
  const authenticator = challenge.method === 'totp';

  const fail = (err: unknown) => {
    setError({ message: getErrorMessage(err), dead: DEAD_CHALLENGE.has(getErrorCode(err) ?? '') });
  };

  const submit = async (value = code) => {
    if (value.length !== challenge.code_length || pending.current || expired || error?.dead) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      onVerified(await verifyOtp(challenge.challenge_id, value));
    } catch (err) {
      fail(err);
      setCode('');
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };

  const submitRecovery = async () => {
    if (!RECOVERY_CODE.test(recoveryCode.trim()) || pending.current || expired || error?.dead) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      onVerified(await verifyRecoveryCode(challenge.challenge_id, recoveryCode.trim()));
    } catch (err) {
      fail(err);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };

  const resend = async () => {
    if (pending.current || resendIn > 0 || error?.dead || authenticator) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      const next = await resendOtp(challenge.challenge_id);
      setChallenge(next);
      setIssuedAt(Date.now());
      setNow(Date.now());
      setCode('');
      enqueueSnackbar('A new code is on its way', { variant: 'success' });
    } catch (err) {
      fail(err);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };

  const subtitle = authenticator ? (
    recoveryMode ? (
      'Enter one of the recovery codes you saved when you set up your authenticator app. Each code works once.'
    ) : (
      <>Enter the {challenge.code_length}-digit code from your authenticator app to finish signing in.</>
    )
  ) : (
    <>
      Enter the {challenge.code_length}-digit code for <strong>{challenge.destination}</strong>
      {signingUp ? ' to activate your account.' : ' to finish signing in.'}
    </>
  );

  return (
    <Box>
      <AuthHeading title={signingUp ? 'Verify your email' : 'Two-step verification'} subtitle={subtitle} />

      {authenticator ? (
        <Alert severity="info" icon={<PhonelinkLockIcon fontSize="inherit" />} sx={{ mb: 3 }}>
          Your account uses an <strong>authenticator app</strong> (Google Authenticator, Microsoft Authenticator,
          1Password…). No code is sent by email.
        </Alert>
      ) : challenge.delivery === 'log' ? (
        <Alert severity="info" icon={<TerminalIcon fontSize="inherit" />} sx={{ mb: 3 }}>
          In this environment codes are written to the <strong>server log</strong>. Look for{' '}
          <Box component="code" sx={{ fontSize: 13 }}>
            OTP for
          </Box>{' '}
          in the terminal running the backend, or run{' '}
          <Box component="code" sx={{ fontSize: 13, whiteSpace: 'nowrap' }}>
            docker compose logs -f backend
          </Box>
          .
        </Alert>
      ) : (
        <Alert severity="info" sx={{ mb: 3 }}>
          We emailed the code to {challenge.destination}. It can take a minute to arrive.
        </Alert>
      )}

      {recoveryMode ? (
        <Box
          component="form"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void submitRecovery();
          }}
        >
          <TextField
            label="Recovery code"
            placeholder="xxxxx-xxxxx"
            value={recoveryCode}
            onChange={(e) => {
              setRecoveryCode(e.target.value);
              if (error && !error.dead) setError(null);
            }}
            autoComplete="one-time-code"
            autoFocus
            fullWidth
            disabled={busy || expired || Boolean(error?.dead)}
            error={Boolean(error)}
            slotProps={{ htmlInput: { spellCheck: false, autoCapitalize: 'none', maxLength: 11 } }}
          />
          <Box aria-live="polite" sx={{ minHeight: 24, mt: 1.5 }}>
            {error && (
              <Typography variant="body2" color="error">
                {error.message}
              </Typography>
            )}
          </Box>
          {error?.dead ? (
            <Button fullWidth size="large" variant="contained" sx={{ mt: 2 }} onClick={onStartOver}>
              Start again
            </Button>
          ) : (
            <Button
              type="submit"
              fullWidth
              size="large"
              variant="contained"
              sx={{ mt: 2 }}
              disabled={busy || expired || !RECOVERY_CODE.test(recoveryCode.trim())}
            >
              {busy ? 'Verifying…' : 'Use recovery code'}
            </Button>
          )}
        </Box>
      ) : (
        <Box
          component="form"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <OtpInput
            length={challenge.code_length}
            value={code}
            onChange={(value) => {
              setCode(value);
              if (error && !error.dead) setError(null);
            }}
            onComplete={(value) => void submit(value)}
            disabled={busy || expired || Boolean(error?.dead)}
            error={Boolean(error)}
            autoFocus
          />

          <Box aria-live="polite" sx={{ minHeight: 24, mt: 1.5 }}>
            {error ? (
              <Typography variant="body2" color="error">
                {error.message}
              </Typography>
            ) : (
              <Typography variant="body2" color={expired ? 'error' : 'text.secondary'}>
                {expired
                  ? authenticator
                    ? 'This sign-in attempt has expired. Start again.'
                    : 'This code has expired. Request a new one.'
                  : authenticator
                    ? `Finish signing in within ${formatClock(expiresIn)}`
                    : `Code expires in ${formatClock(expiresIn)}`}
              </Typography>
            )}
          </Box>

          {error?.dead ? (
            <Button fullWidth size="large" variant="contained" sx={{ mt: 2 }} onClick={onStartOver}>
              Start again
            </Button>
          ) : (
            <Button
              type="submit"
              fullWidth
              size="large"
              variant="contained"
              sx={{ mt: 2 }}
              disabled={busy || expired || code.length !== challenge.code_length}
            >
              {busy ? 'Verifying…' : signingUp ? 'Verify and continue' : 'Verify and sign in'}
            </Button>
          )}
        </Box>
      )}

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        justifyContent="space-between"
        alignItems="center"
        sx={{ mt: 3 }}
        spacing={1}
      >
        <Link
          component="button"
          type="button"
          underline="hover"
          onClick={onStartOver}
          disabled={busy}
          sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
        >
          <ArrowBackIcon sx={{ fontSize: 16 }} /> Use a different account
        </Link>
        {authenticator ? (
          <Button
            size="small"
            onClick={() => {
              setRecoveryMode((on) => !on);
              setError(null);
            }}
            disabled={busy || expired || Boolean(error?.dead)}
          >
            {recoveryMode ? 'Use the authenticator app' : 'Use a recovery code'}
          </Button>
        ) : (
          <Button size="small" onClick={() => void resend()} disabled={busy || resendIn > 0 || Boolean(error?.dead)}>
            {resendIn > 0 ? `Resend in ${formatClock(resendIn)}` : 'Resend code'}
          </Button>
        )}
      </Stack>
    </Box>
  );
}
