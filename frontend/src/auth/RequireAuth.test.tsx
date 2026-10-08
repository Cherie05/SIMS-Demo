import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CurrentUser, Permission } from '../types';
import { RequireAuth } from './RequireAuth';

const auth = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock('./AuthContext', () => ({ useAuth: () => auth.value }));

function signedInAs(permissions: Permission[]) {
  const user = { id: 1, name: 'Sam', email: 'sam@example.com', role: 'SALES', permissions } as unknown as CurrentUser;
  auth.value = {
    user,
    initializing: false,
    signedOut: false,
    can: (p: Permission) => permissions.includes(p),
  };
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<p>Sign-in page</p>} />
        <Route path="/" element={<p>Dashboard</p>} />
        <Route element={<RequireAuth />}>
          <Route path="/orders" element={<p>Orders</p>} />
        </Route>
        <Route element={<RequireAuth permission="audit:read" />}>
          <Route path="/audit" element={<p>Audit log</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('RequireAuth', () => {
  beforeEach(() => {
    auth.value = { user: null, initializing: false, signedOut: false, can: () => false };
  });

  it('sends anonymous visitors to the sign-in page', () => {
    renderAt('/orders');
    expect(screen.getByText('Sign-in page')).toBeInTheDocument();
  });

  it('waits while the session is being restored', () => {
    auth.value = { ...auth.value, initializing: true };
    renderAt('/orders');
    expect(screen.getByLabelText('Loading')).toBeInTheDocument();
  });

  it('shows the page to a signed-in user', () => {
    signedInAs(['order:read:own']);
    renderAt('/orders');
    expect(screen.getByText('Orders')).toBeInTheDocument();
  });

  it('keeps users without the permission out of admin pages', () => {
    signedInAs(['order:read:own']);
    renderAt('/audit');
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    signedInAs(['audit:read']);
    renderAt('/audit');
    expect(screen.getByText('Audit log')).toBeInTheDocument();
  });
});
