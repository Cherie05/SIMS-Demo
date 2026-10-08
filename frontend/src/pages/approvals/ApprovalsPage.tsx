import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Box, Button, Stack, Tab, Tabs, Tooltip, Typography } from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import { approvalsApi } from '../../api/endpoints';
import { getErrorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { DataTable, type Column } from '../../components/DataTable';
import { PageHeader } from '../../components/PageHeader';
import { StatusChip } from '../../components/StatusChip';
import { formatDateTime, formatMoney } from '../../utils/format';
import type { ApprovalListItem, ApprovalStatus } from '../../types';
import { DecisionDialog, type Decision } from './DecisionDialog';

const TABS: { value: ApprovalStatus | ''; label: string }[] = [
  { value: 'PENDING', label: 'Pending' },
  { value: 'APPROVED', label: 'Approved' },
  { value: 'REJECTED', label: 'Rejected' },
  { value: 'CANCELLED', label: 'Cancelled' },
  { value: '', label: 'All' },
];

export default function ApprovalsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [status, setStatus] = useState<ApprovalStatus | ''>('PENDING');
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const [selected, setSelected] = useState<{ item: ApprovalListItem; decision: Decision } | null>(null);

  const params = { status, page: page + 1, page_size: pageSize };
  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ['approvals', params],
    queryFn: ({ signal }) => approvalsApi.list(params, signal),
    placeholderData: keepPreviousData,
  });

  const columns: Column<ApprovalListItem>[] = [
    {
      key: 'order',
      header: 'Order',
      render: (a) => (
        <Box>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {a.order.order_number}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {a.order.customer.name}
          </Typography>
        </Box>
      ),
    },
    { key: 'requester', header: 'Requested by', hideOnMobile: true, render: (a) => a.order.created_by.name },
    { key: 'requested', header: 'Requested', hideOnMobile: true, render: (a) => formatDateTime(a.requested_at) },
    {
      key: 'total',
      header: 'Total',
      align: 'right',
      render: (a) => (
        <Box>
          <Typography variant="body2" sx={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
            {formatMoney(a.order.total_amount)}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            limit {formatMoney(a.threshold_amount)}
          </Typography>
        </Box>
      ),
    },
  ];

  if (status === 'PENDING') {
    columns.push({
      key: 'actions',
      header: 'Decision',
      align: 'right',
      render: (a) => {
        const own = a.order.created_by.id === user?.id;
        return (
          <Tooltip describeChild title={own ? 'You cannot decide on your own order' : ''}>
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={1}
              justifyContent="flex-end"
              onClick={(e) => e.stopPropagation()}
            >
              <Button
                size="small"
                color="error"
                variant="outlined"
                startIcon={<CloseIcon />}
                disabled={own}
                onClick={() => setSelected({ item: a, decision: 'reject' })}
              >
                Reject
              </Button>
              <Button
                size="small"
                color="success"
                variant="contained"
                startIcon={<CheckIcon />}
                disabled={own}
                onClick={() => setSelected({ item: a, decision: 'approve' })}
              >
                Approve
              </Button>
            </Stack>
          </Tooltip>
        );
      },
    });
  } else {
    columns.push(
      { key: 'status', header: 'Status', render: (a) => <StatusChip status={a.status} /> },
      {
        key: 'decided',
        header: 'Decision',
        hideOnMobile: true,
        render: (a) => (
          <Box>
            <Typography variant="body2">{a.decided_by?.name ?? '—'}</Typography>
            <Typography variant="caption" color="text.secondary">
              {formatDateTime(a.decided_at)}
            </Typography>
          </Box>
        ),
      },
      {
        key: 'comment',
        header: 'Comment',
        hideOnMobile: true,
        render: (a) => (
          <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 260 }} noWrap title={a.comment ?? ''}>
            {a.comment ?? '—'}
          </Typography>
        ),
      },
    );
  }

  return (
    <>
      <PageHeader title="Approvals" subtitle="Orders above the approval threshold wait here for a manager's decision" />
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tabs
          value={status}
          onChange={(_, value) => {
            setStatus(value);
            setPage(0);
          }}
          variant="scrollable"
          allowScrollButtonsMobile
        >
          {TABS.map((tab) => (
            <Tab key={tab.label} value={tab.value} label={tab.label} />
          ))}
        </Tabs>
      </Box>
      <DataTable
        rows={data?.items}
        columns={columns}
        rowKey={(a) => a.id}
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
        onRowClick={(a) => navigate(`/orders/${a.order.id}`)}
        emptyText={status === 'PENDING' ? 'Nothing waiting for approval. 🎉' : 'No approvals in this view.'}
      />
      <DecisionDialog
        order={selected?.item.order ?? null}
        decision={selected?.decision ?? null}
        onClose={() => setSelected(null)}
      />
    </>
  );
}
