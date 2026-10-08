import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';
import type { ApiErrorBody, Session } from '../types';
import { getSignOutStatus, withSessionLock } from '../auth/sessionIntent';

export const api = axios.create({
  baseURL: '/api/v1',
  timeout: 20000,
  // Required by the cookie-authenticated auth endpoints as a CSRF defence; harmless elsewhere.
  headers: { 'X-Requested-With': 'sims-web' },
});

// The access token lives only in memory, so injected scripts can't lift it from storage.
// A page reload restores the session through the httpOnly refresh cookie.
let accessToken: string | null = null;
let sessionListener: ((session: Session | null) => void) | null = null;
let sessionRevision = 0;

/** AuthProvider subscribes here, so refreshes done by the client keep React state in sync. */
export function setSessionListener(listener: ((session: Session | null) => void) | null) {
  sessionListener = listener;
}

export function applySession(session: Session | null) {
  sessionRevision += 1;
  accessToken = session?.access_token ?? null;
  sessionListener?.(session);
}

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`;
  return config;
});

async function requestRefresh(): Promise<Session | null> {
  // 204 means there is no session cookie at all: the visitor simply isn't signed in.
  const attempt = async () => {
    const response = await api.post<Session>('/auth/refresh');
    return response.status === 204 ? null : response.data;
  };
  try {
    return await attempt();
  } catch (error) {
    // Another tab may have rotated the cookie a moment ago; one retry picks up the new one.
    if (['SESSION_EXPIRED', 'SESSION_REFRESH_RACE'].includes(getErrorCode(error) ?? '')) {
      await new Promise((resolve) => setTimeout(resolve, 400));
      try {
        return await attempt();
      } catch {
        return null;
      }
    }
    return null;
  }
}

let refreshing: Promise<Session | null> | null = null;

/**
 * Get a fresh access token from the refresh cookie. Concurrent callers share one request, and
 * tabs take turns via the Web Locks API so they never present the same refresh token twice.
 */
export function refreshSession(): Promise<Session | null> {
  if (getSignOutStatus()) return Promise.resolve(null);
  if (!refreshing) {
    const revision = sessionRevision;
    const run = withSessionLock(() => (getSignOutStatus() ? Promise.resolve(null) : requestRefresh()));
    refreshing = run
      .then((session) => {
        // A sign-out or new sign-in while refresh was pending takes precedence.
        if (revision !== sessionRevision || getSignOutStatus()) return null;
        applySession(session);
        return session;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

const AUTH_ROUTES = ['/auth/login', '/auth/signup', '/auth/otp/', '/auth/refresh', '/auth/logout', '/auth/config'];

// An expired access token is refreshed once, then the original request is replayed.
api.interceptors.response.use(undefined, async (error: AxiosError<ApiErrorBody>) => {
  const original = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined;
  const isAuthRoute = AUTH_ROUTES.some((route) => original?.url?.startsWith(route));
  if (error.response?.status === 401 && original && !original._retried && !isAuthRoute) {
    original._retried = true;
    const session = await refreshSession();
    if (session) {
      original.headers.Authorization = `Bearer ${session.access_token}`;
      return api(original);
    }
  }
  return Promise.reject(error);
});

export interface FieldError {
  field: string;
  message: string;
}

/** Turn any thrown value into a human readable message using the API's error envelope. */
export function getErrorMessage(error: unknown, fallback = 'Something went wrong'): string {
  if (axios.isAxiosError<ApiErrorBody>(error)) {
    const body = error.response?.data?.error;
    if (body) {
      if (body.code === 'VALIDATION_ERROR' && Array.isArray(body.details) && body.details.length) {
        return (body.details as FieldError[]).map((d) => `${d.field || 'request'}: ${d.message}`).join('; ');
      }
      // Server faults carry a request id that support can look up in the logs.
      const status = error.response?.status ?? 0;
      return status >= 500 && body.request_id
        ? `${body.message} (reference ${body.request_id.slice(0, 8)})`
        : body.message;
    }
    if (error.response?.status === 429) return 'Too many requests. Please wait a moment and try again.';
    if (error.code === 'ECONNABORTED') return 'The server took too long to respond';
    if (!error.response) return 'Cannot reach the server. Check your connection and try again.';
  }
  return error instanceof Error ? error.message : fallback;
}

export function getErrorCode(error: unknown): string | undefined {
  return axios.isAxiosError<ApiErrorBody>(error) ? error.response?.data?.error?.code : undefined;
}

export function getErrorDetails<T = unknown>(error: unknown): T | undefined {
  return axios.isAxiosError<ApiErrorBody>(error) ? (error.response?.data?.error?.details as T) : undefined;
}

/** A unique key per logical submission (Idempotency-Key): a retried request is applied only once. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  // crypto.randomUUID needs a secure context (HTTPS); getRandomValues works everywhere.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}
