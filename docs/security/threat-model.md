# Threat model (STRIDE)

Scope: the SIMS web app, API, worker, database, cache and their deployment as described in
[architecture](../architecture/README.md). Reviewed: 2026-10-07. Review again when a trust boundary,
an integration or the authentication flow changes, and at least yearly.

## Assets

| Asset | Why it matters | Classification |
|---|---|---|
| User credentials, second factors, sessions | account takeover → fraudulent approvals | Restricted |
| Orders, approvals, stock ledger | money and stock movements; integrity is the business | Confidential |
| Customer contact data | personal data (DPDP Act 2023 / GDPR) | Confidential (PII) |
| Audit trail | evidence for investigations and compliance | Confidential, integrity-critical |
| Secrets (JWT keys, Fernet keys, DB/SMTP passwords, backup key) | full compromise | Restricted |
| Backups | complete copy of the above | Restricted |

## Actors

Anonymous internet users; authenticated sales staff, managers and administrators (including a
malicious insider); an attacker holding a stolen password, cookie or token; a compromised dependency
or container image; an operator with server access.

## Threats and mitigations

### S - Spoofing identity

| Threat | Mitigation | Evidence |
|---|---|---|
| Password guessing / credential stuffing | per-account and per-IP failure limits (Valkey, shared by replicas), lockout audit, Argon2id, common-password block-list, 2nd factor on every sign-in, alert `SignInFailureSpike` | `test_security.py`, `test_rate_limit.py` |
| Stolen password | second factor (code or TOTP), new-device email | `test_accounts.py` |
| Stolen refresh cookie | httpOnly + Secure + SameSite=Strict, path-scoped; rotation with reuse detection ends the session and emails the user | `test_auth_flow.py` |
| Stolen access token | 15-minute lifetime, held in memory only, session id checked on every request (sign-out revokes immediately) | `test_accounts.py::test_signing_out_another_device_stops_its_token_immediately` |
| Forged JWT (alg=none, other key, other audience) | fixed algorithm, issuer, audience, type, key id; old keys only while rotating | `test_security.py` |
| Account enumeration | identical responses and timing for unknown emails (dummy hash); password-reset reply is the same either way | `test_accounts.py` |
| Spoofed client IP to dodge limits | X-Forwarded-For overwritten by nginx; only the edge is a trusted proxy | `frontend/api-proxy.conf` |

### T - Tampering

| Threat | Mitigation |
|---|---|
| SQL injection | SQLAlchemy parameters everywhere; search terms tested as data; Semgrep in CI |
| Mass assignment | `extra=forbid` input models; server-computed prices, totals and status |
| Overselling under concurrency | row locks in id order, stock re-checked at fulfilment, CHECK constraint `stock_qty >= 0` |
| Duplicate orders on retry | Idempotency-Key stored in the same transaction (unique index) |
| Rewriting the audit trail | database triggers block UPDATE/DELETE; app account has no DDL |
| Tampered backups | encrypt-then-MAC (HMAC verified before decrypting) |
| Supply-chain tampering | hash-locked Python deps, npm lockfile with `npm ci --ignore-scripts`, SHA-pinned CI actions, Dependabot with a 7-day cooldown, signed images + provenance on release |

### R - Repudiation

Every security event and business change is in the append-only audit trail with actor, IP, user
agent and request id; the same id appears in the proxy, API and worker logs. Logs are JSON and
shippable to a SIEM; the audit export is itself audited.

### I - Information disclosure

| Threat | Mitigation |
|---|---|
| Seeing other users' orders (IDOR) | object-level checks; 404 instead of 403 |
| XSS stealing tokens | strict CSP (`script-src 'self'`), React escaping, tokens not in storage, autoescaped email templates |
| Secrets in logs | redaction filter (bearer tokens, JWTs, password/secret/token fields); query strings never logged |
| Error details leaking | generic 500 body with a reference id; stack traces only in server logs |
| Sniffing internal traffic | TLS to MySQL required; internal networks |
| Leaked database | Argon2id passwords, hashed refresh tokens and codes, Fernet-encrypted TOTP secrets, encrypted backups |
| Third-party data processors | self-hosted fonts and telemetry; no analytics vendors |

### D - Denial of service

Request body limit (1 MB), JSON-only bodies, nginx connection and request-rate limits, per-user and
per-IP API budgets, statement timeout (15 s) and lock-wait timeout (10 s), connection-pool timeouts,
container CPU/memory/PID limits, paginated lists (max 100), slow emails moved off the request path,
telemetry endpoints that silently drop over-budget reports. Volumetric attacks need a WAF/CDN
(residual risk below).

### E - Elevation of privilege

Permissions per endpoint with a deny-by-default test over the whole API; role taken from the
database, never the token; no self-approval; no self role change or deactivation; last admin
protected; admin-only operations audited; containers non-root, read-only, no capabilities;
`sims_app` can't change the schema.

## OWASP Top 10 (2021) mapping

| Risk | Where it's handled |
|---|---|
| A01 Broken access control | permissions, object-level checks, deny-by-default test |
| A02 Cryptographic failures | TLS everywhere, Argon2id, Fernet, HMAC, no secrets in code |
| A03 Injection | ORM parameters, schema validation, CSP, autoescaping |
| A04 Insecure design | threat model, idempotency, transactional outbox, append-only audit |
| A05 Security misconfiguration | config validator refuses weak production settings, hardened containers, docs off in production |
| A06 Vulnerable components | pip-audit, npm audit, Trivy, Dependabot, SBOMs |
| A07 Identification & authentication failures | MFA, lockout, session controls |
| A08 Software & data integrity failures | lockfiles with hashes, signed images, SHA-pinned actions |
| A09 Logging & monitoring failures | audit trail, structured logs, metrics, alerts, runbook |
| A10 SSRF | the server makes no requests to user-supplied URLs |

## Residual risks and owners

| Risk | Treatment | Owner |
|---|---|---|
| Volumetric DDoS / bot traffic at internet scale | put a managed WAF/CDN (Cloudflare, AWS WAF) in front of the edge | Platform |
| `OTP_DELIVERY=log` exposes codes to anyone reading logs | demo only; production uses email or authenticator apps (start-up warning) | Product owner |
| `style-src 'unsafe-inline'` (required by MUI/Emotion) | scripts remain same-origin only; revisit with a nonce-based Emotion setup | Frontend |
| Single-host Compose deployment has no HA | run on Kubernetes/ECS with a managed MySQL HA pair for production SLAs | Platform |
| No SSO/SCIM | add OIDC when the customer has an identity provider | Product |
| No external penetration test yet | schedule before go-live and yearly | Security |
