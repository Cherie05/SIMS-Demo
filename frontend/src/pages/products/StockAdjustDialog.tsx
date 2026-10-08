import { useEffect, useRef, useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useSnackbar } from 'notistack';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import { productsApi } from '../../api/endpoints';
import { getErrorMessage, newIdempotencyKey } from '../../api/client';
import type { Product } from '../../types';

const schema = z
  .object({
    txn_type: z.enum(['RESTOCK', 'ADJUSTMENT']),
    quantity: z.coerce
      .number({ invalid_type_error: 'Enter a quantity' })
      .int('Whole number')
      .refine((v) => v !== 0, 'Cannot be zero'),
    note: z.string().trim().max(500).optional(),
  })
  .superRefine((values, ctx) => {
    if (values.txn_type === 'RESTOCK' && values.quantity < 0) {
      ctx.addIssue({ code: 'custom', path: ['quantity'], message: 'Restock quantity must be positive' });
    }
    if (values.txn_type === 'ADJUSTMENT' && !values.note) {
      ctx.addIssue({ code: 'custom', path: ['note'], message: 'Explain the adjustment (e.g. damaged, stock count)' });
    }
  });
type FormValues = z.infer<typeof schema>;

export function StockAdjustDialog({ product, onClose }: { product: Product | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { enqueueSnackbar } = useSnackbar();
  const [error, setError] = useState<string | null>(null);
  const {
    control,
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  useEffect(() => {
    if (product) {
      setError(null);
      reset({ txn_type: 'RESTOCK', quantity: '' as unknown as number, note: '' });
    }
  }, [product, reset]);

  const quantity = Number(watch('quantity')) || 0;
  const txnType = watch('txn_type');
  const newBalance = (product?.stock_qty ?? 0) + quantity;

  // A retried submission of the same adjustment reuses its Idempotency-Key, so it is applied once.
  const lastSubmission = useRef<{ body: string; key: string } | null>(null);

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      const payload = { ...values, note: values.note || undefined };
      const body = JSON.stringify([product!.id, payload]);
      if (lastSubmission.current?.body !== body) lastSubmission.current = { body, key: newIdempotencyKey() };
      return productsApi.adjustStock(product!.id, payload, lastSubmission.current.key);
    },
    onSuccess: (txn) => {
      // A confirmed save ends this operation; another identical restock is a new submission.
      lastSubmission.current = null;
      ['products', 'inventory', 'dashboard'].forEach((key) => queryClient.invalidateQueries({ queryKey: [key] }));
      enqueueSnackbar(`${txn.product.sku}: stock is now ${txn.balance_after}`, { variant: 'success' });
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  return (
    <Dialog open={Boolean(product)} onClose={mutation.isPending ? undefined : onClose} maxWidth="xs" fullWidth>
      <form onSubmit={handleSubmit((v) => mutation.mutate(v))} noValidate>
        <DialogTitle>Adjust stock</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {product?.name} ({product?.sku}) — currently <strong>{product?.stock_qty}</strong> in stock
          </Typography>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          <Stack spacing={2}>
            <Controller
              control={control}
              name="txn_type"
              render={({ field }) => (
                <ToggleButtonGroup
                  exclusive
                  fullWidth
                  size="small"
                  value={field.value}
                  onChange={(_, v) => v && field.onChange(v)}
                >
                  <ToggleButton value="RESTOCK">Restock (+)</ToggleButton>
                  <ToggleButton value="ADJUSTMENT">Adjustment (±)</ToggleButton>
                </ToggleButtonGroup>
              )}
            />
            <TextField
              label="Quantity"
              type="number"
              autoFocus
              {...register('quantity')}
              error={!!errors.quantity}
              helperText={
                errors.quantity?.message ??
                (txnType === 'ADJUSTMENT' ? 'Use a negative number to remove stock' : 'Units received')
              }
            />
            <TextField
              label={txnType === 'ADJUSTMENT' ? 'Reason' : 'Note (optional)'}
              multiline
              minRows={2}
              {...register('note')}
              error={!!errors.note}
              helperText={errors.note?.message}
            />
            {quantity !== 0 && (
              <Box sx={{ p: 1.5, borderRadius: 2, bgcolor: newBalance < 0 ? 'rgba(185,28,28,0.08)' : 'grey.50' }}>
                <Typography variant="body2" color={newBalance < 0 ? 'error' : 'text.secondary'}>
                  New balance: <strong>{newBalance}</strong>
                  {newBalance < 0 && ' — stock cannot go below zero'}
                </Typography>
              </Box>
            )}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={mutation.isPending || newBalance < 0}>
            {mutation.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}
