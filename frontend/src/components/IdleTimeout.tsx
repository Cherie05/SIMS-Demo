import { useCallback, useEffect, useRef, useState } from 'react';
import { useSnackbar } from 'notistack';
import { Button, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle } from '@mui/material';
import { refreshSession } from '../api/client';
import { useAuth } from '../auth/AuthContext';

const WARN_BEFORE_SECONDS = 60;
const KEEPALIVE_EVERY_MS = 10 * 60 * 1000;
const STORAGE_KEY = 'sims.lastActivity';
const EVENTS = ['pointerdown', 'keydown', 'scroll', 'touchstart', 'mousemove'] as const;

function readShared(): number {
  try {
    const stored = Number(localStorage.getItem(STORAGE_KEY));
    return Number.isFinite(stored) && stored > 0 ? Math.min(stored, Date.now()) : 0;
  } catch {
    return 0;
  }
}

function writeShared(at: number) {
  try {
    localStorage.setItem(STORAGE_KEY, String(at));
  } catch {
    // private mode / storage disabled: each tab keeps its own timer
  }
}

/**
 * Signs the user out after `timeoutSeconds` without any activity in any tab, with a one-minute
 * warning. While the user is active, the server session (whose refresh token also expires when
 * idle) is kept alive, so the two timeouts agree.
 */
export function IdleTimeout({ timeoutSeconds }: { timeoutSeconds: number }) {
  const { user, logout } = useAuth();
  const { enqueueSnackbar } = useSnackbar();
  const lastActivity = useRef(Date.now());
  const lastKeepAlive = useRef(Date.now());
  const warning = useRef(false);
  const signingOut = useRef(false);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const userId = user?.id;
  const keepAliveEveryMs = Math.min(KEEPALIVE_EVERY_MS, Math.max(1000, (timeoutSeconds * 1000) / 3));
  const warnBeforeSeconds = Math.min(WARN_BEFORE_SECONDS, Math.floor(timeoutSeconds / 2));

  const markActive = useCallback(() => {
    const now = Date.now();
    lastActivity.current = now;
    if (now - readShared() > 5000) writeShared(now); // throttled: other tabs see it via 'storage'
    if (now - lastKeepAlive.current > keepAliveEveryMs) {
      lastKeepAlive.current = now;
      void refreshSession().catch(() => undefined);
    }
  }, [keepAliveEveryMs]);

  useEffect(() => {
    if (!userId) return;
    lastActivity.current = Date.now();
    lastKeepAlive.current = Date.now();
    warning.current = false;
    signingOut.current = false;
    writeShared(lastActivity.current);
    const onActivity = () => {
      if (!warning.current && !signingOut.current) markActive();
    };
    const onStorage = (event: StorageEvent) => {
      const at = Number(event.newValue);
      if (event.key === STORAGE_KEY && Number.isFinite(at) && at > 0)
        lastActivity.current = Math.max(lastActivity.current, Math.min(at, Date.now()));
    };
    EVENTS.forEach((name) => window.addEventListener(name, onActivity, { passive: true }));
    window.addEventListener('storage', onStorage);
    const timer = window.setInterval(() => {
      const idleFor = (Date.now() - Math.max(lastActivity.current, readShared())) / 1000;
      const left = Math.ceil(timeoutSeconds - idleFor);
      if (left <= 0) {
        if (signingOut.current) return;
        signingOut.current = true;
        warning.current = false;
        setSecondsLeft(null);
        void logout().then(() =>
          enqueueSnackbar(`You were signed out after ${Math.round(timeoutSeconds / 60)} minutes of inactivity`, {
            variant: 'info',
          }),
        );
      } else {
        warning.current = left <= warnBeforeSeconds;
        setSecondsLeft(left <= warnBeforeSeconds ? left : null);
      }
    }, 1000);
    return () => {
      EVENTS.forEach((name) => window.removeEventListener(name, onActivity));
      window.removeEventListener('storage', onStorage);
      window.clearInterval(timer);
    };
  }, [userId, timeoutSeconds, warnBeforeSeconds, logout, enqueueSnackbar, markActive]);

  if (!user || secondsLeft === null) return null;
  return (
    <Dialog open aria-labelledby="idle-title" aria-describedby="idle-text">
      <DialogTitle id="idle-title">Are you still there?</DialogTitle>
      <DialogContent>
        <DialogContentText id="idle-text">
          For your security you'll be signed out in {secondsLeft} second{secondsLeft === 1 ? '' : 's'} because there has
          been no activity.
        </DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => void logout()}>Sign out now</Button>
        <Button
          variant="contained"
          autoFocus
          onClick={() => {
            lastKeepAlive.current = 0; // refresh the server session straight away
            warning.current = false;
            setSecondsLeft(null);
            markActive();
          }}
        >
          Stay signed in
        </Button>
      </DialogActions>
    </Dialog>
  );
}
