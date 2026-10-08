import { useState } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSnackbar } from 'notistack';
import {
  Box,
  Button,
  Chip,
  IconButton,
  InputAdornment,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import SearchIcon from '@mui/icons-material/Search';
import EditIcon from '@mui/icons-material/EditOutlined';
import BlockIcon from '@mui/icons-material/BlockOutlined';
import RestoreIcon from '@mui/icons-material/RestoreOutlined';
import { customersApi } from '../../api/endpoints';
import { getErrorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { DataTable, type Column } from '../../components/DataTable';
import { PageHeader } from '../../components/PageHeader';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { useDebounce } from '../../hooks/useDebounce';
import { formatDate } from '../../utils/format';
import type { Customer } from '../../types';
import { CustomerFormDialog } from './CustomerFormDialog';

type ActiveFilter = 'active' | 'inactive' | 'all';

export default function CustomersPage() {
  const { can } = useAuth();
  const canDeactivate = can('customer:deactivate');
  const queryClient = useQueryClient();
  const { enqueueSnackbar } = useSnackbar();

  const [search, setSearch] = useState('');
  const [active, setActive] = useState<ActiveFilter>('active');
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const debouncedSearch = useDebounce(search);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Customer | null>(null);
  const [toggling, setToggling] = useState<Customer | null>(null);

  const params = {
    search: debouncedSearch,
    is_active: active === 'all' ? undefined : active === 'active',
    page: page + 1,
    page_size: pageSize,
  };
  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ['customers', params],
    queryFn: ({ signal }) => customersApi.list(params, signal),
    placeholderData: keepPreviousData,
  });

  const toggleActive = useMutation({
    mutationFn: (c: Customer) =>
      c.is_active ? customersApi.deactivate(c.id) : customersApi.update(c.id, { is_active: true }),
    onSuccess: (c) => {
      queryClient.invalidateQueries({ queryKey: ['customers'] });
      enqueueSnackbar(`${c.name} ${c.is_active ? 'reactivated' : 'deactivated'}`, { variant: 'success' });
      setToggling(null);
    },
    onError: (err) => enqueueSnackbar(getErrorMessage(err), { variant: 'error' }),
  });

  const columns: Column<Customer>[] = [
    {
      key: 'name',
      header: 'Customer',
      render: (c) => (
        <Box>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>
            {c.name}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {c.email}
          </Typography>
        </Box>
      ),
    },
    { key: 'phone', header: 'Phone', render: (c) => c.phone ?? '—' },
    { key: 'address', header: 'Address', hideOnMobile: true, render: (c) => c.address ?? '—' },
    { key: 'since', header: 'Since', hideOnMobile: true, render: (c) => formatDate(c.created_at) },
    {
      key: 'status',
      header: 'Status',
      render: (c) =>
        c.is_active ? (
          <Chip size="small" label="Active" color="success" variant="outlined" />
        ) : (
          <Chip size="small" label="Inactive" variant="outlined" />
        ),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      width: 100,
      render: (c) => (
        <Box sx={{ whiteSpace: 'nowrap' }}>
          <Tooltip title="Edit">
            <IconButton
              size="small"
              onClick={() => {
                setEditing(c);
                setFormOpen(true);
              }}
            >
              <EditIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          {canDeactivate && (
            <Tooltip title={c.is_active ? 'Deactivate' : 'Reactivate'}>
              <IconButton size="small" onClick={() => setToggling(c)}>
                {c.is_active ? <BlockIcon fontSize="small" /> : <RestoreIcon fontSize="small" />}
              </IconButton>
            </Tooltip>
          )}
        </Box>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Customers"
        subtitle="People and companies you sell to"
        actions={
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            Add customer
          </Button>
        }
      />
      <DataTable
        rows={data?.items}
        columns={columns}
        rowKey={(c) => c.id}
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
        emptyText="No customers match your filters."
        toolbar={
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField
              size="small"
              placeholder="Search name, email or phone"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(0);
              }}
              sx={{ minWidth: 280 }}
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
              <MenuItem value="all">All customers</MenuItem>
            </TextField>
          </Stack>
        }
      />
      <CustomerFormDialog open={formOpen} customer={editing} onClose={() => setFormOpen(false)} />
      <ConfirmDialog
        open={Boolean(toggling)}
        title={toggling?.is_active ? 'Deactivate customer?' : 'Reactivate customer?'}
        message={
          toggling?.is_active
            ? `New orders can no longer be placed for ${toggling?.name}. Order history is kept.`
            : `${toggling?.name} can be selected on new orders again.`
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
