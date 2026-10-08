import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSnackbar } from 'notistack';
import {
  Box,
  Button,
  Chip,
  FormControlLabel,
  IconButton,
  InputAdornment,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import SearchIcon from '@mui/icons-material/Search';
import EditIcon from '@mui/icons-material/EditOutlined';
import TuneIcon from '@mui/icons-material/TuneOutlined';
import BlockIcon from '@mui/icons-material/BlockOutlined';
import RestoreIcon from '@mui/icons-material/RestoreOutlined';
import WarningIcon from '@mui/icons-material/WarningAmberOutlined';
import { productsApi } from '../../api/endpoints';
import { getErrorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { DataTable, type Column } from '../../components/DataTable';
import { PageHeader } from '../../components/PageHeader';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { useDebounce } from '../../hooks/useDebounce';
import { formatMoney } from '../../utils/format';
import type { Product } from '../../types';
import { ProductFormDialog } from './ProductFormDialog';
import { StockAdjustDialog } from './StockAdjustDialog';

type ActiveFilter = 'active' | 'inactive' | 'all';

export default function ProductsPage() {
  const { can } = useAuth();
  const canManage = can('product:write');
  const queryClient = useQueryClient();
  const { enqueueSnackbar } = useSnackbar();
  const [searchParams, setSearchParams] = useSearchParams();

  const [search, setSearch] = useState('');
  const [active, setActive] = useState<ActiveFilter>('active');
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const lowStock = searchParams.get('low_stock') === '1';
  const debouncedSearch = useDebounce(search);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [adjusting, setAdjusting] = useState<Product | null>(null);
  const [toggling, setToggling] = useState<Product | null>(null);

  const params = {
    search: debouncedSearch,
    is_active: active === 'all' ? undefined : active === 'active',
    low_stock: lowStock || undefined,
    page: page + 1,
    page_size: pageSize,
  };
  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ['products', params],
    queryFn: ({ signal }) => productsApi.list(params, signal),
    placeholderData: keepPreviousData,
  });

  const toggleActive = useMutation({
    mutationFn: (p: Product) =>
      p.is_active ? productsApi.deactivate(p.id) : productsApi.update(p.id, { is_active: true }),
    onSuccess: (p) => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      enqueueSnackbar(`${p.name} ${p.is_active ? 'reactivated' : 'deactivated'}`, { variant: 'success' });
      setToggling(null);
    },
    onError: (err) => enqueueSnackbar(getErrorMessage(err), { variant: 'error' }),
  });

  const columns: Column<Product>[] = [
    {
      key: 'sku',
      header: 'SKU',
      render: (p) => (
        <Typography variant="body2" sx={{ fontFamily: 'monospace', fontWeight: 600 }}>
          {p.sku}
        </Typography>
      ),
    },
    {
      key: 'name',
      header: 'Product',
      render: (p) => (
        <Box>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>
            {p.name}
          </Typography>
          {p.description && (
            <Typography variant="caption" color="text.secondary">
              {p.description}
            </Typography>
          )}
        </Box>
      ),
    },
    {
      key: 'price',
      header: 'Unit price',
      align: 'right',
      render: (p) => <span style={{ fontVariantNumeric: 'tabular-nums' }}>{formatMoney(p.unit_price)}</span>,
    },
    {
      key: 'stock',
      header: 'In stock',
      align: 'right',
      render: (p) => (
        <Stack direction="row" spacing={1} alignItems="center" justifyContent="flex-end">
          {p.is_low_stock && (
            <Tooltip title={p.stock_qty === 0 ? 'Out of stock' : `At or below reorder level (${p.reorder_level})`}>
              <WarningIcon fontSize="small" color={p.stock_qty === 0 ? 'error' : 'warning'} />
            </Tooltip>
          )}
          <Typography variant="body2" sx={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
            {p.stock_qty}
          </Typography>
        </Stack>
      ),
    },
    {
      key: 'reorder',
      header: 'Reorder level',
      align: 'right',
      hideOnMobile: true,
      render: (p) => p.reorder_level,
    },
    {
      key: 'status',
      header: 'Status',
      hideOnMobile: true,
      render: (p) =>
        p.is_active ? (
          <Chip size="small" label="Active" color="success" variant="outlined" />
        ) : (
          <Chip size="small" label="Inactive" variant="outlined" />
        ),
    },
  ];

  if (canManage) {
    columns.push({
      key: 'actions',
      header: '',
      align: 'right',
      width: 140,
      render: (p) => (
        <Box sx={{ whiteSpace: 'nowrap' }}>
          <Tooltip title="Adjust stock">
            <IconButton size="small" onClick={() => setAdjusting(p)} disabled={!p.is_active}>
              <TuneIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Edit">
            <IconButton
              size="small"
              onClick={() => {
                setEditing(p);
                setFormOpen(true);
              }}
            >
              <EditIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title={p.is_active ? 'Deactivate' : 'Reactivate'}>
            <IconButton size="small" onClick={() => setToggling(p)}>
              {p.is_active ? <BlockIcon fontSize="small" /> : <RestoreIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Box>
      ),
    });
  }

  return (
    <>
      <PageHeader
        title="Products"
        subtitle="Catalogue, pricing and current stock levels"
        actions={
          canManage && (
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              Add product
            </Button>
          )
        }
      />
      <DataTable
        rows={data?.items}
        columns={columns}
        rowKey={(p) => p.id}
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
        emptyText={lowStock ? 'No products are low on stock.' : 'No products match your filters.'}
        toolbar={
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }}>
            <TextField
              size="small"
              placeholder="Search name or SKU"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(0);
              }}
              sx={{ minWidth: 260 }}
              slotProps={{
                input: {
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon fontSize="small" />
                    </InputAdornment>
                  ),
                },
              }}
            />
            <TextField
              select
              size="small"
              value={active}
              onChange={(e) => {
                setActive(e.target.value as ActiveFilter);
                setPage(0);
              }}
              sx={{ minWidth: 150 }}
              slotProps={{ htmlInput: { 'aria-label': 'Filter by status' } }}
            >
              <MenuItem value="active">Active</MenuItem>
              <MenuItem value="inactive">Inactive</MenuItem>
              <MenuItem value="all">All products</MenuItem>
            </TextField>
            <FormControlLabel
              control={
                <Switch
                  checked={lowStock}
                  onChange={(e) => {
                    setSearchParams(e.target.checked ? { low_stock: '1' } : {});
                    setPage(0);
                  }}
                />
              }
              label="Low stock only"
            />
          </Stack>
        }
      />

      <ProductFormDialog open={formOpen} product={editing} onClose={() => setFormOpen(false)} />
      <StockAdjustDialog product={adjusting} onClose={() => setAdjusting(null)} />
      <ConfirmDialog
        open={Boolean(toggling)}
        title={toggling?.is_active ? 'Deactivate product?' : 'Reactivate product?'}
        message={
          toggling?.is_active
            ? `${toggling?.name} will no longer be available for new orders. Existing orders are not affected.`
            : `${toggling?.name} will be available for new orders again.`
        }
        confirmLabel={toggling?.is_active ? 'Deactivate' : 'Reactivate'}
        confirmColor={toggling?.is_active ? 'error' : 'primary'}
        loading={toggleActive.isPending}
        onConfirm={() => toggling && toggleActive.mutate(toggling)}
        onClose={() => setToggling(null)}
      />
    </>
  );
}
