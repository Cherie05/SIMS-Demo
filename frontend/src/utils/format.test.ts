import { describe, expect, it } from 'vitest';
import { formatMoney, formatNumber, humanize } from './format';
import { describeUserAgent } from './userAgent';

describe('humanize', () => {
  it('turns API enums into labels', () => {
    expect(humanize('PENDING_APPROVAL')).toBe('Pending Approval');
    expect(humanize('success')).toBe('Success');
  });
});

describe('formatting', () => {
  it('formats rupees and numbers the Indian way', () => {
    expect(formatMoney(1234567.5)).toBe('₹12,34,567.50');
    expect(formatNumber(100000)).toBe('1,00,000');
    expect(formatMoney(null)).toBe('₹0.00');
  });
});

describe('describeUserAgent', () => {
  it.each([
    [
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36',
      'Chrome on Windows',
    ],
    [
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
      'Safari on macOS',
    ],
    ['Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0', 'Firefox on Linux'],
    ['Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/141.0 Safari/537.36 Edg/141.0', 'Edge on Windows'],
    ['curl/8.19.0', 'API client'],
  ])('recognises %s', (ua, expected) => {
    expect(describeUserAgent(ua)).toBe(expected);
  });

  it('copes with a missing value', () => {
    expect(describeUserAgent(null)).toBe('Unknown device');
  });
});
