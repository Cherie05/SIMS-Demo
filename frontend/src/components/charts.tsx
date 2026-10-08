import { Box, Paper, Stack, Typography } from '@mui/material';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from 'recharts';
import { brand, chart } from '../theme';
import { formatMoney, formatMoneyCompact, formatNumber, formatShortDay } from '../utils/format';

const axisTick = { fill: chart.axis, fontSize: 12 };

/** Round axis ticks (0, 100K, 200K…): step is 1, 2, 2.5 or 5 × 10^n. */
function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? raw;
  const top = Math.ceil(max / step) * step;
  return Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step);
}

function TooltipCard({ title, rows }: { title: string; rows: { label: string; value: string; color?: string }[] }) {
  return (
    <Paper sx={{ px: 1.5, py: 1, boxShadow: '0 8px 24px rgba(16,24,40,.12)', minWidth: 170 }}>
      <Typography variant="caption" color="text.secondary">
        {title}
      </Typography>
      {rows.map((row) => (
        <Stack key={row.label} direction="row" alignItems="center" spacing={1} sx={{ mt: 0.25 }}>
          {row.color && <Box sx={{ width: 8, height: 8, borderRadius: '2px', bgcolor: row.color }} />}
          <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
            {row.label}
          </Typography>
          <Typography variant="body2" sx={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
            {row.value}
          </Typography>
        </Stack>
      ))}
    </Paper>
  );
}

/** Tiny trend line for KPI cards. Decorative: the card states the value. */
export function Sparkline({ data, width = 96 }: { data: number[]; width?: number }) {
  const points = data.map((value, index) => ({ index, value }));
  return (
    <Box aria-hidden sx={{ width, height: 44, flexShrink: 0 }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 4, right: 2, bottom: 2, left: 2 }}>
          <Area
            type="monotone"
            dataKey="value"
            stroke={chart.series}
            strokeWidth={2}
            fill={chart.series}
            fillOpacity={0.12}
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </Box>
  );
}

export interface OverviewPoint {
  date: string;
  current: number;
  previous: number | null;
  orders: number;
}

function OverviewTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload as OverviewPoint;
  const rows = [
    { label: 'This period', value: formatMoney(point.current), color: chart.series },
    ...(point.previous !== null
      ? [{ label: 'Previous period', value: formatMoney(point.previous), color: chart.context }]
      : []),
    { label: 'Orders', value: formatNumber(point.orders) },
  ];
  return <TooltipCard title={formatShortDay(point.date)} rows={rows} />;
}

/** Revenue per day for the selected period, against the period before it. */
export function OverviewChart({ data, label }: { data: OverviewPoint[]; label: string }) {
  const ticks = niceTicks(Math.max(0, ...data.map((d) => Math.max(d.current, d.previous ?? 0))));
  // The wrapper carries the text alternative (the Table view has the values); the drawing is hidden from assistive tech.
  return (
    <Box role="img" aria-label={label}>
      <Box aria-hidden>
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 4 }} accessibilityLayer={false}>
            <CartesianGrid vertical={false} stroke={chart.grid} />
            <XAxis
              dataKey="date"
              tickFormatter={formatShortDay}
              tick={axisTick}
              tickLine={false}
              axisLine={{ stroke: brand.lineStrong }}
              minTickGap={32}
            />
            <YAxis
              ticks={ticks}
              domain={[0, ticks[ticks.length - 1]]}
              tickFormatter={(v: number) => formatMoneyCompact(v)}
              tick={axisTick}
              tickLine={false}
              axisLine={false}
              width={64}
            />
            <Tooltip content={<OverviewTooltip />} cursor={{ stroke: chart.axis, strokeWidth: 1 }} />
            <Line
              type="monotone"
              dataKey="previous"
              stroke={chart.context}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: chart.context, stroke: chart.surface, strokeWidth: 2 }}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="current"
              stroke={chart.series}
              strokeWidth={2}
              fill={chart.series}
              fillOpacity={0.1}
              dot={false}
              activeDot={{ r: 5, fill: chart.series, stroke: chart.surface, strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </Box>
    </Box>
  );
}

export function LegendKey({ color, label, line }: { color: string; label: string; line?: boolean }) {
  return (
    <Stack direction="row" alignItems="center" spacing={0.75}>
      <Box sx={{ width: line ? 14 : 10, height: line ? 3 : 10, borderRadius: line ? 2 : '3px', bgcolor: color }} />
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
    </Stack>
  );
}

export interface DonutSlice {
  key: string;
  label: string;
  value: number;
  color: string;
}

/** Part-to-whole with a labelled legend (counts and shares), so colour never carries meaning alone. */
export function StatusDonut({ slices, centerLabel }: { slices: DonutSlice[]; centerLabel: string }) {
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  const shown = slices.filter((s) => s.value > 0);
  const summary = slices.map((s) => `${s.label} ${s.value}`).join(', ');
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} alignItems="center" spacing={3}>
      <Box
        role="img"
        aria-label={`${centerLabel}: ${summary}`}
        sx={{ position: 'relative', width: 168, height: 168, flexShrink: 0 }}
      >
        {/* The wrapper carries the text alternative; the drawing is hidden from assistive tech. */}
        <Box aria-hidden sx={{ width: '100%', height: '100%' }}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart accessibilityLayer={false}>
              <Pie
                data={shown.length ? shown : [{ key: 'none', label: 'None', value: 1, color: chart.track }]}
                dataKey="value"
                nameKey="label"
                innerRadius={55}
                outerRadius={80}
                startAngle={90}
                endAngle={-270}
                stroke={chart.surface}
                strokeWidth={2}
                isAnimationActive={false}
                rootTabIndex={-1}
              >
                {(shown.length ? shown : [{ key: 'none', color: chart.track }]).map((s) => (
                  <Cell key={s.key} fill={s.color} />
                ))}
              </Pie>
              {shown.length > 0 && (
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const slice = payload[0].payload as DonutSlice;
                    const share = total ? Math.round((slice.value / total) * 100) : 0;
                    return (
                      <TooltipCard
                        title={slice.label}
                        rows={[{ label: `${share}% of orders`, value: formatNumber(slice.value), color: slice.color }]}
                      />
                    );
                  }}
                />
              )}
            </PieChart>
          </ResponsiveContainer>
        </Box>
        <Box
          aria-hidden
          sx={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', pointerEvents: 'none' }}
        >
          <Box sx={{ textAlign: 'center' }}>
            <Typography sx={{ fontSize: 26, fontWeight: 700, lineHeight: 1.1 }}>{formatNumber(total)}</Typography>
            <Typography variant="caption" color="text.secondary">
              {centerLabel}
            </Typography>
          </Box>
        </Box>
      </Box>
      <Stack component="ul" spacing={1.25} sx={{ listStyle: 'none', p: 0, m: 0, flex: 1, width: '100%' }}>
        {slices.map((slice) => (
          <Stack key={slice.key} component="li" direction="row" alignItems="center" spacing={1.25}>
            <Box sx={{ width: 10, height: 10, borderRadius: '3px', bgcolor: slice.color, flexShrink: 0 }} />
            <Typography variant="body2" sx={{ flex: 1, whiteSpace: 'nowrap' }}>
              {slice.label}
            </Typography>
            <Typography variant="body2" sx={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
              {formatNumber(slice.value)}
            </Typography>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ width: 40, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
            >
              {total ? `${Math.round((slice.value / total) * 100)}%` : '0%'}
            </Typography>
          </Stack>
        ))}
      </Stack>
    </Stack>
  );
}

export interface BarRow {
  key: string | number;
  label: string;
  sublabel?: string;
  value: number;
}

/** Labelled horizontal bars on a light track, value at the end (one hue: it's magnitude, not identity). */
export function BarRows({ rows, format = formatNumber }: { rows: BarRow[]; format?: (value: number) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <Stack component="ul" spacing={2} sx={{ listStyle: 'none', p: 0, m: 0 }}>
      {rows.map((row) => (
        <Box
          key={row.key}
          component="li"
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr auto', sm: 'minmax(0, 210px) 1fr 72px' },
            alignItems: 'center',
            columnGap: 2,
            rowGap: 0.75,
          }}
        >
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" noWrap title={row.label} sx={{ fontWeight: 500 }}>
              {row.label}
            </Typography>
            {row.sublabel && (
              <Typography variant="caption" color="text.secondary" noWrap component="p">
                {row.sublabel}
              </Typography>
            )}
          </Box>
          <Box
            aria-hidden
            sx={{
              gridColumn: { xs: '1 / -1', sm: 'auto' },
              gridRow: { xs: 2, sm: 'auto' },
              height: 8,
              borderRadius: 4,
              bgcolor: chart.track,
              overflow: 'hidden',
            }}
          >
            <Box
              sx={{
                width: `${Math.max(2, (row.value / max) * 100)}%`,
                height: '100%',
                borderRadius: 4,
                bgcolor: chart.series,
              }}
            />
          </Box>
          <Typography variant="body2" sx={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}>
            {format(row.value)}
          </Typography>
        </Box>
      ))}
    </Stack>
  );
}
