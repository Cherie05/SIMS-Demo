/** Nonsecret browser intent: a failed server logout must not silently sign the user back in. */
export const SIGN_OUT_STORAGE_KEY = 'sims.signOut';
export type SignOutStatus = 'pending' | 'complete';
let fallbackStatus: SignOutStatus | null = null;

export function getSignOutStatus(): SignOutStatus | null {
  try {
    const value = localStorage.getItem(SIGN_OUT_STORAGE_KEY);
    return value === 'pending' || value === 'complete' ? value : null;
  } catch {
    return fallbackStatus;
  }
}

export function setSignOutStatus(status: SignOutStatus | null) {
  fallbackStatus = status;
  try {
    if (status) localStorage.setItem(SIGN_OUT_STORAGE_KEY, status);
    else localStorage.removeItem(SIGN_OUT_STORAGE_KEY);
  } catch {
    // Storage-disabled browsers retain the intent for the current page.
  }
}

let operations: Promise<unknown> = Promise.resolve();

/** Serialize refresh, cookie revocation and explicit sign-in within and across browser tabs. */
export function withSessionLock<T>(action: () => Promise<T>): Promise<T> {
  const run = () => {
    const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
    return locks ? locks.request('sims-session-refresh', action) : action();
  };
  const operation = operations.then(run, run);
  operations = operation.catch(() => undefined);
  return operation;
}
