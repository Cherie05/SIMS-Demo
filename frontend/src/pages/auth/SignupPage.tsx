import { useState } from 'react';
import { Link as RouterLink, Navigate, useNavigate } from 'react-router-dom';
import { Controller, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useSnackbar } from 'notistack';
import { Alert, Box, Button, Link, Skeleton, Stack, TextField, Typography } from '@mui/material';
import { getErrorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { applyServerErrors } from '../../utils/forms';
import type { OtpChallenge } from '../../types';
import { AuthHeading, AuthLayout } from './AuthLayout';
import { OtpStep } from './OtpStep';
import { PasswordField } from './PasswordField';
import { meetsPasswordPolicy } from './passwordPolicy';
import { useAuthConfig } from './useAuthConfig';

const schema = z
  .object({
    name: z.string().trim().min(2, 'At least 2 characters').max(120),
    email: z.string().trim().min(1, 'Email is required').email('Enter a valid email'),
    password: z.string().refine(meetsPasswordPolicy, 'Choose a password that meets the rules below'),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, { path: ['confirm'], message: 'Passwords do not match' });
type FormValues = z.infer<typeof schema>;

export default function SignupPage() {
  const { user, signup } = useAuth();
  const navigate = useNavigate();
  const { enqueueSnackbar } = useSnackbar();
  const config = useAuthConfig();
  const [challenge, setChallenge] = useState<OtpChallenge | null>(null);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: '', email: '', password: '', confirm: '' },
  });
  const {
    control,
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = form;

  if (user) return <Navigate to="/" replace />;

  const domains = config.data?.signup_allowed_domains ?? [];

  const onSubmit = async (values: FormValues) => {
    setError(null);
    try {
      setChallenge(await signup({ name: values.name, email: values.email, password: values.password }));
    } catch (err) {
      if (!applyServerErrors(err, form.setError, { EMAIL_TAKEN: 'email', EMAIL_DOMAIN_NOT_ALLOWED: 'email' })) {
        setError(getErrorMessage(err, 'Sign-up failed'));
      }
    }
  };

  const signInLink = (
    <Typography variant="body2" color="text.secondary" sx={{ mt: 3, textAlign: 'center' }}>
      Already have an account?{' '}
      <Link component={RouterLink} to="/login" underline="hover" sx={{ fontWeight: 600 }}>
        Sign in
      </Link>
    </Typography>
  );

  let content;
  if (challenge) {
    content = (
      <OtpStep
        challenge={challenge}
        onVerified={() => {
          enqueueSnackbar('Your account is ready. Welcome to SIMS!', { variant: 'success' });
          navigate('/', { replace: true });
        }}
        onStartOver={() => setChallenge(null)}
      />
    );
  } else if (config.isLoading) {
    content = <Skeleton variant="rounded" height={360} />;
  } else if (config.isError && !config.data) {
    content = (
      <>
        <AuthHeading title="Create an account" />
        <Alert
          severity="error"
          action={
            <Button color="inherit" onClick={() => void config.refetch()}>
              Retry
            </Button>
          }
        >
          {getErrorMessage(config.error)}
        </Alert>
        {signInLink}
      </>
    );
  } else if (config.data && !config.data.signup_enabled) {
    content = (
      <>
        <AuthHeading title="Create an account" />
        <Alert severity="info">Self sign-up is turned off. Ask an administrator to create an account for you.</Alert>
        {signInLink}
      </>
    );
  } else {
    content = (
      <>
        <AuthHeading
          title="Create your account"
          subtitle="You'll confirm your email with a one-time code. New accounts start with the Sales role."
        />
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        <Box component="form" onSubmit={handleSubmit(onSubmit)} noValidate>
          <Stack spacing={2.25}>
            <TextField
              label="Full name"
              autoComplete="name"
              autoFocus
              fullWidth
              {...register('name')}
              error={!!errors.name}
              helperText={errors.name?.message}
            />
            <TextField
              label="Work email"
              type="email"
              autoComplete="email"
              fullWidth
              {...register('email')}
              error={!!errors.email}
              helperText={
                errors.email?.message ??
                (domains.length ? `Use your ${domains.map((d) => '@' + d).join(' or ')} address` : undefined)
              }
            />
            <Controller
              control={control}
              name="password"
              render={({ field }) => (
                <PasswordField
                  label="Password"
                  autoComplete="new-password"
                  showStrength
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
            <Controller
              control={control}
              name="confirm"
              render={({ field }) => (
                <PasswordField
                  label="Confirm password"
                  autoComplete="new-password"
                  name={field.name}
                  value={field.value}
                  onChange={field.onChange}
                  onBlur={field.onBlur}
                  inputRef={field.ref}
                  error={!!errors.confirm}
                  helperText={errors.confirm?.message}
                />
              )}
            />
            <Button type="submit" variant="contained" size="large" disabled={isSubmitting}>
              {isSubmitting ? 'Creating account…' : 'Create account'}
            </Button>
          </Stack>
        </Box>
        {signInLink}
      </>
    );
  }

  return <AuthLayout>{content}</AuthLayout>;
}
