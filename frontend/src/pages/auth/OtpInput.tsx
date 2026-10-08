import { useRef, type ClipboardEvent, type KeyboardEvent } from 'react';
import { Box } from '@mui/material';
import { brand } from '../../theme';

interface Props {
  length: number;
  value: string;
  onChange: (value: string) => void;
  onComplete?: (value: string) => void;
  disabled?: boolean;
  error?: boolean;
  autoFocus?: boolean;
}

/**
 * One box per digit: typing moves forward, Backspace moves back, and pasting (or the phone's
 * one-time-code autofill) fills every box at once.
 */
export function OtpInput({ length, value, onChange, onComplete, disabled, error, autoFocus }: Props) {
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const digits = Array.from({ length }, (_, i) => value[i] ?? '');

  const focus = (index: number) => inputs.current[Math.max(0, Math.min(length - 1, index))]?.focus();

  const commit = (next: string, focusIndex: number) => {
    onChange(next);
    focus(focusIndex);
    if (next.length === length) onComplete?.(next);
  };

  /** One typed digit replaces only its box; several (paste, autofill) fill from that box onwards. */
  const setFrom = (index: number, entered: string) => {
    let clean = entered.replace(/\D/g, '');
    if (!clean) return;
    if (clean.length === 2 && digits[index]) clean = clean.replace(digits[index], '') || clean[1]; // typed over a digit
    const start = Math.min(index, value.length); // never leave gaps
    if (clean.length === 1) {
      commit((value.slice(0, start) + clean + value.slice(start + 1)).slice(0, length), start + 1);
    } else {
      const next = (value.slice(0, start) + clean).slice(0, length);
      commit(next, next.length);
    }
  };

  const handleKeyDown = (index: number, event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Backspace') {
      event.preventDefault();
      if (digits[index]) {
        onChange(value.slice(0, index) + value.slice(index + 1));
      } else if (index > 0) {
        onChange(value.slice(0, index - 1) + value.slice(index));
        focus(index - 1);
      }
    } else if (event.key === 'ArrowLeft') {
      focus(index - 1);
    } else if (event.key === 'ArrowRight') {
      focus(index + 1);
    }
  };

  const handlePaste = (index: number, event: ClipboardEvent<HTMLInputElement>) => {
    event.preventDefault();
    setFrom(index, event.clipboardData.getData('text'));
  };

  return (
    <Box role="group" aria-label={`${length}-digit code`} sx={{ display: 'flex', gap: { xs: 1, sm: 1.25 } }}>
      {digits.map((digit, index) => (
        <Box
          key={index}
          component="input"
          ref={(el: HTMLInputElement | null) => {
            inputs.current[index] = el;
          }}
          value={digit}
          onChange={(e) => setFrom(index, e.target.value)}
          onKeyDown={(e) => handleKeyDown(index, e)}
          onPaste={(e) => handlePaste(index, e)}
          onFocus={(e) => e.target.select()}
          inputMode="numeric"
          pattern="[0-9]*"
          autoComplete={index === 0 ? 'one-time-code' : 'off'}
          autoFocus={autoFocus && index === 0}
          disabled={disabled}
          aria-label={`Digit ${index + 1} of ${length}`}
          aria-invalid={error || undefined}
          sx={{
            width: '100%',
            minWidth: 0,
            height: { xs: 52, sm: 58 },
            textAlign: 'center',
            fontSize: { xs: 22, sm: 26 },
            fontWeight: 700,
            fontFamily: 'inherit',
            color: brand.ink,
            border: `1.5px solid ${error ? brand.danger : digit ? brand.teal : brand.lineStrong}`,
            borderRadius: 2,
            outline: 'none',
            bgcolor: disabled ? '#f6f7f7' : '#fff',
            transition: 'border-color .15s, box-shadow .15s',
            '&:focus': {
              borderColor: error ? brand.danger : brand.teal,
              boxShadow: `0 0 0 4px ${error ? 'rgba(214,69,69,.15)' : 'rgba(15,139,125,.16)'}`,
            },
          }}
        />
      ))}
    </Box>
  );
}
