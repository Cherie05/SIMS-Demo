# Security policy

## Reporting a vulnerability

Please **don't open a public issue**. Email the maintainers at the address in the repository
profile (or use GitHub's private vulnerability reporting) with:

- what you found and where (URL, endpoint, file),
- how to reproduce it,
- the impact you think it has.

We acknowledge reports within 2 working days, give a remediation estimate within 5, and credit
reporters who want to be credited once a fix ships. Please give us reasonable time to fix before
disclosure and don't access other people's data or degrade the service while testing.

## Supported versions

Only the latest release receives security fixes.

## What is in place

A summary; details in [docs/security/threat-model.md](docs/security/threat-model.md) and
[docs/enterprise-readiness.md](docs/enterprise-readiness.md).

- Two-step sign-in (one-time code or authenticator app with recovery codes), Argon2id passwords,
  short-lived access tokens, rotating refresh tokens with reuse detection, idle and absolute
  session timeouts, immediate revocation, new-device alerts.
- Role-based access with fine-grained permissions, deny by default (enforced by a test over the
  whole API), object-level checks, an append-only audit trail enforced by database triggers.
- Strict security headers and CSP, HSTS behind HTTPS, CSRF protection for the cookie endpoints,
  rate limiting at the edge and per user/IP/account, request size and content-type limits.
- Least-privilege database accounts, TLS to MySQL, secrets from the environment or files,
  field-level encryption for authenticator secrets, encrypted and restore-tested backups.
- Hardened containers (non-root, read-only, no capabilities), pinned and hash-locked dependencies,
  CI with SAST, secret scanning, dependency and image scanning, SBOMs, signed images.
