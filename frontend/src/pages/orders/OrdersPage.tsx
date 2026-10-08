import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import {
  Box,
  Button,
  FormControlLabel,
  InputAdornment,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import SearchIcon from '@mui/icons-material/Search';
import ShieldIcon from '@mui/icons-material/GppMaybeOutlined';
import { ordersApi } from '../../api/endpoints';
import { getErrorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { DataTable, type Column } from '../../components/DataTable';
import { PageHeader } from '../../components/PageHeader';
import { StatusChip } from '../../components/StatusChip';
import { useDebounce } from '../../hooks/useDebounce';
import { formatDateTime, formatMoney } from '../../utils/format';
import type { OrderListItem, OrderStatus } from '../../types';

const TABS: { value: OrderStatus | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'PENDING_APPROVAL', label: 'Pending approval' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'REJECTED', label: 'Rejected' },
  { value: 'CANCELLED', label: 'Cancelled' },
];

export default function OrdersPage() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const isSales = !can('order:read:all');
  const [searchParams, setSearchParams] = useSearchParams();
  const status = (searchParams.get('status') ?? '') as OrderStatus | '';

  const [search, setSearch] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const debouncedSearch = useDebounce(search);

  const params = {
    status: status || undefined,
    search: debouncedSearch,
    date_from: dateFrom,
    date_to: dateTo,
    mine: mine || undefined,
    page: page + 1,
    page_size: pageSize,
  };
  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ['orders', params],
    queryFn: ({ signal }) => ordersApi.list(params, signal),
    placeholderData: keepPreviousData,
  });

  const columns: Column<OrderListItem>[] = [
    {
      key: 'number',
      header: 'Order',
      render: (o) => (
        <Stack direction="row" spacing={0.75} alignItems="center">
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {o.order_number}
          </Typography>
          {o.requires_approval && (
            <Tooltip title="Above approval threshold">
              <ShieldIcon sx={{ fontSize: 16, color: 'text.secondary' }} />
            </Tooltip>
          )}
        </Stack>
      ),
    },
    { key: 'customer', header: 'Customer', render: (o) => o.customer.name },
    { key: 'by', header: 'Created by', hideOnMobile: true, render: (o) => o.created_by.name },
    { key: 'date', header: 'Created', hideOnMobile: true, render: (o) => formatDateTime(o.created_at) },
    {
      key: 'total',
      header: 'Total',
      align: 'right',
      render: (o) => <span style={{ fontVariantNumeric: 'tabular-nums' }}>{formatMoney(o.total_amount)}</span>,
    },
    { key: 'status', header: 'Status', render: (o) => <StatusChip status={o.status} /> },
  ];

  return (
    <>
      <PageHeader
        title="Sales orders"
        subtitle={isSales ? 'Orders you have created' : 'All sales orders across the team'}
        actions={
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => navigate('/orders/new')}>
            New order
          </Button>
        }
      />
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tabs
          value={status}
          onChange={(_, value: string) => {
            setSearchParams(value ? { status: value } : {});
            setPage(0);
          }}
          variant="scrollable"
          allowScrollButtonsMobile
        >
          {TABS.map((tab) => (
            <Tab key={tab.value} value={tab.value} label={tab.label} />
          ))}
        </Tabs>
      </Box>
      <DataTable
        rows={data?.items}
        columns={columns}
        rowKey={(o) => o.id}
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
        onRowClick={(o) => navigate(`/orders/${o.id}`)}
        emptyText="No orders match your filters."
        toolbar={
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ md: 'center' }}>
            <TextField
              size="small"
              placeholder="Order number or customer"
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
              size="small"
              type="date"
              label="From"
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value);
                setPage(0);
              }}
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <TextField
              size="small"
              type="date"
              label="To"
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value);
                setPage(0);
              }}
              slotProps={{ inputLabel: { shrink: true }, htmlInput: { min: dateFrom || undefined } }}
            />
            {!isSales && (
              <FormControlLabel
                control={
                  <Switch
                    checked={mine}
                    onChange={(e) => {
                      setMine(e.target.checked);
                      setPage(0);
                    }}
                  />
                }
                label="Only mine"
              />
            )}
          </Stack>
        }
      />
    </>
  );
}
