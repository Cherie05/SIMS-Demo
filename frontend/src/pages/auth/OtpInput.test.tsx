import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { OtpInput } from './OtpInput';

function Harness({ onComplete }: { onComplete: (code: string) => void }) {
  const [value, setValue] = useState('');
  return <OtpInput length={6} value={value} onChange={setValue} onComplete={onComplete} autoFocus />;
}

describe('OtpInput', () => {
  it('moves forward as digits are typed and reports the complete code', async () => {
    const onComplete = vi.fn();
    render(<Harness onComplete={onComplete} />);
    await userEvent.keyboard('482913');
    expect(onComplete).toHaveBeenCalledWith('482913');
    expect(screen.getByLabelText('Digit 6 of 6')).toHaveValue('3');
  });

  it('fills every box from a pasted code', async () => {
    const onComplete = vi.fn();
    render(<Harness onComplete={onComplete} />);
    await userEvent.click(screen.getByLabelText('Digit 1 of 6'));
    await userEvent.paste('123 456');
    expect(onComplete).toHaveBeenCalledWith('123456');
  });

  it('ignores letters', async () => {
    const onComplete = vi.fn();
    render(<Harness onComplete={onComplete} />);
    await userEvent.keyboard('ab12');
    expect(screen.getByLabelText('Digit 1 of 6')).toHaveValue('1');
    expect(onComplete).not.toHaveBeenCalled();
  });
});
