import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useSnackbar } from 'notistack';
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField } from '@mui/material';
import { customersApi } from '../../api/endpoints';
import { getErrorMessage } from '../../api/client';
import { applyServerErrors } from '../../utils/forms';
import type { Customer } from '../../types';

const schema = z.object({
  name: z.string().trim().min(2, 'At least 2 characters').max(150),
  email: z.string().trim().min(1, 'Email is required').email('Enter a valid email'),
  phone: z
    .string()
    .trim()
    .refine((v) => v === '' || /^[0-9+()\-\s]{7,20}$/.test(v), '7–20 digits; + ( ) - and spaces allowed')
    .optional(),
  address: z.string().trim().max(500).optional(),
});
type FormValues = z.infer<typeof schema>;

interface Props {
  open: boolean;
  customer: Customer | null;
  onClose: () => void;
  onSaved?: (customer: Customer) => void;
}

export function CustomerFormDialog({ open, customer, onClose, onSaved }: Props) {
  const queryClient = useQueryClient();
  const { enqueueSnackbar } = useSnackbar();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<FormValues>({ resolver: zodResolver(schema) });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = form;

  useEffect(() => {
    if (!open) return;
    setError(null);
    reset({
      name: customer?.name ?? '',
      email: customer?.email ?? '',
      phone: customer?.phone ?? '',
      address: customer?.address ?? '',
    });
  }, [open, customer, reset]);

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      const payload = { ...values, phone: values.phone || null, address: values.address || null };
      return customer ? customersApi.update(customer.id, payload) : customersApi.create(payload);
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ['customers'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      enqueueSnackbar(`${saved.name} ${customer ? 'updated' : 'added'}`, { variant: 'success' });
      onSaved?.(saved);
      onClose();
    },
    onError: (err) => {
      if (!applyServerErrors(err, form.setError, { DUPLICATE_EMAIL: 'email' })) setError(getErrorMessage(err));
    },
  });

  return (
    <Dialog open={open} onClose={mutation.isPending ? undefined : onClose} maxWidth="sm" fullWidth>
      <form onSubmit={handleSubmit((v) => mutation.mutate(v))} noValidate>
        <DialogTitle>{customer ? 'Edit customer' : 'Add customer'}</DialogTitle>
        <DialogContent>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label="Name"
              required
              {...register('name')}
              error={!!errors.name}
              helperText={errors.name?.message}
            />
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <TextField
                label="Email"
                type="email"
                required
                fullWidth
                {...register('email')}
                error={!!errors.email}
                helperText={errors.email?.message}
              />
              <TextField
                label="Phone"
                fullWidth
                {...register('phone')}
                error={!!errors.phone}
                helperText={errors.phone?.message}
              />
            </Stack>
            <TextField
              label="Address"
              multiline
              minRows={2}
              {...register('address')}
              error={!!errors.address}
              helperText={errors.address?.message}
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={mutation.isPending}>
            {mutation.isPending ? 'Saving…' : customer ? 'Save changes' : 'Add customer'}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}
