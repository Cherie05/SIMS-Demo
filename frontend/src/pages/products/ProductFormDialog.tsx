import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useSnackbar } from 'notistack';
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid2 as Grid,
  InputAdornment,
  TextField,
} from '@mui/material';
import { productsApi } from '../../api/endpoints';
import { getErrorMessage } from '../../api/client';
import { applyServerErrors } from '../../utils/forms';
import type { Product } from '../../types';

const schema = z.object({
  sku: z
    .string()
    .trim()
    .min(2, 'At least 2 characters')
    .max(50)
    .regex(/^[A-Za-z0-9_-]+$/, 'Letters, numbers, - and _ only'),
  name: z.string().trim().min(2, 'At least 2 characters').max(200),
  description: z.string().trim().max(2000).optional(),
  unit_price: z.coerce.number({ invalid_type_error: 'Enter a price' }).min(0, 'Cannot be negative').max(9_999_999_999),
  reorder_level: z.coerce.number().int('Whole number').min(0, 'Cannot be negative'),
  opening_stock: z.coerce.number().int('Whole number').min(0, 'Cannot be negative'),
});
type FormValues = z.infer<typeof schema>;

interface Props {
  open: boolean;
  product: Product | null; // null = create
  onClose: () => void;
}

export function ProductFormDialog({ open, product, onClose }: Props) {
  const queryClient = useQueryClient();
  const { enqueueSnackbar } = useSnackbar();
  const [error, setError] = useState<string | null>(null);
  const isEdit = Boolean(product);

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
      sku: product?.sku ?? '',
      name: product?.name ?? '',
      description: product?.description ?? '',
      unit_price: product?.unit_price ?? ('' as unknown as number),
      reorder_level: product?.reorder_level ?? 10,
      opening_stock: 0,
    });
  }, [open, product, reset]);

  const mutation = useMutation({
    mutationFn: ({ opening_stock, ...values }: FormValues) => {
      const fields = { ...values, description: values.description || null };
      return product ? productsApi.update(product.id, fields) : productsApi.create({ ...fields, opening_stock });
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      queryClient.invalidateQueries({ queryKey: ['inventory'] });
      enqueueSnackbar(`${saved.name} ${isEdit ? 'updated' : 'created'}`, { variant: 'success' });
      onClose();
    },
    onError: (err) => {
      if (!applyServerErrors(err, form.setError, { DUPLICATE_SKU: 'sku' })) setError(getErrorMessage(err));
    },
  });

  return (
    <Dialog open={open} onClose={mutation.isPending ? undefined : onClose} maxWidth="sm" fullWidth>
      <form onSubmit={handleSubmit((values) => mutation.mutate(values))} noValidate>
        <DialogTitle>{isEdit ? 'Edit product' : 'Add product'}</DialogTitle>
        <DialogContent>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid size={{ xs: 12, sm: 4 }}>
              <TextField
                label="SKU"
                fullWidth
                required
                {...register('sku')}
                error={!!errors.sku}
                helperText={errors.sku?.message}
                slotProps={{ htmlInput: { style: { textTransform: 'uppercase' } } }}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 8 }}>
              <TextField
                label="Name"
                fullWidth
                required
                {...register('name')}
                error={!!errors.name}
                helperText={errors.name?.message}
              />
            </Grid>
            <Grid size={12}>
              <TextField
                label="Description"
                fullWidth
                multiline
                minRows={2}
                {...register('description')}
                error={!!errors.description}
                helperText={errors.description?.message}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: isEdit ? 6 : 4 }}>
              <TextField
                label="Unit price"
                type="number"
                fullWidth
                required
                {...register('unit_price')}
                error={!!errors.unit_price}
                helperText={errors.unit_price?.message}
                slotProps={{
                  input: { startAdornment: <InputAdornment position="start">₹</InputAdornment> },
                  htmlInput: { step: '0.01', min: 0 },
                }}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: isEdit ? 6 : 4 }}>
              <TextField
                label="Reorder level"
                type="number"
                fullWidth
                {...register('reorder_level')}
                error={!!errors.reorder_level}
                helperText={errors.reorder_level?.message ?? 'Flag as low stock at or below'}
                slotProps={{ htmlInput: { min: 0 } }}
              />
            </Grid>
            {!isEdit && (
              <Grid size={{ xs: 12, sm: 4 }}>
                <TextField
                  label="Opening stock"
                  type="number"
                  fullWidth
                  {...register('opening_stock')}
                  error={!!errors.opening_stock}
                  helperText={errors.opening_stock?.message ?? 'Recorded in the ledger'}
                  slotProps={{ htmlInput: { min: 0 } }}
                />
              </Grid>
            )}
          </Grid>
          {isEdit && (
            <Alert severity="info" sx={{ mt: 2 }}>
              Stock ({product?.stock_qty} units) can only be changed with <strong>Adjust stock</strong>, so every
              movement is recorded in the stock ledger.
            </Alert>
          )}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={mutation.isPending}>
            {mutation.isPending ? 'Saving…' : isEdit ? 'Save changes' : 'Create product'}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}
