import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IdleTimeout } from './IdleTimeout';

const mocks = vi.hoisted(() => ({ logout: vi.fn(), refresh: vi.fn(), notify: vi.fn() }));
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 1 }, logout: mocks.logout }) }));
vi.mock('../api/client', () => ({ refreshSession: mocks.refresh }));
vi.mock('notistack', () => ({ useSnackbar: () => ({ enqueueSnackbar: mocks.notify }) }));

describe('IdleTimeout', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-07T12:00:00Z'));
    localStorage.clear();
    mocks.logout.mockReset().mockResolvedValue(undefined);
    mocks.refresh.mockReset().mockResolvedValue(null);
    mocks.notify.mockReset();
  });

  afterEach(() => vi.useRealTimers());

  it('counts down to one sign-out without resetting activity on warning renders', async () => {
    render(<IdleTimeout timeoutSeconds={120} />);
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByText(/signed out in 60 seconds/)).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });
    expect(screen.getByText(/signed out in 30 seconds/)).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });
    expect(mocks.logout).toHaveBeenCalledTimes(1);
    await act(async () => {
      vi.advanceTimersByTime(5_000);
    });
    expect(mocks.logout).toHaveBeenCalledTimes(1);
  });

  it('renews both local activity and the server session when the user stays signed in', async () => {
    render(<IdleTimeout timeoutSeconds={120} />);
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Stay signed in' }));
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
    await act(async () => {
      vi.advanceTimersByTime(59_000);
    });
    expect(mocks.logout).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(61_000);
    });
    expect(mocks.logout).toHaveBeenCalledTimes(1);
  });

  it('keeps active sessions alive when the configured idle timeout is shorter than ten minutes', async () => {
    render(<IdleTimeout timeoutSeconds={120} />);
    await act(async () => {
      vi.advanceTimersByTime(45_000);
    });
    fireEvent.pointerDown(window);
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
    await act(async () => {
      vi.advanceTimersByTime(59_000);
    });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(mocks.logout).not.toHaveBeenCalled();
  });
});
