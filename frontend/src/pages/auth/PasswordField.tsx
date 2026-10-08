import { forwardRef, useState } from 'react';
import { Box, IconButton, InputAdornment, Stack, TextField, Typography, type TextFieldProps } from '@mui/material';
import Visibility from '@mui/icons-material/VisibilityOutlined';
import VisibilityOff from '@mui/icons-material/VisibilityOffOutlined';
import CheckIcon from '@mui/icons-material/CheckCircle';
import DotIcon from '@mui/icons-material/RadioButtonUnchecked';
import { brand } from '../../theme';
import { meetsPasswordPolicy, PASSWORD_RULES } from './passwordPolicy';

function strength(value: string): { score: number; label: string; color: string } {
  if (!value) return { score: 0, label: '', color: brand.lineStrong };
  if (!meetsPasswordPolicy(value)) return { score: 1, label: 'Too weak', color: brand.danger };
  let score = 2;
  if (value.length >= 12) score += 1;
  if (/[a-z]/.test(value) && /[A-Z]/.test(value) && /[^A-Za-z0-9]/.test(value)) score += 1;
  return score === 2
    ? { score, label: 'Fair', color: '#c27a0e' }
    : score === 3
      ? { score, label: 'Good', color: '#3fa597' }
      : { score, label: 'Strong', color: brand.teal };
}

type Props = TextFieldProps & { showStrength?: boolean; value?: string };

export const PasswordField = forwardRef<HTMLDivElement, Props>(function PasswordField(
  { showStrength, value = '', slotProps, ...props },
  ref,
) {
  const [visible, setVisible] = useState(false);
  const meter = strength(value);
  return (
    <Box>
      <TextField
        {...props}
        ref={ref}
        value={value}
        type={visible ? 'text' : 'password'}
        fullWidth
        slotProps={{
          ...slotProps,
          input: {
            endAdornment: (
              <InputAdornment position="end">
                <IconButton
                  onClick={() => setVisible((v) => !v)}
                  edge="end"
                  aria-label={visible ? 'Hide password' : 'Show password'}
                >
                  {visible ? <VisibilityOff /> : <Visibility />}
                </IconButton>
              </InputAdornment>
            ),
          },
        }}
      />
      {showStrength && (
        <Box sx={{ mt: 1.25 }}>
          <Stack direction="row" spacing={0.75} alignItems="center">
            {[1, 2, 3, 4].map((step) => (
              <Box
                key={step}
                sx={{
                  flex: 1,
                  height: 4,
                  borderRadius: 2,
                  bgcolor: step <= meter.score ? meter.color : brand.line,
                  transition: 'background-color .2s',
                }}
              />
            ))}
            <Typography
              variant="caption"
              sx={{ minWidth: 56, textAlign: 'right', fontWeight: 600, color: meter.color }}
            >
              {meter.label}
            </Typography>
          </Stack>
          <Stack component="ul" spacing={0.5} sx={{ listStyle: 'none', p: 0, m: 0, mt: 1 }}>
            {PASSWORD_RULES.map((rule) => {
              const ok = Boolean(value) && rule.test(value);
              return (
                <Stack key={rule.label} component="li" direction="row" spacing={0.75} alignItems="center">
                  {ok ? (
                    <CheckIcon sx={{ fontSize: 15, color: brand.teal }} />
                  ) : (
                    <DotIcon sx={{ fontSize: 15, color: brand.muted }} />
                  )}
                  <Typography variant="caption" color={ok ? 'text.primary' : 'text.secondary'}>
                    {rule.label}
                  </Typography>
                </Stack>
              );
            })}
          </Stack>
        </Box>
      )}
    </Box>
  );
});
