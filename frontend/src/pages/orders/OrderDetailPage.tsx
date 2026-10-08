import { useState, type ReactNode } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  Box,
  Breadcrumbs,
  Button,
  Divider,
  Grid2 as Grid,
  Link,
  Paper,
  Skeleton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import CheckIcon from '@mui/icons-material/CheckCircleOutline';
import CloseIcon from '@mui/icons-material/HighlightOff';
import CancelIcon from '@mui/icons-material/DoNotDisturbOnOutlined';
import MailIcon from '@mui/icons-material/MailOutline';
import { ordersApi } from '../../api/endpoints';
import { getErrorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { StatusChip } from '../../components/StatusChip';
import { DecisionDialog, type Decision } from '../approvals/DecisionDialog';
import { formatDateTime, formatMoney, humanize } from '../../utils/format';
import type { Order, StatusHistory } from '../../types';

const HIDE_ON_PHONE = { display: { xs: 'none', sm: 'table-cell' } };

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <Paper sx={{ p: 2.5, mb: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
        {action}
      </Box>
      {children}
    </Paper>
  );
}

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <Box sx={{ mb: 1.5 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" component="div">
        {value}
      </Typography>
    </Box>
  );
}

const DOT_COLORS: Record<string, string> = {
  PENDING_APPROVAL: '#b45309',
  APPROVED: '#1d4ed8',
  COMPLETED: '#15803d',
  REJECTED: '#b91c1c',
  CANCELLED: '#6b7280',
};

function Timeline({ history }: { history: StatusHistory[] }) {
  return (
    <Box>
      {history.map((h, index) => (
        <Box key={h.id} sx={{ display: 'flex', gap: 1.5 }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <Box
              sx={{
                width: 12,
                height: 12,
                mt: 0.5,
                borderRadius: '50%',
                bgcolor: DOT_COLORS[h.to_status],
                boxShadow: '0 0 0 3px #fff',
              }}
            />
            {index < history.length - 1 && <Box sx={{ width: 2, flex: 1, bgcolor: 'divider', my: 0.5 }} />}
          </Box>
          <Box sx={{ pb: 2, minWidth: 0 }}>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>
              {humanize(h.to_status)}
            </Typography>
            <Typography variant="caption" color="text.secondary" component="div">
              {formatDateTime(h.created_at)}
              {h.changed_by ? ` · ${h.changed_by.name}` : ''}
            </Typography>
            {h.comment && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {h.comment}
              </Typography>
            )}
          </Box>
        </Box>
      ))}
    </Box>
  );
}

export default function OrderDetailPage() {
  const { orderId } = useParams();
  const id = Number(orderId);
  const { user, can } = useAuth();
  const [decision, setDecision] = useState<Decision | null>(null);

  const {
    data: order,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['order', id],
    queryFn: ({ signal }) => ordersApi.get(id, signal),
    enabled: Number.isFinite(id),
    // Emails wait in the outbox until the background worker sends them - poll while any are queued.
    refetchInterval: (query) => {
      const o = query.state.data as Order | undefined;
      const queued = o?.emails.some((e) => e.status === 'QUEUED');
      return queued && query.state.dataUpdateCount < 40 ? 2000 : false;
    },
  });

  if (isLoading) return <Skeleton variant="rounded" height={400} />;
  if (error || !order) return <Alert severity="error">{getErrorMessage(error, 'Order not found')}</Alert>;

  const pending = order.status === 'PENDING_APPROVAL';
  const isOwn = order.created_by.id === user?.id;
  const canDecide = pending && can('order:approve');
  const canCancel = pending && (isOwn || can('order:cancel:any'));
  // Emails go out in the background right after saving; only a just-created order is "still sending".
  const justCreated = Date.now() - new Date(order.created_at).getTime() < 60_000;

  return (
    <>
      <Breadcrumbs sx={{ mb: 1 }}>
        <Link component={RouterLink} to="/orders" underline="hover" color="inherit">
          Sales orders
        </Link>
        <Typography color="text.primary">{order.order_number}</Typography>
      </Breadcrumbs>

      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: { md: 'center' },
          flexDirection: { xs: 'column', md: 'row' },
          gap: 2,
          mb: 3,
        }}
      >
        <Box>
          <Stack direction="row" spacing={1.5} alignItems="center" useFlexGap flexWrap="wrap">
            <Typography variant="h4" sx={{ wordBreak: 'keep-all', fontSize: { xs: '1.35rem', sm: '1.6rem' } }}>
              {order.order_number}
            </Typography>
            <StatusChip status={order.status} size="medium" />
          </Stack>
          <Typography color="text.secondary" sx={{ mt: 0.5 }}>
            Created {formatDateTime(order.created_at)} by {order.created_by.name}
          </Typography>
        </Box>
        <Stack
          direction="row"
          spacing={1}
          useFlexGap
          flexWrap="wrap"
          sx={{ '& .MuiButton-root': { whiteSpace: 'nowrap' } }}
        >
          {canCancel && (
            <Button variant="outlined" color="inherit" startIcon={<CancelIcon />} onClick={() => setDecision('cancel')}>
              Cancel order
            </Button>
          )}
          {canDecide && (
            <>
              <Tooltip describeChild title={isOwn ? 'You cannot decide on your own order' : ''}>
                <span>
                  <Button
                    variant="outlined"
                    color="error"
                    startIcon={<CloseIcon />}
                    disabled={isOwn}
                    onClick={() => setDecision('reject')}
                  >
                    Reject
                  </Button>
                </span>
              </Tooltip>
              <Tooltip describeChild title={isOwn ? 'You cannot decide on your own order' : ''}>
                <span>
                  <Button
                    variant="contained"
                    color="success"
                    startIcon={<CheckIcon />}
                    disabled={isOwn}
                    onClick={() => setDecision('approve')}
                  >
                    Approve
                  </Button>
                </span>
              </Tooltip>
            </>
          )}
        </Stack>
      </Box>

      {pending && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          This order exceeds the {formatMoney(order.approval?.threshold_amount)} approval threshold and is waiting for a
          manager. Stock will be deducted when it is approved.
        </Alert>
      )}
      {order.status === 'REJECTED' && order.approval?.comment && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Rejected by {order.approval.decided_by?.name}: {order.approval.comment}
        </Alert>
      )}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 8 }}>
          <Section title="Items">
            <Box sx={{ overflowX: 'auto' }} tabIndex={0} role="region" aria-label="Order items">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Product</TableCell>
                    <TableCell align="right">Qty</TableCell>
                    <TableCell align="right" sx={HIDE_ON_PHONE}>
                      Unit price
                    </TableCell>
                    <TableCell align="right">Line total</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {order.items.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>
                          {item.product.name}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {item.product.sku}
                          {/* On phones the unit price moves under the product name instead of its own column */}
                          <Box component="span" sx={{ display: { xs: 'inline', sm: 'none' } }}>
                            {` · ${formatMoney(item.unit_price)} each`}
                          </Box>
                        </Typography>
                      </TableCell>
                      <TableCell align="right">{item.quantity}</TableCell>
                      <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums', ...HIDE_ON_PHONE }}>
                        {formatMoney(item.unit_price)}
                      </TableCell>
                      <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                        {formatMoney(item.line_total)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
            <Box sx={{ ml: 'auto', maxWidth: 300, mt: 2 }}>
              {[
                ['Subtotal', formatMoney(order.subtotal)],
                [`Tax (${order.tax_rate}%)`, formatMoney(order.tax_amount)],
              ].map(([label, value]) => (
                <Box key={label} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.5 }}>
                  <Typography color="text.secondary">{label}</Typography>
                  <Typography sx={{ fontVariantNumeric: 'tabular-nums' }}>{value}</Typography>
                </Box>
              ))}
              <Divider sx={{ my: 1 }} />
              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                <Typography sx={{ fontWeight: 700 }}>Total</Typography>
                <Typography sx={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                  {formatMoney(order.total_amount)}
                </Typography>
              </Box>
            </Box>
            {order.notes && (
              <Box sx={{ mt: 2, p: 1.5, bgcolor: 'grey.50', borderRadius: 2 }}>
                <Typography variant="caption" color="text.secondary">
                  Notes
                </Typography>
                <Typography variant="body2">{order.notes}</Typography>
              </Box>
            )}
          </Section>

          <Section title="Email notifications">
            {order.emails.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                {!order.requires_approval
                  ? 'No emails for this order: it was within the approval threshold.'
                  : justCreated
                    ? 'Sending…'
                    : 'No notification emails were recorded for this order.'}
              </Typography>
            ) : (
              <Stack spacing={1.5}>
                {order.emails.map((email) => (
                  <Stack key={email.id} direction="row" spacing={1.5} alignItems="flex-start">
                    <MailIcon fontSize="small" sx={{ color: 'text.secondary', mt: 0.25 }} />
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {email.subject}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        To {email.to_email} · {formatDateTime(email.created_at)}
                      </Typography>
                      {email.error && (
                        <Typography variant="caption" color="error" component="div">
                          {email.error}
                        </Typography>
                      )}
                    </Box>
                    <StatusChip status={email.status} />
                  </Stack>
                ))}
              </Stack>
            )}
          </Section>
        </Grid>

        <Grid size={{ xs: 12, lg: 4 }}>
          <Section title="Customer">
            <Field label="Name" value={order.customer.name} />
            <Field label="Email" value={order.customer.email} />
          </Section>

          {order.approval && (
            <Section title="Approval">
              <Field label="Status" value={<StatusChip status={order.approval.status} />} />
              <Field label="Threshold at time of order" value={formatMoney(order.approval.threshold_amount)} />
              <Field label="Requested" value={formatDateTime(order.approval.requested_at)} />
              {order.approval.decided_at && (
                <>
                  <Field label="Decided by" value={order.approval.decided_by?.name ?? '—'} />
                  <Field label="Decided" value={formatDateTime(order.approval.decided_at)} />
                  {order.approval.comment && <Field label="Comment" value={order.approval.comment} />}
                </>
              )}
            </Section>
          )}

          <Section title="Status history">
            <Timeline history={order.history} />
          </Section>
        </Grid>
      </Grid>

      <DecisionDialog order={decision ? order : null} decision={decision} onClose={() => setDecision(null)} />
    </>
  );
}
