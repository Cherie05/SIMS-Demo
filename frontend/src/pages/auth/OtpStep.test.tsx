import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SnackbarProvider } from 'notistack';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { OtpChallenge } from '../../types';
import { OtpStep } from './OtpStep';

const auth = vi.hoisted(() => ({
  verifyOtp: vi.fn(),
  verifyRecoveryCode: vi.fn(),
  resendOtp: vi.fn(),
}));
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => auth }));

const base: OtpChallenge = {
  otp_required: true,
  challenge_id: 'challenge-0123456789abcdef',
  purpose: 'LOGIN',
  method: 'code',
  delivery: 'log',
  destination: 'sa***@example.com',
  expires_in: 300,
  resend_available_in: 30,
  code_length: 6,
};

function renderStep(challenge: OtpChallenge) {
  const onVerified = vi.fn();
  render(
    <SnackbarProvider>
      <OtpStep challenge={challenge} onVerified={onVerified} onStartOver={vi.fn()} />
    </SnackbarProvider>,
  );
  return onVerified;
}

describe('OtpStep', () => {
  beforeEach(() => {
    Object.values(auth).forEach((fn) => fn.mockReset());
  });

  it('explains where a logged code can be found and verifies it', async () => {
    auth.verifyOtp.mockResolvedValue({ id: 1 });
    const onVerified = renderStep(base);
    expect(screen.getByText(/server log/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /resend in/i })).toBeDisabled();
    await userEvent.keyboard('123456');
    expect(auth.verifyOtp).toHaveBeenCalledWith(base.challenge_id, '123456');
    expect(onVerified).toHaveBeenCalled();
  });

  it('uses the authenticator app and offers recovery codes instead of resending', async () => {
    auth.verifyRecoveryCode.mockResolvedValue({ id: 1 });
    const onVerified = renderStep({
      ...base,
      method: 'totp',
      delivery: 'authenticator',
      destination: null,
      resend_available_in: 0,
    });
    expect(screen.getByText(/authenticator app/i, { selector: 'strong' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /resend/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Use a recovery code' }));
    await userEvent.type(screen.getByLabelText('Recovery code'), 'abcde-23456');
    await userEvent.click(screen.getByRole('button', { name: 'Use recovery code' }));
    expect(auth.verifyRecoveryCode).toHaveBeenCalledWith(base.challenge_id, 'abcde-23456');
    expect(onVerified).toHaveBeenCalled();
  });

  it('blocks duplicate resends and code verification while a replacement code is pending', async () => {
    let finish!: (challenge: OtpChallenge) => void;
    auth.resendOtp.mockReturnValue(
      new Promise<OtpChallenge>((resolve) => {
        finish = resolve;
      }),
    );
    renderStep({ ...base, resend_available_in: 0 });
    const resend = screen.getByRole('button', { name: 'Resend code' });
    fireEvent.click(resend);
    expect(resend).toBeDisabled();
    expect(screen.getByLabelText('Digit 1 of 6')).toBeDisabled();
    fireEvent.click(resend);
    expect(auth.resendOtp).toHaveBeenCalledTimes(1);
    await act(async () => {
      finish(base);
    });
    expect(screen.getByRole('button', { name: /resend in/i })).toBeDisabled();
    expect(screen.getByLabelText('Digit 1 of 6')).toBeEnabled();
  });
});
