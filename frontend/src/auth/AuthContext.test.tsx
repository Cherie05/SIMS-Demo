import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Session } from '../types';
import { AuthProvider, useAuth } from './AuthContext';
import { getSignOutStatus, setSignOutStatus, SIGN_OUT_STORAGE_KEY } from './sessionIntent';

const client = vi.hoisted(() => ({
  listener: null as ((session: Session | null) => void) | null,
  refresh: vi.fn(),
  logout: vi.fn(),
  login: vi.fn(),
}));
vi.mock('../api/client', () => ({
  setSessionListener: (listener: typeof client.listener) => {
    client.listener = listener;
  },
  refreshSession: client.refresh,
  applySession: (session: Session | null) => client.listener?.(session),
}));
vi.mock('../api/endpoints', () => ({ authApi: { logout: client.logout, login: client.login } }));

function Profile() {
  const { user, logout, login } = useAuth();
  return (
    <>
      <span>{user?.name ?? 'Signed out'}</span>
      <button onClick={() => void logout()}>Sign out</button>
      <button onClick={() => void login('user@example.com', 'Password1!').catch(() => undefined)}>Sign in</button>
    </>
  );
}

const first = { otp_required: false, user: { id: 1, name: 'First user' }, access_token: 'first' } as Session;

function renderProfile() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <Profile />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe('AuthProvider cache isolation', () => {
  beforeEach(() => {
    setSignOutStatus(null);
    client.refresh.mockReset().mockResolvedValue(null);
    client.logout.mockReset().mockResolvedValue(undefined);
    client.login.mockReset().mockResolvedValue(first);
  });

  it('clears the previous account data when a different user signs in through another tab', async () => {
    const queries = new QueryClient();
    render(
      <QueryClientProvider client={queries}>
        <AuthProvider>
          <Profile />
        </AuthProvider>
      </QueryClientProvider>,
    );
    await act(async () => {
      client.listener?.(first);
    });
    queries.setQueryData(['orders'], { private: 'First user orders' });
    await act(async () => {
      client.listener?.({ ...first, access_token: 'refreshed' });
    });
    expect(queries.getQueryData(['orders'])).toEqual({ private: 'First user orders' });
    await act(async () => {
      client.listener?.({ user: { id: 2, name: 'Second user' }, access_token: 'second' } as Session);
    });
    expect(queries.getQueryData(['orders'])).toBeUndefined();
    expect(screen.getByText('Second user')).toBeInTheDocument();
  });

  it('persists offline sign-out across reloads, revokes on reconnect, and requires explicit sign-in', async () => {
    client.logout.mockRejectedValue(new Error('Offline'));
    const initial = renderProfile();
    await act(async () => {
      client.listener?.(first);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    await waitFor(() => expect(client.logout).toHaveBeenCalledTimes(1));
    expect(screen.getByText('Signed out')).toBeInTheDocument();
    expect(getSignOutStatus()).toBe('pending');
    initial.unmount();
    client.refresh.mockClear();
    renderProfile();
    await waitFor(() => expect(client.logout).toHaveBeenCalledTimes(2));
    expect(client.refresh).not.toHaveBeenCalled();
    expect(screen.getByText('Signed out')).toBeInTheDocument();
    client.logout.mockResolvedValue(undefined);
    fireEvent(window, new Event('online'));
    await waitFor(() => expect(getSignOutStatus()).toBe('complete'));
    expect(client.refresh).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(screen.getByText('First user')).toBeInTheDocument());
    expect(getSignOutStatus()).toBeNull();
  });

  it('signs out another tab when the shared marker changes', async () => {
    renderProfile();
    await act(async () => {
      client.listener?.(first);
    });
    setSignOutStatus('pending');
    fireEvent(window, new StorageEvent('storage', { key: SIGN_OUT_STORAGE_KEY, newValue: 'pending' }));
    expect(screen.getByText('Signed out')).toBeInTheDocument();
  });

  it('finishes deferred revocation before creating a new signed-in session', async () => {
    let finish!: () => void;
    client.logout.mockReturnValue(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );
    renderProfile();
    await act(async () => {
      client.listener?.(first);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    await waitFor(() => expect(client.logout).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await act(async () => {});
    expect(client.login).not.toHaveBeenCalled();
    await act(async () => {
      finish();
    });
    await waitFor(() => expect(screen.getByText('First user')).toBeInTheDocument());
    expect(client.logout).toHaveBeenCalledTimes(1);
    expect(getSignOutStatus()).toBeNull();
  });

  it('keeps a later sign-out authoritative when an earlier sign-in response is still pending', async () => {
    let finish!: (session: Session) => void;
    client.login.mockReturnValue(
      new Promise<Session>((resolve) => {
        finish = resolve;
      }),
    );
    renderProfile();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(client.login).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    await act(async () => {
      finish(first);
    });
    await waitFor(() => expect(client.logout).toHaveBeenCalledTimes(1));
    expect(screen.getByText('Signed out')).toBeInTheDocument();
    expect(getSignOutStatus()).toBe('complete');
  });
});
