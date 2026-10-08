import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { OfflineBanner } from './OfflineBanner';
import { StatusChip } from './StatusChip';

describe('StatusChip', () => {
  it('shows a readable label', () => {
    render(<StatusChip status="PENDING_APPROVAL" />);
    expect(screen.getByText('Pending Approval')).toBeInTheDocument();
  });

  it('renders statuses it does not know instead of crashing', () => {
    render(<StatusChip status="SOMETHING_NEW" />);
    expect(screen.getByText('Something New')).toBeInTheDocument();
  });
});

describe('OfflineBanner', () => {
  it('appears while the browser is offline', async () => {
    const online = Object.getOwnPropertyDescriptor(Navigator.prototype, 'onLine')!;
    let isOnline = true;
    Object.defineProperty(Navigator.prototype, 'onLine', { configurable: true, get: () => isOnline });
    try {
      render(<OfflineBanner />);
      expect(screen.queryByRole('status')).not.toBeInTheDocument();
      await act(async () => {
        isOnline = false;
        window.dispatchEvent(new Event('offline'));
      });
      expect(screen.getByRole('status')).toHaveTextContent(/you're offline/i);
    } finally {
      Object.defineProperty(Navigator.prototype, 'onLine', online);
    }
  });
});
