import { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Autocomplete, Box, Link, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { inventoryApi, productsApi } from '../../api/endpoints';
import { getErrorMessage } from '../../api/client';
import { DataTable, type Column } from '../../components/DataTable';
import { PageHeader } from '../../components/PageHeader';
import { StatusChip } from '../../components/StatusChip';
import { useDebounce } from '../../hooks/useDebounce';
import { formatDateTime } from '../../utils/format';
import type { InventoryTransaction, InventoryTxnType, Product } from '../../types';

export default function InventoryPage() {
  const [product, setProduct] = useState<Product | null>(null);
  const [txnType, setTxnType] = useState<InventoryTxnType | ''>('');
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(20);

  const [productSearch, setProductSearch] = useState('');
  const debouncedProductSearch = useDebounce(productSearch, 250);
  // Searched on the server as the user types, so any catalogue size works.
  const products = useQuery({
    queryKey: ['products', 'ledger-filter', debouncedProductSearch],
    queryFn: ({ signal }) => productsApi.list({ search: debouncedProductSearch, page_size: 20 }, signal),
    placeholderData: keepPreviousData,
  });
  const params = { product_id: product?.id, txn_type: txnType || undefined, page: page + 1, page_size: pageSize };
  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ['inventory', params],
    queryFn: ({ signal }) => inventoryApi.transactions(params, signal),
    placeholderData: keepPreviousData,
  });

  const columns: Column<InventoryTransaction>[] = [
    { key: 'date', header: 'Date', render: (t) => formatDateTime(t.created_at) },
    {
      key: 'product',
      header: 'Product',
      render: (t) => (
        <Box>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>
            {t.product.name}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {t.product.sku}
          </Typography>
        </Box>
      ),
    },
    { key: 'type', header: 'Type', render: (t) => <StatusChip status={t.txn_type} /> },
    {
      key: 'change',
      header: 'Change',
      align: 'right',
      render: (t) => (
        <Typography
          variant="body2"
          sx={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}
          color={t.qty_change < 0 ? 'error.main' : 'success.main'}
        >
          {t.qty_change > 0 ? `+${t.qty_change}` : t.qty_change}
        </Typography>
      ),
    },
    {
      key: 'balance',
      header: 'Balance',
      align: 'right',
      render: (t) => <span style={{ fontVariantNumeric: 'tabular-nums' }}>{t.balance_after}</span>,
    },
    {
      key: 'reference',
      header: 'Reference',
      hideOnMobile: true,
      render: (t) =>
        t.order_id ? (
          <Link component={RouterLink} to={`/orders/${t.order_id}`} underline="hover">
            {t.note ?? `Order #${t.order_id}`}
          </Link>
        ) : (
          (t.note ?? '—')
        ),
    },
    { key: 'by', header: 'By', hideOnMobile: true, render: (t) => t.created_by?.name ?? '—' },
  ];

  return (
    <>
      <PageHeader
        title="Stock ledger"
        subtitle="Every stock movement: opening balances, sales, restocks and manual adjustments"
      />
      <DataTable
        rows={data?.items}
        columns={columns}
        rowKey={(t) => t.id}
        loading={isFetching}
        error={error ? getErrorMessage(error) : undefined}
        onRetry={() => void refetch()}
        total={data?.total}
        page={page}
        pageSize={pageSize}
        onPageChange={setPage}
        onPageSizeChange={(size) => {
          setPageSize(size);
          setPage(0);
        }}
        emptyText="No stock movements match your filters."
        toolbar={
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <Autocomplete
              size="small"
              sx={{ minWidth: { xs: 0, sm: 300 } }}
              value={product}
              onChange={(_, value) => {
                setProduct(value);
                setPage(0);
              }}
              onInputChange={(_, value, reason) => reason === 'input' && setProductSearch(value)}
              onOpen={() => setProductSearch('')}
              options={
                product && !products.data?.items.some((p) => p.id === product.id)
                  ? [product, ...(products.data?.items ?? [])]
                  : (products.data?.items ?? [])
              }
              filterOptions={(x) => x}
              loading={products.isFetching}
              getOptionLabel={(p) => `${p.sku} · ${p.name}`}
              isOptionEqualToValue={(a, b) => a.id === b.id}
              renderInput={(p) => (
                <TextField
                  {...p}
                  label="Product"
                  placeholder="All products"
                  error={products.isError}
                  helperText={products.isError ? getErrorMessage(products.error) : undefined}
                />
              )}
            />
            <TextField
              select
              size="small"
              value={txnType}
              onChange={(e) => {
                setTxnType(e.target.value as InventoryTxnType | '');
                setPage(0);
              }}
              sx={{ minWidth: 170 }}
              slotProps={{ select: { displayEmpty: true }, htmlInput: { 'aria-label': 'Filter by movement type' } }}
            >
              <MenuItem value="">All movement types</MenuItem>
              <MenuItem value="SALE">Sale</MenuItem>
              <MenuItem value="RESTOCK">Restock</MenuItem>
              <MenuItem value="ADJUSTMENT">Adjustment</MenuItem>
              <MenuItem value="OPENING">Opening</MenuItem>
            </TextField>
          </Stack>
        }
      />
    </>
  );
}
