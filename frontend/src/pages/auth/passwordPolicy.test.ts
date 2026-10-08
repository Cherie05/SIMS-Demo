import { describe, expect, it } from 'vitest';
import { meetsPasswordPolicy, PASSWORD_MAX } from './passwordPolicy';

describe('password policy (mirrors the API)', () => {
  it.each(['Sales@2026', 'correct horse battery 9', 'ünïcödé-pässwörd-1'])('accepts %s', (value) => {
    expect(meetsPasswordPolicy(value)).toBe(true);
  });

  it.each([
    ['too short', 'ab1'],
    ['no digit', 'onlyletters'],
    ['no letter', '1234567890'],
    ['too long', `a1${'x'.repeat(PASSWORD_MAX)}`],
  ])('rejects a password that is %s', (_reason, value) => {
    expect(meetsPasswordPolicy(value)).toBe(false);
  });
});
