import { useState } from 'react';
import { Link as RouterLink, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Controller, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Alert, Box, Button, Chip, Divider, Link, Stack, TextField, Typography } from '@mui/material';
import { getErrorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import type { OtpChallenge } from '../../types';
import { AuthHeading, AuthLayout } from './AuthLayout';
import { OtpStep } from './OtpStep';
import { PasswordField } from './PasswordField';
import { useAuthConfig } from './useAuthConfig';

const schema = z.object({
  email: z.string().trim().min(1, 'Email is required').email('Enter a valid email'),
  password: z.string().min(1, 'Password is required'),
});
type FormValues = z.infer<typeof schema>;

const DEMO_ACCOUNTS = [
  { role: 'Admin', email: 'admin@example.com', password: 'Admin@123' },
  { role: 'Manager', email: 'manager@example.com', password: 'Manager@123' },
  { role: 'Sales', email: 'sales@example.com', password: 'Sales@123' },
];

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const config = useAuthConfig();
  const [challenge, setChallenge] = useState<OtpChallenge | null>(null);
  const [error, setError] = useState<string | null>(null);
  const {
    control,
    register,
    handleSubmit,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { email: '', password: '' } });

  const from = (location.state as { from?: string } | null)?.from ?? '/';
  if (user) return <Navigate to={from} replace />;

  const onSubmit = async (values: FormValues) => {
    setError(null);
    try {
      const next = await login(values.email, values.password);
      if (next) setChallenge(next);
      else navigate(from, { replace: true });
    } catch (err) {
      setError(getErrorMessage(err, 'Sign in failed'));
    }
  };

  return (
    <AuthLayout>
      {challenge ? (
        <OtpStep
          challenge={challenge}
          onVerified={() => navigate(from, { replace: true })}
          onStartOver={() => {
            setChallenge(null);
            setValue('password', '');
          }}
        />
      ) : (
        <>
          <AuthHeading title="Welcome back" subtitle="Sign in to manage orders, stock and approvals." />
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          <Box component="form" onSubmit={handleSubmit(onSubmit)} noValidate>
            <Stack spacing={2.25}>
              <TextField
                label="Email"
                type="email"
                autoComplete="username"
                autoFocus
                fullWidth
                {...register('email')}
                error={!!errors.email}
                helperText={errors.email?.message}
              />
              <Controller
                control={control}
                name="password"
                render={({ field }) => (
                  <PasswordField
                    label="Password"
                    autoComplete="current-password"
                    name={field.name}
                    value={field.value}
                    onChange={field.onChange}
                    onBlur={field.onBlur}
                    inputRef={field.ref}
                    error={!!errors.password}
                    helperText={errors.password?.message}
                  />
                )}
              />
              <Box sx={{ textAlign: 'right', mt: -1 }}>
                <Link component={RouterLink} to="/forgot-password" variant="body2" underline="hover">
                  Forgot password?
                </Link>
              </Box>
              <Button type="submit" variant="contained" size="large" disabled={isSubmitting}>
                {isSubmitting ? 'Checking…' : 'Continue'}
              </Button>
            </Stack>
          </Box>

          {config.data?.signup_enabled && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 3, textAlign: 'center' }}>
              New to SIMS?{' '}
              <Link component={RouterLink} to="/signup" underline="hover" sx={{ fontWeight: 600 }}>
                Create an account
              </Link>
            </Typography>
          )}

          {config.data?.demo_accounts && (
            <>
              <Divider sx={{ my: 3 }}>
                <Typography variant="caption" color="text.secondary">
                  Demo accounts
                </Typography>
              </Divider>
              <Stack direction="row" spacing={1} justifyContent="center">
                {DEMO_ACCOUNTS.map((account) => (
                  <Chip
                    key={account.role}
                    label={account.role}
                    variant="outlined"
                    onClick={() => {
                      setValue('email', account.email, { shouldValidate: true });
                      setValue('password', account.password, { shouldValidate: true });
                    }}
                  />
                ))}
              </Stack>
            </>
          )}
        </>
      )}
    </AuthLayout>
  );
}
