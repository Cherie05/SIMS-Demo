import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Step,
  StepLabel,
  Stepper,
  Typography,
} from '@mui/material';
import { getErrorMessage } from '../../api/client';
import { authApi } from '../../api/endpoints';
import type { TotpSetup } from '../../types';
import { OtpInput } from '../auth/OtpInput';
import { PasswordField } from '../auth/PasswordField';
import { RecoveryCodes } from './RecoveryCodes';

const STEPS = ['Confirm it’s you', 'Scan the QR code', 'Save recovery codes'];

/** Authenticator-app enrolment: password -> QR code + first code -> recovery codes. */
export function TotpSetupDialog({
  open,
  onClose,
  onEnabled,
}: {
  open: boolean;
  onClose: () => void;
  onEnabled: () => void;
}) {
  const [step, setStep] = useState(0);
  const [password, setPassword] = useState('');
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [code, setCode] = useState('');
  const [codes, setCodes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setStep(0);
    setPassword('');
    setSetup(null);
    setCode('');
    setCodes([]);
    setError(null);
  };

  const close = () => {
    if (step === 2) onEnabled();
    reset();
    onClose();
  };

  const run = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const start = () =>
    run(async () => {
      setSetup(await authApi.totpSetup(password));
      setPassword('');
      setStep(1);
    });

  const confirm = (value = code) =>
    run(async () => {
      try {
        setCodes((await authApi.totpEnable(value)).recovery_codes);
        setStep(2);
      } catch (err) {
        setCode('');
        throw err;
      }
    });

  return (
    <Dialog open={open} onClose={busy ? undefined : close} maxWidth="sm" fullWidth aria-labelledby="totp-title">
      <DialogTitle id="totp-title">Set up an authenticator app</DialogTitle>
      <DialogContent>
        <Stepper activeStep={step} alternativeLabel sx={{ mb: 3 }}>
          {STEPS.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {step === 0 && (
          <Box
            component="form"
            onSubmit={(e) => {
              e.preventDefault();
              if (password) void start();
            }}
          >
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              After this, signing in asks for the 6-digit code from an app such as Google Authenticator, Microsoft
              Authenticator or 1Password, instead of a code sent to you.
            </Typography>
            <PasswordField
              label="Current password"
              autoComplete="current-password"
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Box>
        )}

        {step === 1 && setup && (
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={3} alignItems="center">
            <Box
              component="img"
              src={setup.qr_svg_data_uri}
              alt="QR code to scan with your authenticator app"
              sx={{ width: 200, height: 200, flexShrink: 0, border: 1, borderColor: 'divider', borderRadius: 2 }}
            />
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2" sx={{ mb: 1 }}>
                Scan the code with your authenticator app, or enter this key by hand:
              </Typography>
              <Box
                component="code"
                sx={{
                  display: 'block',
                  p: 1,
                  mb: 2,
                  bgcolor: 'grey.50',
                  borderRadius: 1,
                  wordBreak: 'break-all',
                  fontSize: 14,
                }}
              >
                {setup.secret.replace(/(.{4})/g, '$1 ').trim()}
              </Box>
              <Typography variant="body2" sx={{ mb: 1, fontWeight: 500 }}>
                Then enter the 6-digit code it shows:
              </Typography>
              <OtpInput
                length={6}
                value={code}
                onChange={setCode}
                onComplete={(value) => void confirm(value)}
                disabled={busy}
                autoFocus
              />
            </Box>
          </Stack>
        )}

        {step === 2 && <RecoveryCodes codes={codes} />}
      </DialogContent>
      <DialogActions>
        {step < 2 && (
          <Button onClick={close} disabled={busy}>
            Cancel
          </Button>
        )}
        {step === 0 && (
          <Button variant="contained" onClick={() => void start()} disabled={busy || !password}>
            Continue
          </Button>
        )}
        {step === 1 && (
          <Button variant="contained" onClick={() => void confirm()} disabled={busy || code.length !== 6}>
            {busy ? 'Checking…' : 'Turn on'}
          </Button>
        )}
        {step === 2 && (
          <Button variant="contained" onClick={close}>
            I've saved my codes
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
