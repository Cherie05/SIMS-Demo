import { useState } from 'react';
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle } from '@mui/material';
import { getErrorMessage } from '../../api/client';
import { PasswordField } from '../auth/PasswordField';

interface Props {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  destructive?: boolean;
  onClose: () => void;
  /** Called with the password; reject to show the error and keep the dialog open. */
  onConfirm: (password: string) => Promise<void>;
}

/** Re-authentication before a sensitive change (the API checks the password again). */
export function PasswordConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  destructive,
  onClose,
  onConfirm,
}: Props) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const close = () => {
    setPassword('');
    setError(null);
    onClose();
  };

  const submit = async () => {
    if (busy || !password) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(password);
      setPassword('');
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : close} maxWidth="xs" fullWidth>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (password) void submit();
        }}
      >
        <DialogTitle>{title}</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 2 }}>{description}</DialogContentText>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          <PasswordField
            label="Current password"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="contained"
            color={destructive ? 'error' : 'primary'}
            disabled={busy || !password}
          >
            {busy ? 'Checking…' : confirmLabel}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}
