import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { applySession, refreshSession, setSessionListener } from '../api/client';
import { authApi, type SignupInput } from '../api/endpoints';
import type { CurrentUser, OtpChallenge, Permission, Role, Session } from '../types';
import {
  getSignOutStatus,
  setSignOutStatus,
  SIGN_OUT_STORAGE_KEY,
  withSessionLock,
  type SignOutStatus,
} from './sessionIntent';

interface AuthState {
  user: CurrentUser | null;
  /** True until the first session restore (from the refresh cookie) has finished. */
  initializing: boolean;
  /** True after a deliberate sign-out (as opposed to an expired session). */
  signedOut: boolean;
  /** Password step. Resolves to the second-factor challenge, or null if already signed in. */
  login: (email: string, password: string) => Promise<OtpChallenge | null>;
  signup: (data: SignupInput) => Promise<OtpChallenge>;
  verifyOtp: (challengeId: string, code: string) => Promise<CurrentUser>;
  verifyRecoveryCode: (challengeId: string, recoveryCode: string) => Promise<CurrentUser>;
  resendOtp: (challengeId: string) => Promise<OtpChallenge>;
  logout: () => Promise<void>;
  /** Forget the local session without calling the API (it has already ended server-side). */
  endLocalSession: () => void;
  /** Re-read the profile (after enabling an authenticator app, changing the password...). */
  reloadUser: () => Promise<void>;
  hasRole: (...roles: Role[]) => boolean;
  /** Permission check for rendering; the API enforces the same rules. */
  can: (permission: Permission) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);
const TAB_CHANNEL = 'sims-auth';

/** Caller holds the shared session lock, so revocation cannot erase a newer sign-in cookie. */
async function revokePendingLogout() {
  if (getSignOutStatus() !== 'pending') return;
  await authApi.logout();
  setSignOutStatus('complete');
}

const retryPendingLogout = () => withSessionLock(revokePendingLogout);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [signedOut, setSignedOut] = useState(() => Boolean(getSignOutStatus()));
  const channel = useRef<BroadcastChannel | null>(null);
  const activeUserId = useRef<number | null>(null);

  // The API client owns the token; mirror its session into React state.
  useEffect(() => {
    setSessionListener((session) => {
      const nextUserId = session?.user.id ?? null;
      if (!session || (activeUserId.current !== null && activeUserId.current !== nextUserId)) queryClient.clear();
      activeUserId.current = nextUserId;
      setUser(session?.user ?? null);
      if (session) setSignedOut(false);
    });
    return () => setSessionListener(null);
  }, [queryClient]);

  // Restore the session after a reload (the access token only ever lived in memory).
  useEffect(() => {
    if (getSignOutStatus()) {
      setInitializing(false);
      void retryPendingLogout().catch(() => undefined);
    } else {
      void refreshSession()
        .catch(() => applySession(null))
        .finally(() => setInitializing(false));
    }
  }, []);

  // Keep tabs in step: signing out in one tab signs out the others; signing in is picked up too.
  useEffect(() => {
    const onSignOut = () => {
      setSignedOut(true);
      applySession(null);
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key !== SIGN_OUT_STORAGE_KEY) return;
      if (getSignOutStatus()) onSignOut();
      else void refreshSession().catch(() => undefined);
    };
    const onOnline = () => {
      void retryPendingLogout().catch(() => undefined);
    };
    window.addEventListener('storage', onStorage);
    window.addEventListener('online', onOnline);
    let tabs: BroadcastChannel | null = null;
    try {
      if (typeof BroadcastChannel !== 'undefined') tabs = new BroadcastChannel(TAB_CHANNEL);
    } catch {
      // The storage listener still synchronizes tabs when browser policy disables this API.
    }
    if (tabs)
      tabs.onmessage = (event) => {
        if (event.data === 'signed-out') {
          if (!getSignOutStatus()) return; // Ignore an older message after a newer explicit sign-in.
          onSignOut();
        } else if (event.data === 'signed-in') {
          void refreshSession().catch(() => undefined);
        }
      };
    channel.current = tabs;
    return () => {
      channel.current = null;
      tabs?.close();
      window.removeEventListener('storage', onStorage);
      window.removeEventListener('online', onOnline);
    };
  }, []);

  const establish = useCallback((session: Session, expectedIntent: SignOutStatus | null) => {
    if (getSignOutStatus() !== expectedIntent)
      throw new Error('Sign-in was cancelled by a sign-out. Please sign in again.');
    setSignOutStatus(null);
    setSignedOut(false);
    applySession(session);
    channel.current?.postMessage('signed-in');
    return session.user;
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      return withSessionLock(async () => {
        await revokePendingLogout();
        const intent = getSignOutStatus();
        const result = await authApi.login(email, password);
        if (result.otp_required) return result;
        establish(result, intent);
        return null;
      });
    },
    [establish],
  );

  const signup = useCallback(
    (data: SignupInput) =>
      withSessionLock(async () => {
        await revokePendingLogout();
        return authApi.signup(data);
      }),
    [],
  );

  const verifyOtp = useCallback(
    async (challengeId: string, code: string) =>
      withSessionLock(async () => {
        await revokePendingLogout();
        const intent = getSignOutStatus();
        return establish(await authApi.verifyOtp(challengeId, code), intent);
      }),
    [establish],
  );

  const verifyRecoveryCode = useCallback(
    async (challengeId: string, recoveryCode: string) =>
      withSessionLock(async () => {
        await revokePendingLogout();
        const intent = getSignOutStatus();
        return establish(await authApi.verifyRecoveryCode(challengeId, recoveryCode), intent);
      }),
    [establish],
  );

  const resendOtp = useCallback((challengeId: string) => authApi.resendOtp(challengeId), []);

  const endLocalSession = useCallback(() => {
    setSignOutStatus('complete');
    setSignedOut(true);
    applySession(null);
    channel.current?.postMessage('signed-out');
  }, []);

  const logout = useCallback(async () => {
    setSignOutStatus('pending');
    setSignedOut(true);
    applySession(null);
    channel.current?.postMessage('signed-out');
    try {
      await retryPendingLogout(); // revokes the session server-side and clears the cookie
    } catch {
      // Keep the marker across reloads, and retry revocation when connectivity returns.
    }
  }, []);

  const reloadUser = useCallback(async () => {
    const expectedUserId = activeUserId.current;
    const fresh = await authApi.me();
    if (expectedUserId !== null && activeUserId.current === expectedUserId) setUser(fresh);
  }, []);

  const hasRole = useCallback((...roles: Role[]) => Boolean(user && roles.includes(user.role)), [user]);
  const can = useCallback((permission: Permission) => Boolean(user?.permissions?.includes(permission)), [user]);

  const value = useMemo(
    () => ({
      user,
      initializing,
      signedOut,
      login,
      signup,
      verifyOtp,
      verifyRecoveryCode,
      resendOtp,
      logout,
      endLocalSession,
      reloadUser,
      hasRole,
      can,
    }),
    [
      user,
      initializing,
      signedOut,
      login,
      signup,
      verifyOtp,
      verifyRecoveryCode,
      resendOtp,
      logout,
      endLocalSession,
      reloadUser,
      hasRole,
      can,
    ],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>');
  return context;
}
