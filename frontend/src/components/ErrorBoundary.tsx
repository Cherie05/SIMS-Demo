import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Alert, AlertTitle, Box, Button } from '@mui/material';
import { reportClientError } from '../api/telemetry';

interface Props {
  children: ReactNode;
  /** When this value changes (e.g. the route), a crashed subtree gets another chance to render. */
  resetKey?: unknown;
}

interface State {
  error: Error | null;
}

/** Catches render errors so one broken screen shows a message instead of a blank app. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Sent to the API's telemetry endpoint (structured log + metric), not the console.
    reportClientError('boundary', error, info.componentStack);
  }

  componentDidUpdate(prevProps: Props) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <Box sx={{ p: 3, maxWidth: 560, mx: 'auto', mt: 6 }}>
        <Alert
          severity="error"
          action={
            <Button color="inherit" size="small" onClick={() => window.location.reload()}>
              Reload
            </Button>
          }
        >
          <AlertTitle>Something went wrong on this screen</AlertTitle>
          Try reloading the page. If it keeps happening, please contact support.
        </Alert>
      </Box>
    );
  }
}
