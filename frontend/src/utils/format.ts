const currency = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 });
const compactCurrency = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  notation: 'compact',
  maximumFractionDigits: 1,
});
const number = new Intl.NumberFormat('en-IN');
const dateTime = new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
const date = new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium' });
const shortDate = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short' });

export const formatMoney = (value: number | null | undefined) => currency.format(value ?? 0);
export const formatMoneyCompact = (value: number) => compactCurrency.format(value);
export const formatNumber = (value: number | null | undefined) => number.format(value ?? 0);
export const formatDateTime = (value: string | null | undefined) => (value ? dateTime.format(new Date(value)) : '—');
export const formatDate = (value: string | null | undefined) => (value ? date.format(new Date(value)) : '—');
/** For 'YYYY-MM-DD' strings (no timezone shift). */
export const formatShortDay = (isoDay: string) => shortDate.format(new Date(`${isoDay}T00:00:00`));

export const humanize = (value: string) =>
  value
    .toLowerCase()
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
