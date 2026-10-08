/**
 * Real-user monitoring without a third-party service: JavaScript errors and Core Web Vitals go to
 * the API (/api/v1/telemetry/*), which logs errors as structured events and turns vitals into
 * Prometheus histograms. Reports are fire-and-forget (sendBeacon survives page unloads), deduplicated
 * and capped per page load so a broken loop can't flood the server.
 */
import { onCLS, onFCP, onINP, onLCP, onTTFB, type Metric } from 'web-vitals';

const MAX_REPORTS = 20;
const RELEASE = import.meta.env.VITE_APP_VERSION ?? 'dev';
let sent = 0;
const seen = new Set<string>();

function send(path: string, body: object) {
  if (sent >= MAX_REPORTS) return;
  sent += 1;
  const url = `/api/v1/telemetry/${path}`;
  const json = JSON.stringify(body);
  try {
    const blob = new Blob([json], { type: 'application/json' });
    if (navigator.sendBeacon?.(url, blob)) return;
  } catch {
    // fall through to fetch
  }
  void fetch(url, {
    method: 'POST',
    body: json,
    headers: { 'Content-Type': 'application/json' },
    keepalive: true,
  }).catch(() => undefined);
}

const clip = (value: string | undefined, max: number) => (value ? value.slice(0, max) : undefined);

export function reportClientError(
  kind: 'error' | 'unhandledrejection' | 'boundary',
  error: unknown,
  componentStack?: string | null,
) {
  const err = error instanceof Error ? error : new Error(String(error));
  const key = `${kind}:${err.message}`;
  if (seen.has(key)) return;
  seen.add(key);
  send('client-errors', {
    kind,
    message: clip(err.message || 'Unknown error', 500),
    stack: clip(err.stack, 4000),
    component_stack: clip(componentStack ?? undefined, 2000),
    path: window.location.pathname, // never the query string
    release: clip(RELEASE, 40),
  });
}

function reportVital(metric: Metric) {
  send('web-vitals', {
    name: metric.name,
    value: Math.round(metric.value * (metric.name === 'CLS' ? 1000 : 1)) / (metric.name === 'CLS' ? 1000 : 1),
    rating: metric.rating,
    path: window.location.pathname,
  });
}

/** Call once at start-up. */
export function startTelemetry() {
  window.addEventListener('error', (event) => reportClientError('error', event.error ?? event.message));
  window.addEventListener('unhandledrejection', (event) => reportClientError('unhandledrejection', event.reason));
  onLCP(reportVital);
  onINP(reportVital);
  onCLS(reportVital);
  onFCP(reportVital);
  onTTFB(reportVital);
}
