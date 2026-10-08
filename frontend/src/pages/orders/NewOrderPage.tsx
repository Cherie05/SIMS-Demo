import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Controller, useFieldArray, useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSnackbar } from 'notistack';
import {
  Alert,
  AlertTitle,
  Autocomplete,
  Box,
  Button,
  Divider,
  Grid2 as Grid,
  IconButton,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/DeleteOutline';
import PersonAddIcon from '@mui/icons-material/PersonAddAlt1Outlined';
import { customersApi, ordersApi, productsApi, settingsApi, systemApi } from '../../api/endpoints';
import { getErrorCode, getErrorMessage, newIdempotencyKey } from '../../api/client';
import { PageHeader } from '../../components/PageHeader';
import { CustomerFormDialog } from '../customers/CustomerFormDialog';
import { useDebounce } from '../../hooks/useDebounce';
import { formatMoney } from '../../utils/format';
import type { Customer, Product } from '../../types';

interface StockShortage {
  product_id: number;
  sku: string;
  name: string;
  requested: number;
  available: number;
}

const round2 = (value: number) => Math.round((value + Number.EPSILON) * 100) / 100;
/** Same limit as the API (OrderCreate.items max_length). */
const MAX_LINES = 100;

const buildSchema = (getProduct: (id: number) => Product | undefined) =>
  z
    .object({
      // explicit boolean return: stops TS inferring a type predicate, so the field stays nullable while editing
      customer: z.custom<Customer | null>().refine((c): boolean => c !== null, 'Select a customer'),
      items: z
        .array(
          z.object({
            product_id: z.number().nullable(),
            quantity: z.coerce.number({ invalid_type_error: 'Required' }).int('Whole number').min(1, 'At least 1'),
          }),
        )
        .min(1, 'Add at least one product'),
      notes: z.string().max(1000).optional(),
    })
    .superRefine((values, ctx) => {
      values.items.forEach((item, index) => {
        if (item.product_id === null) {
          ctx.addIssue({ code: 'custom', path: ['items', index, 'product_id'], message: 'Select a product' });
          return;
        }
        const product = getProduct(item.product_id);
        if (product && item.quantity > product.stock_qty) {
          ctx.addIssue({
            code: 'custom',
            path: ['items', index, 'quantity'],
            message: `Only ${product.stock_qty} in stock`,
          });
        }
      });
    });
type FormValues = z.infer<ReturnType<typeof buildSchema>>;

export default function NewOrderPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { enqueueSnackbar } = useSnackbar();
  const [customerSearch, setCustomerSearch] = useState('');
  const debouncedCustomerSearch = useDebounce(customerSearch, 250);
  const [productSearch, setProductSearch] = useState('');
  const debouncedProductSearch = useDebounce(productSearch, 250);
  const [customerDialog, setCustomerDialog] = useState(false);
  const [submitError, setSubmitError] = useState<{ message: string; shortages?: StockShortage[] } | null>(null);

  const settings = useQuery({ queryKey: ['settings'], queryFn: settingsApi.get });
  // Searched on the server as the user types, so any catalogue size works.
  const products = useQuery({
    queryKey: ['products', 'orderable', debouncedProductSearch],
    queryFn: ({ signal }) =>
      productsApi.list({ is_active: true, search: debouncedProductSearch, page_size: 20 }, signal),
    placeholderData: keepPreviousData,
  });
  const customers = useQuery({
    queryKey: ['customers', 'picker', debouncedCustomerSearch],
    queryFn: ({ signal }) =>
      customersApi.list({ is_active: true, search: debouncedCustomerSearch, page_size: 20 }, signal),
  });

  // Products chosen on any line, kept even when they drop out of the current search results.
  const [productsById, setProductsById] = useState<Map<number, Product>>(() => new Map());
  const rememberProduct = (product: Product) => setProductsById((prev) => new Map(prev).set(product.id, product));

  // The schema reads the catalogue through a ref so it can check stock levels while staying stable for RHF.
  const productsRef = useRef(productsById);
  useEffect(() => {
    productsRef.current = productsById;
  }, [productsById]);
  const [schema] = useState(() => buildSchema((id) => productsRef.current.get(id)));

  const {
    control,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { customer: null, items: [{ product_id: null, quantity: 1 }], notes: '' },
  });
  const { fields, append, remove } = useFieldArray({ control, name: 'items' });
  const items = useWatch({ control, name: 'items' });

  const taxRate = settings.data?.tax_rate ?? 0;
  const threshold = settings.data?.approval_threshold ?? Infinity;
  const lines = (items ?? []).map((item) => {
    const product = item.product_id ? productsById.get(item.product_id) : undefined;
    const quantity = Number(item.quantity) || 0;
    return { product, quantity, total: product ? round2(product.unit_price * quantity) : 0 };
  });
  const subtotal = round2(lines.reduce((sum, l) => sum + l.total, 0));
  const tax = round2((subtotal * taxRate) / 100);
  const total = round2(subtotal + tax);
  const needsApproval = total > threshold;
  const selectedIds = new Set(lines.map((l) => l.product?.id).filter(Boolean));

  // Same submission retried (double click, timeout) -> same Idempotency-Key -> one order. Any edit -> new key.
  const lastSubmission = useRef<{ body: string; key: string } | null>(null);
  const flags = useQuery({ queryKey: ['feature-flags'], queryFn: systemApi.flags, staleTime: 60_000 });
  const intakePaused = flags.data?.some((f) => f.name === 'orders.create' && !f.enabled) ?? false;

  const mutation = useMutation({
    mutationFn: (values: FormValues) => {
      const payload = {
        customer_id: values.customer!.id, // non-null: enforced by the schema
        items: values.items.map((i) => ({ product_id: i.product_id!, quantity: Number(i.quantity) })),
        notes: values.notes?.trim() || undefined,
      };
      const body = JSON.stringify(payload);
      if (lastSubmission.current?.body !== body) lastSubmission.current = { body, key: newIdempotencyKey() };
      return ordersApi.create(payload, lastSubmission.current.key);
    },
    onSuccess: (order) => {
      ['orders', 'products', 'dashboard', 'approvals', 'inventory'].forEach((key) =>
        queryClient.invalidateQueries({ queryKey: [key] }),
      );
      enqueueSnackbar(
        order.status === 'PENDING_APPROVAL'
          ? `${order.order_number} submitted for manager approval`
          : `${order.order_number} confirmed and completed`,
        { variant: 'success' },
      );
      navigate(`/orders/${order.id}`);
    },
    onError: (err) => {
      const shortages =
        getErrorCode(err) === 'INSUFFICIENT_STOCK'
          ? ((err as { response?: { data?: { error?: { details?: StockShortage[] } } } }).response?.data?.error
              ?.details ?? [])
          : undefined;
      setSubmitError({ message: getErrorMessage(err), shortages });
      if (shortages) {
        // Refresh the stock we validate against with the server's current figures.
        setProductsById((prev) => {
          const next = new Map(prev);
          for (const s of shortages) {
            const product = next.get(s.product_id);
            if (product) next.set(s.product_id, { ...product, stock_qty: s.available });
          }
          return next;
        });
        queryClient.invalidateQueries({ queryKey: ['products'] });
      }
    },
  });

  return (
    <>
      <PageHeader title="New sales order" subtitle="Stock is validated now and again when the order is fulfilled" />
      {intakePaused && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Order intake is paused by an administrator. You can prepare the order, but it can't be submitted right now.
        </Alert>
      )}

      {[settings, products, customers, flags]
        .filter((query) => query.isError)
        .map((query, index) => (
          <Alert
            key={index}
            severity="error"
            sx={{ mb: 2 }}
            action={
              <Button color="inherit" onClick={() => void query.refetch()}>
                Retry
              </Button>
            }
          >
            {getErrorMessage(query.error)}
          </Alert>
        ))}
      <Box
        component="form"
        noValidate
        onSubmit={handleSubmit((v) => {
          if (!mutation.isPending && !intakePaused && settings.data) mutation.mutate(v);
        })}
      >
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, lg: 8 }}>
            <Paper sx={{ p: 2.5, mb: 2 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 2 }}>
                Customer
              </Typography>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'flex-start' }}>
                <Controller
                  control={control}
                  name="customer"
                  render={({ field }) => (
                    <Autocomplete
                      fullWidth
                      value={field.value}
                      onChange={(_, value) => field.onChange(value)}
                      onInputChange={(_, value, reason) => reason === 'input' && setCustomerSearch(value)}
                      options={
                        field.value && !customers.data?.items.some((c) => c.id === field.value?.id)
                          ? [field.value, ...(customers.data?.items ?? [])]
                          : (customers.data?.items ?? [])
                      }
                      loading={customers.isFetching}
                      filterOptions={(x) => x}
                      getOptionLabel={(c) => c.name}
                      isOptionEqualToValue={(a, b) => a.id === b.id}
                      renderOption={({ key, ...props }, c) => (
                        <li key={key} {...props}>
                          <Box>
                            <Typography variant="body2">{c.name}</Typography>
                            <Typography variant="caption" color="text.secondary">
                              {c.email}
                              {c.phone ? ` · ${c.phone}` : ''}
                            </Typography>
                          </Box>
                        </li>
                      )}
                      renderInput={(params) => (
                        <TextField
                          {...params}
                          label="Search customers"
                          required
                          error={!!errors.customer}
                          helperText={errors.customer?.message}
                        />
                      )}
                    />
                  )}
                />
                <Button
                  variant="outlined"
                  startIcon={<PersonAddIcon />}
                  onClick={() => setCustomerDialog(true)}
                  sx={{ flexShrink: 0, height: 56 }}
                >
                  New customer
                </Button>
              </Stack>
            </Paper>

            <Paper sx={{ p: 2.5 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 2 }}>
                Products
              </Typography>
              <Stack spacing={2} divider={<Divider flexItem />}>
                {fields.map((field, index) => {
                  const line = lines[index];
                  const rowErrors = errors.items?.[index];
                  return (
                    <Grid container spacing={1.5} key={field.id} alignItems="flex-start">
                      <Grid size={{ xs: 12, md: 6 }}>
                        <Controller
                          control={control}
                          name={`items.${index}.product_id`}
                          render={({ field: f }) => (
                            <Autocomplete<Product>
                              value={f.value ? (productsById.get(f.value) ?? null) : null}
                              onChange={(_, product) => {
                                if (product) rememberProduct(product);
                                f.onChange(product?.id ?? null);
                                setSubmitError(null);
                              }}
                              onOpen={() => setProductSearch('')}
                              onInputChange={(_, value, reason) => reason === 'input' && setProductSearch(value)}
                              options={withSelected(
                                products.data?.items ?? [],
                                f.value ? productsById.get(f.value) : undefined,
                              )}
                              filterOptions={(x) => x}
                              loading={products.isFetching}
                              noOptionsText={debouncedProductSearch ? 'No matching products' : 'No products'}
                              getOptionLabel={(p) => `${p.sku} · ${p.name}`}
                              getOptionDisabled={(p) =>
                                p.stock_qty === 0 || (selectedIds.has(p.id) && p.id !== f.value)
                              }
                              isOptionEqualToValue={(a, b) => a.id === b.id}
                              renderOption={({ key, ...props }, p) => (
                                <li key={key} {...props}>
                                  <Box sx={{ display: 'flex', justifyContent: 'space-between', width: '100%', gap: 2 }}>
                                    <Box>
                                      <Typography variant="body2">{p.name}</Typography>
                                      <Typography variant="caption" color="text.secondary">
                                        {p.sku} · {formatMoney(p.unit_price)}
                                      </Typography>
                                    </Box>
                                    <Typography
                                      variant="caption"
                                      color={
                                        p.stock_qty === 0 ? 'error' : p.is_low_stock ? 'warning.main' : 'text.secondary'
                                      }
                                      sx={{ whiteSpace: 'nowrap' }}
                                    >
                                      {p.stock_qty === 0 ? 'Out of stock' : `${p.stock_qty} in stock`}
                                    </Typography>
                                  </Box>
                                </li>
                              )}
                              renderInput={(params) => (
                                <TextField
                                  {...params}
                                  label="Product"
                                  error={!!rowErrors?.product_id}
                                  helperText={
                                    rowErrors?.product_id?.message ??
                                    (line?.product ? `${line.product.stock_qty} available` : ' ')
                                  }
                                />
                              )}
                            />
                          )}
                        />
                      </Grid>
                      <Grid size={{ xs: 4, md: 2 }}>
                        <Controller
                          control={control}
                          name={`items.${index}.quantity`}
                          render={({ field: f }) => (
                            <TextField
                              {...f}
                              onChange={(e) => {
                                f.onChange(e.target.value);
                                setSubmitError(null);
                              }}
                              label="Qty"
                              type="number"
                              fullWidth
                              error={!!rowErrors?.quantity}
                              helperText={rowErrors?.quantity?.message ?? ' '}
                              slotProps={{ htmlInput: { min: 1, max: line?.product?.stock_qty } }}
                            />
                          )}
                        />
                      </Grid>
                      <Grid size={{ xs: 6, md: 3 }} sx={{ textAlign: 'right', pt: 1 }}>
                        <Typography variant="body2" color="text.secondary">
                          {line?.product ? `${formatMoney(line.product.unit_price)} each` : '—'}
                        </Typography>
                        <Typography sx={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                          {formatMoney(line?.total ?? 0)}
                        </Typography>
                      </Grid>
                      <Grid size={{ xs: 2, md: 1 }} sx={{ textAlign: 'right', pt: 1 }}>
                        <Tooltip describeChild title="Remove line">
                          <span>
                            <IconButton
                              onClick={() => remove(index)}
                              disabled={fields.length === 1}
                              aria-label="Remove line"
                            >
                              <DeleteIcon />
                            </IconButton>
                          </span>
                        </Tooltip>
                      </Grid>
                    </Grid>
                  );
                })}
              </Stack>
              <Button
                startIcon={<AddIcon />}
                sx={{ mt: 2 }}
                onClick={() => append({ product_id: null, quantity: 1 })}
                disabled={fields.length >= MAX_LINES}
              >
                Add product
              </Button>

              <Controller
                control={control}
                name="notes"
                render={({ field }) => (
                  <TextField
                    {...field}
                    label="Notes (optional)"
                    fullWidth
                    multiline
                    minRows={2}
                    sx={{ mt: 3 }}
                    slotProps={{ htmlInput: { maxLength: 1000 } }}
                  />
                )}
              />
            </Paper>
          </Grid>

          <Grid size={{ xs: 12, lg: 4 }}>
            <Paper sx={{ p: 2.5, position: { lg: 'sticky' }, top: { lg: 24 } }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 2 }}>
                Summary
              </Typography>
              <Stack spacing={1}>
                <Row label="Subtotal" value={formatMoney(subtotal)} />
                <Row label={`Tax (${taxRate}%)`} value={formatMoney(tax)} />
                <Divider />
                <Row label="Total" value={formatMoney(total)} strong />
              </Stack>

              {total > 0 &&
                settings.data &&
                (needsApproval ? (
                  <Alert severity="warning" sx={{ mt: 2 }}>
                    <AlertTitle>Manager approval required</AlertTitle>
                    Total exceeds the {formatMoney(threshold)} threshold. Managers will be emailed, and stock is only
                    deducted once the order is approved.
                  </Alert>
                ) : (
                  <Alert severity="success" sx={{ mt: 2 }}>
                    Within the {formatMoney(threshold)} approval threshold — the order is confirmed and stock deducted
                    immediately.
                  </Alert>
                ))}

              {submitError && (
                <Alert severity="error" sx={{ mt: 2 }}>
                  {submitError.shortages?.length ? (
                    <>
                      <AlertTitle>Not enough stock</AlertTitle>
                      {submitError.shortages.map((s) => (
                        <div key={s.sku}>
                          {s.name}: requested {s.requested}, available {s.available}
                        </div>
                      ))}
                    </>
                  ) : (
                    submitError.message
                  )}
                </Alert>
              )}

              <Button
                type="submit"
                variant="contained"
                size="large"
                fullWidth
                sx={{ mt: 3 }}
                disabled={mutation.isPending || intakePaused || !settings.data}
              >
                {mutation.isPending ? 'Placing order…' : needsApproval ? 'Submit for approval' : 'Place order'}
              </Button>
              <Button fullWidth sx={{ mt: 1 }} onClick={() => navigate(-1)} disabled={mutation.isPending}>
                Cancel
              </Button>
            </Paper>
          </Grid>
        </Grid>
      </Box>

      <CustomerFormDialog
        open={customerDialog}
        customer={null}
        onClose={() => setCustomerDialog(false)}
        onSaved={(c) => setValue('customer', c, { shouldValidate: true })}
      />
    </>
  );
}

/** Keep the selected product in the option list so the field can display it. */
function withSelected(options: Product[], selected: Product | undefined): Product[] {
  return selected && !options.some((p) => p.id === selected.id) ? [selected, ...options] : options;
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
      <Typography color={strong ? 'text.primary' : 'text.secondary'} sx={{ fontWeight: strong ? 700 : 400 }}>
        {label}
      </Typography>
      <Typography sx={{ fontWeight: strong ? 700 : 500, fontVariantNumeric: 'tabular-nums' }}>{value}</Typography>
    </Box>
  );
}
