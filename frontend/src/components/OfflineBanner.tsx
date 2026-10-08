import { useSyncExternalStore } from 'react';
import { Alert, Collapse } from '@mui/material';
import CloudOffIcon from '@mui/icons-material/CloudOffOutlined';

function subscribe(onChange: () => void) {
  window.addEventListener('online', onChange);
  window.addEventListener('offline', onChange);
  return () => {
    window.removeEventListener('online', onChange);
    window.removeEventListener('offline', onChange);
  };
}

function useOnline(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => navigator.onLine,
    () => true,
  );
}

/** Tells the user why nothing loads or saves while the connection is down (queries pause and resume). */
export function OfflineBanner() {
  const online = useOnline();
  return (
    <Collapse in={!online} unmountOnExit>
      <Alert severity="warning" icon={<CloudOffIcon fontSize="inherit" />} role="status" sx={{ borderRadius: 0 }}>
        You're offline. Changes can't be saved until the connection is back; this page will refresh itself.
      </Alert>
    </Collapse>
  );
}
