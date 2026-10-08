/** Same rules as the API's password policy (the API also refuses common passwords and ones built
 * from the account's name or email, and explains why). */
export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 128;

export const PASSWORD_RULES = [
  { label: `At least ${PASSWORD_MIN} characters`, test: (v: string) => v.length >= PASSWORD_MIN },
  { label: 'A letter and a number', test: (v: string) => /\p{L}/u.test(v) && /\d/.test(v) },
  { label: `At most ${PASSWORD_MAX} characters`, test: (v: string) => v.length <= PASSWORD_MAX },
];

export const meetsPasswordPolicy = (value: string) => PASSWORD_RULES.every((rule) => rule.test(value));
