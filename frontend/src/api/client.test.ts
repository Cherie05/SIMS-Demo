import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Session } from '../types';
import { setSignOutStatus } from '../auth/sessionIntent';
import {
  api,
  applySession,
  getErrorCode,
  getErrorDetails,
  getErrorMessage,
  newIdempotencyKey,
  refreshSession,
  setSessionListener,
} from './client';

function apiError(status: number, error?: object): AxiosError {
  const response = {
    status,
    statusText: '',
    headers: {},
    config: { headers: new AxiosHeaders() },
    data: error ? { error } : undefined,
  } as AxiosResponse;
  return new AxiosError('Request failed', 'ERR_BAD_RESPONSE', response.config, null, response);
}

describe('getErrorMessage', () => {
  it('uses the message from the API error envelope', () => {
    expect(getErrorMessage(apiError(409, { code: 'INSUFFICIENT_STOCK', message: 'Not enough stock' }))).toBe(
      'Not enough stock',
    );
  });

  it('lists every field of a validation error', () => {
    const error = apiError(422, {
      code: 'VALIDATION_ERROR',
      message: 'Request validation failed',
      details: [
        { field: 'email', message: 'value is not a valid email address' },
        { field: 'items', message: 'List should have at least 1 item' },
      ],
    });
    expect(getErrorMessage(error)).toBe(
      'email: value is not a valid email address; items: List should have at least 1 item',
    );
  });

  it('adds a support reference to server errors', () => {
    const error = apiError(500, {
      code: 'INTERNAL_ERROR',
      message: 'An unexpected error occurred',
      request_id: 'abcdef1234567890',
    });
    expect(getErrorMessage(error)).toBe('An unexpected error occurred (reference abcdef12)');
  });

  it('explains rate limiting and lost connections', () => {
    expect(getErrorMessage(apiError(429))).toMatch(/too many requests/i);
    const offline = new AxiosError('Network Error', 'ERR_NETWORK');
    expect(getErrorMessage(offline)).toMatch(/cannot reach the server/i);
  });

  it('exposes the error code and details', () => {
    const error = apiError(400, {
      code: 'OTP_INCORRECT',
      message: 'Incorrect code',
      details: { remaining_attempts: 2 },
    });
    expect(getErrorCode(error)).toBe('OTP_INCORRECT');
    expect(getErrorDetails<{ remaining_attempts: number }>(error)?.remaining_attempts).toBe(2);
  });
});

describe('newIdempotencyKey', () => {
  it('creates unique keys the API accepts', () => {
    const keys = new Set(Array.from({ length: 200 }, () => newIdempotencyKey()));
    expect(keys.size).toBe(200);
    for (const key of keys) expect(key).toMatch(/^[A-Za-z0-9._:-]{8,255}$/);
  });
});

describe('session refresh', () => {
  const originalAdapter = api.defaults.adapter;
  beforeEach(() => setSignOutStatus(null));
  afterEach(() => {
    setSessionListener(null);
    applySession(null);
    api.defaults.adapter = originalAdapter;
    setSignOutStatus(null);
  });

  it('does not restore a session after the user signs out while refresh is pending', async () => {
    let finish!: (session: Session) => void;
    const response = new Promise<Session>((resolve) => {
      finish = resolve;
    });
    const adapter = vi.fn(async (config) => ({
      data: await response,
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    }));
    api.defaults.adapter = adapter;
    const listener = vi.fn();
    setSessionListener(listener);
    const refresh = refreshSession();
    await vi.waitFor(() => expect(adapter).toHaveBeenCalledTimes(1));
    applySession(null);
    finish({ access_token: 'refreshed-token', user: { id: 1 } } as Session);
    expect(await refresh).toBeNull();
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenLastCalledWith(null);
  });

  it('does not contact refresh when a previous offline sign-out is persisted', async () => {
    const adapter = vi.fn();
    api.defaults.adapter = adapter;
    setSignOutStatus('pending');
    expect(await refreshSession()).toBeNull();
    expect(adapter).not.toHaveBeenCalled();
  });

  it('retries a benign cookie-rotation race using the newly shared cookie', async () => {
    const session = { access_token: 'rotated-token', user: { id: 1 } } as Session;
    const race = apiError(401, { code: 'SESSION_REFRESH_RACE', message: 'Refresh is in progress' });
    race.config!.url = '/auth/refresh';
    const adapter = vi
      .fn()
      .mockRejectedValueOnce(race)
      .mockImplementationOnce(async (config) => ({
        data: session,
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      }));
    api.defaults.adapter = adapter;
    expect(await refreshSession()).toEqual(session);
    expect(adapter).toHaveBeenCalledTimes(2);
  });
});
