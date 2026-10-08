import { useMemo, useState, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import {
  Alert,
  Box,
  Button,
  Grid2 as Grid,
  ListItemIcon,
  Menu,
  MenuItem,
  Paper,
  Skeleton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import CalendarIcon from '@mui/icons-material/CalendarTodayOutlined';
import ExpandIcon from '@mui/icons-material/KeyboardArrowDown';
import CheckIcon from '@mui/icons-material/Check';
import AddIcon from '@mui/icons-material/Add';
import ApprovalIcon from '@mui/icons-material/FactCheckOutlined';
import WarehouseIcon from '@mui/icons-material/WarehouseOutlined';
import { dashboardApi, ordersApi, productsApi } from '../api/endpoints';
import { getErrorMessage } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { PageHeader } from '../components/PageHeader';
import { KpiCard, DeltaChip } from '../components/KpiCard';
import { StatusChip } from '../components/StatusChip';
import { BarRows, LegendKey, OverviewChart, StatusDonut, type OverviewPoint } from '../components/charts';
import { brand, chart } from '../theme';
import { formatDate, formatMoney, formatMoneyCompact, formatNumber, formatShortDay } from '../utils/format';

const PERIODS = [
  { days: 7, label: 'Last 7 days' },
  { days: 30, label: 'Last 30 days' },
  { days: 90, label: 'Last 90 days' },
  { days: 365, label: 'Last 12 months' },
];

const sum = (values: number[]) => values.reduce((total, v) => total + v, 0);
const change = (current: number, previous: number) => (previous > 0 ? ((current - previous) / previous) * 100 : null);

function Panel({
  title,
  subtitle,
  action,
  children,
  fillHeight = true,
}: {
  title: string;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  fillHeight?: boolean;
}) {
  return (
    <Paper sx={{ p: { xs: 2, sm: 2.5 }, height: fillHeight ? '100%' : 'auto' }}>
      <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1} sx={{ mb: 2.5 }}>
        <Box>
          <Typography variant="subtitle1">{title}</Typography>
          {subtitle && (
            <Typography variant="body2" color="text.secondary">
              {subtitle}
            </Typography>
          )}
        </Box>
        {action}
      </Stack>
      {children}
    </Paper>
  );
}

function PeriodPicker({ value, onChange }: { value: number; onChange: (days: number) => void }) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const current = PERIODS.find((p) => p.days === value) ?? PERIODS[1];
  return (
    <>
      <Button
        variant="outlined"
        color="inherit"
        startIcon={<CalendarIcon sx={{ fontSize: '18px !important' }} />}
        endIcon={<ExpandIcon />}
        onClick={(e) => setAnchor(e.currentTarget)}
        aria-haspopup="menu"
        aria-label={`Period: ${current.label}`}
        sx={{ color: brand.ink, bgcolor: '#fff' }}
      >
        {current.label}
      </Button>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
        {PERIODS.map((period) => (
          <MenuItem
            key={period.days}
            selected={period.days === value}
            onClick={() => {
              onChange(period.days);
              setAnchor(null);
            }}
          >
            <ListItemIcon>{period.days === value && <CheckIcon fontSize="small" />}</ListItemIcon>
            {period.label}
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}

function OverviewStat({
  label,
  value,
  delta,
  first,
}: {
  label: string;
  value: string;
  delta?: number | null;
  first?: boolean;
}) {
  return (
    <Box sx={{ pl: { md: first ? 0 : 2.5 }, borderLeft: { md: first ? 'none' : `1px solid ${brand.line}` } }}>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 0.5 }} useFlexGap flexWrap="wrap">
        <Typography sx={{ fontSize: 22, fontWeight: 700 }}>{value}</Typography>
        {delta !== undefined && <DeltaChip change={delta} />}
      </Stack>
    </Box>
  );
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const { user, can } = useAuth();
  const isApprover = can('order:approve');
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = Number(searchParams.get('period'));
  const days = PERIODS.some((p) => p.days === requested) ? requested : 30;
  const periodLabel = PERIODS.find((p) => p.days === days)!.label.toLowerCase();
  const [view, setView] = useState<'chart' | 'table'>('chart');

  const summary = useQuery({ queryKey: ['dashboard', 'summary'], queryFn: dashboardApi.summary });
  // Twice the period: the first half is the comparison period for the change indicators.
  const trend = useQuery({
    queryKey: ['dashboard', 'trend', days * 2],
    queryFn: () => dashboardApi.salesTrend(days * 2),
    placeholderData: keepPreviousData,
  });
  const top = useQuery({
    queryKey: ['dashboard', 'top-products', days],
    queryFn: () => dashboardApi.topProducts(5, days),
    placeholderData: keepPreviousData,
  });
  const lowStock = useQuery({
    queryKey: ['products', { low_stock: true, page_size: 5 }],
    queryFn: () => productsApi.list({ low_stock: true, is_active: true, page_size: 5 }),
  });
  const recent = useQuery({ queryKey: ['orders', { page_size: 6 }], queryFn: () => ordersApi.list({ page_size: 6 }) });

  const stats = useMemo(() => {
    const points = trend.data ?? [];
    const current = points.slice(-days);
    const previous = points.slice(0, Math.max(0, points.length - days));
    const revenue = sum(current.map((p) => p.revenue));
    const prevRevenue = sum(previous.map((p) => p.revenue));
    const orders = sum(current.map((p) => p.orders));
    const prevOrders = sum(previous.map((p) => p.orders));
    const aov = orders ? revenue / orders : 0;
    const prevAov = prevOrders ? prevRevenue / prevOrders : 0;
    const overview: OverviewPoint[] = current.map((point, i) => ({
      date: point.date,
      current: point.revenue,
      previous: previous[i]?.revenue ?? null,
      orders: point.orders,
    }));
    return {
      revenue,
      orders,
      aov,
      revenueChange: change(revenue, prevRevenue),
      ordersChange: change(orders, prevOrders),
      aovChange: change(aov, prevAov),
      revenueSeries: current.map((p) => p.revenue),
      orderSeries: current.map((p) => p.orders),
      overview,
    };
  }, [trend.data, days]);

  const s = summary.data;
  const loadingTrend = trend.isLoading;

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={`Welcome back, ${user?.name.split(' ')[0]}. Here's how sales and stock are doing.`}
        actions={
          <>
            <PeriodPicker value={days} onChange={(d) => setSearchParams(d === 30 ? {} : { period: String(d) })} />
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => navigate('/orders/new')}>
              New order
            </Button>
          </>
        }
      />

      {[summary, trend, top, lowStock, recent]
        .filter((query) => query.isError)
        .map((query, index) => (
          <Alert
            key={index}
            severity="error"
            sx={{ mb: 3 }}
            action={
              <Button color="inherit" onClick={() => void query.refetch()}>
                Retry
              </Button>
            }
          >
            {getErrorMessage(query.error)}
          </Alert>
        ))}

      <Grid container spacing={2.5} sx={{ mb: 2.5 }}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KpiCard
            label="Revenue"
            value={formatMoneyCompact(stats.revenue)}
            change={stats.revenueChange}
            caption={`${formatNumber(stats.orders)} orders · ${periodLabel}`}
            trend={stats.revenueSeries}
            loading={loadingTrend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KpiCard
            label="Completed orders"
            value={formatNumber(stats.orders)}
            change={stats.ordersChange}
            caption={`Avg. ${formatMoneyCompact(stats.aov)} each`}
            trend={stats.orderSeries}
            loading={loadingTrend}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KpiCard
            label="Pending approvals"
            value={formatNumber(s?.approvals.pending)}
            caption={
              s &&
              `${formatMoneyCompact(s.approvals.pending_value)} awaiting${
                s.approvals.average_decision_hours != null
                  ? ` · ~${Math.round(s.approvals.average_decision_hours)}h to decide`
                  : ''
              }`
            }
            icon={<ApprovalIcon />}
            loading={summary.isLoading}
            action={
              isApprover && Boolean(s?.approvals.pending) ? (
                <Button size="small" onClick={() => navigate('/approvals')} sx={{ minWidth: 0, py: 0 }}>
                  Review
                </Button>
              ) : undefined
            }
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <KpiCard
            label="Inventory value"
            value={s && formatMoneyCompact(s.inventory.inventory_value)}
            caption={s && `${formatNumber(s.inventory.total_units)} units · ${s.inventory.active_products} products`}
            badge={
              s && s.inventory.low_stock > 0 ? (
                <Box
                  component="button"
                  onClick={() => navigate('/products?low_stock=1')}
                  sx={{
                    border: 0,
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                    px: 0.75,
                    py: 0.25,
                    borderRadius: 1.5,
                    bgcolor: brand.warningSoft,
                    color: '#94570a',
                    fontSize: 12,
                    fontWeight: 700,
                  }}
                >
                  {s.inventory.low_stock} low stock
                </Box>
              ) : undefined
            }
            icon={<WarehouseIcon />}
            loading={summary.isLoading}
          />
        </Grid>
      </Grid>

      <Paper sx={{ p: { xs: 2, sm: 2.5 }, mb: 2.5 }}>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          justifyContent="space-between"
          alignItems={{ sm: 'flex-start' }}
          spacing={1.5}
          sx={{ mb: 2.5 }}
        >
          <Box>
            <Typography variant="subtitle1">Sales overview</Typography>
            <Typography variant="body2" color="text.secondary">
              Completed orders, {periodLabel} compared with the period before
            </Typography>
          </Box>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={view}
            onChange={(_, v) => v && setView(v)}
            aria-label="Chart or table view"
          >
            <ToggleButton value="chart">Chart</ToggleButton>
            <ToggleButton value="table">Table</ToggleButton>
          </ToggleButtonGroup>
        </Stack>

        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' },
            gap: { xs: 2, md: 0 },
            mb: 3,
          }}
        >
          <OverviewStat first label="Revenue" value={formatMoneyCompact(stats.revenue)} delta={stats.revenueChange} />
          <OverviewStat label="Orders" value={formatNumber(stats.orders)} delta={stats.ordersChange} />
          <OverviewStat label="Avg. order value" value={formatMoneyCompact(stats.aov)} delta={stats.aovChange} />
          <OverviewStat label="Awaiting approval" value={s ? formatMoneyCompact(s.approvals.pending_value) : '—'} />
        </Box>

        {loadingTrend ? (
          <Skeleton variant="rounded" height={300} />
        ) : view === 'chart' ? (
          <>
            <Stack direction="row" spacing={2.5} sx={{ mb: 1 }}>
              <LegendKey color={chart.series} label="This period" />
              <LegendKey color={chart.context} label="Previous period" line />
            </Stack>
            <OverviewChart
              data={stats.overview}
              label={`Revenue per day, ${periodLabel}, against the previous period. The Table view lists the values.`}
            />
          </>
        ) : (
          <Box sx={{ maxHeight: 320, overflow: 'auto' }} tabIndex={0} role="region" aria-label="Daily revenue">
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell>Day</TableCell>
                  <TableCell align="right">Orders</TableCell>
                  <TableCell align="right">Revenue</TableCell>
                  <TableCell align="right">Previous period</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {[...stats.overview].reverse().map((p) => (
                  <TableRow key={p.date}>
                    <TableCell>{formatShortDay(p.date)}</TableCell>
                    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {p.orders}
                    </TableCell>
                    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {formatMoney(p.current)}
                    </TableCell>
                    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums', color: 'text.secondary' }}>
                      {p.previous === null ? '—' : formatMoney(p.previous)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        )}
      </Paper>

      <Grid container spacing={2.5} sx={{ mb: 2.5 }}>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Panel title="Orders by status" subtitle="All orders to date">
            {summary.isLoading || !s ? (
              <Skeleton variant="rounded" height={184} />
            ) : (
              <StatusDonut
                centerLabel="orders"
                slices={[
                  { key: 'completed', label: 'Completed', value: s.orders.completed, color: chart.series },
                  { key: 'pending', label: 'Pending approval', value: s.orders.pending_approval, color: chart.amber },
                  { key: 'rejected', label: 'Rejected', value: s.orders.rejected, color: chart.red },
                  { key: 'cancelled', label: 'Cancelled', value: s.orders.cancelled, color: chart.violet },
                ]}
              />
            )}
          </Panel>
        </Grid>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Panel title="Top products" subtitle={`By revenue, ${periodLabel}`}>
            {top.isLoading ? (
              <Skeleton variant="rounded" height={184} />
            ) : top.data?.length ? (
              <BarRows
                format={formatMoneyCompact}
                rows={top.data.map((p) => ({
                  key: p.product_id,
                  label: p.name,
                  sublabel: `${p.sku} · ${formatNumber(p.quantity_sold)} sold`,
                  value: p.revenue,
                }))}
              />
            ) : (
              <Typography color="text.secondary">No completed sales in this period yet.</Typography>
            )}
          </Panel>
        </Grid>
      </Grid>

      <Grid container spacing={2.5}>
        <Grid size={{ xs: 12, lg: 5 }}>
          <Panel
            title="Low stock"
            subtitle="At or below the reorder level"
            action={
              <Button size="small" onClick={() => navigate('/products?low_stock=1')}>
                View all
              </Button>
            }
          >
            {lowStock.isLoading ? (
              <Skeleton variant="rounded" height={160} />
            ) : lowStock.data?.items.length ? (
              <Stack spacing={1.5}>
                {lowStock.data.items.map((p) => {
                  const ratio = p.reorder_level ? Math.min(1, p.stock_qty / p.reorder_level) : 0;
                  return (
                    <Box key={p.id}>
                      <Stack direction="row" justifyContent="space-between" alignItems="baseline" spacing={1}>
                        <Typography variant="body2" sx={{ fontWeight: 500 }} noWrap>
                          {p.name}
                        </Typography>
                        <Typography
                          variant="body2"
                          sx={{
                            fontWeight: 700,
                            color: p.stock_qty === 0 ? brand.danger : '#94570a',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {p.stock_qty === 0 ? 'Out of stock' : `${p.stock_qty} left`}
                        </Typography>
                      </Stack>
                      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mt: 0.75 }}>
                        <Box
                          aria-hidden
                          sx={{ flex: 1, height: 6, borderRadius: 3, bgcolor: chart.track, overflow: 'hidden' }}
                        >
                          <Box
                            sx={{
                              width: `${Math.max(3, ratio * 100)}%`,
                              height: '100%',
                              borderRadius: 3,
                              bgcolor: p.stock_qty === 0 ? brand.danger : chart.amber,
                            }}
                          />
                        </Box>
                        <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
                          {p.sku} · reorder at {p.reorder_level}
                        </Typography>
                      </Stack>
                    </Box>
                  );
                })}
              </Stack>
            ) : (
              <Typography color="text.secondary">Every product is above its reorder level.</Typography>
            )}
          </Panel>
        </Grid>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Panel
            title="Recent orders"
            action={
              <Button size="small" onClick={() => navigate('/orders')}>
                View all
              </Button>
            }
          >
            <Box
              sx={{ overflowX: 'auto', mx: { xs: -2, sm: -2.5 } }}
              tabIndex={0}
              role="region"
              aria-label="Recent orders"
            >
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ pl: { xs: 2, sm: 2.5 } }}>Order</TableCell>
                    <TableCell>Customer</TableCell>
                    <TableCell sx={{ display: { xs: 'none', xl: 'table-cell' } }}>Date</TableCell>
                    <TableCell align="right">Total</TableCell>
                    <TableCell sx={{ pr: { xs: 2, sm: 2.5 } }}>Status</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {recent.data?.items.map((o) => (
                    <TableRow key={o.id} hover sx={{ cursor: 'pointer' }} onClick={() => navigate(`/orders/${o.id}`)}>
                      <TableCell sx={{ pl: { xs: 2, sm: 2.5 }, fontWeight: 600, whiteSpace: 'nowrap' }}>
                        {o.order_number}
                      </TableCell>
                      <TableCell sx={{ maxWidth: 180 }}>
                        <Typography variant="body2" noWrap>
                          {o.customer.name}
                        </Typography>
                      </TableCell>
                      <TableCell sx={{ display: { xs: 'none', xl: 'table-cell' }, whiteSpace: 'nowrap' }}>
                        {formatDate(o.created_at)}
                      </TableCell>
                      <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                        {formatMoney(o.total_amount)}
                      </TableCell>
                      <TableCell sx={{ pr: { xs: 2, sm: 2.5 } }}>
                        <StatusChip status={o.status} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          </Panel>
        </Grid>
      </Grid>
    </>
  );
}
