# Data inventory, classification and retention

| Data | Where | Class | Protection | Retention |
|---|---|---|---|---|
| Password hashes | `users.password_hash` | Restricted | Argon2id (19 MiB, 2 iterations); never logged | life of account |
| Authenticator secrets | `users.totp_*_encrypted` | Restricted | Fernet (AES-128-CBC + HMAC), key outside the DB | until disabled |
| Recovery codes, one-time codes | `mfa_recovery_codes`, `otp_challenges` | Restricted | keyed HMAC only; codes in the outbox encrypted and wiped after sending | codes: 1 day after expiry |
| Refresh tokens / sessions | `refresh_tokens`, `user_sessions` | Restricted | SHA-256 hash only; IP and user agent kept for the user's device list | 30 days after end |
| Staff identity | `users` (name, email, role) | Confidential (PII) | access by admins only | life of account; deactivate, don't delete (orders reference users) |
| Customer contacts | `customers` (name, email, phone, address) | Confidential (PII) | authenticated staff only; never in logs | while the business relationship lasts |
| Orders, approvals, stock ledger | business tables | Confidential | permission checks; order-level ownership | No automated deletion; business owner defines applicable record-retention policy |
| Audit trail | `audit_logs` | Confidential, integrity-critical | append-only (triggers); admin read | 400 days (scheduled purge) |
| Email delivery log | `email_logs` | Internal | admins and order viewers; sign-in codes never stored | 365 days |
| Background jobs | `outbox_jobs` | Internal | identifiers only after completion | 30 days (dead: 90) |
| Application logs | stdout → log platform | Internal | secrets redacted; no query strings; IPs and user ids for security | per log platform policy (recommend 90 days) |
| Backups | `BACKUP_DIR`, off-site copy | Restricted | AES-256 + HMAC, key in secret manager | 14 days local; off-site per policy |
| Browser telemetry | metrics + log lines | Internal | page path only (no query string); not stored in the DB | metrics retention (15 days) |

## Personal data handling

- **Purpose limitation**: staff data for access control and accountability; customer data for order
  processing and correspondence.
- **Access requests / export**: admin exports customer and user records through the API; the audit
  log is exported per user (`actor_id` filter).
- **Erasure**: customers and users are deactivated so existing orders retain their references.
  Personal-field anonymisation and applicable retention obligations need an approved operational
  process; the application does not provide an automated erasure workflow.
- **Processors**: none by default - fonts, telemetry and monitoring are self-hosted. The SMTP provider
  is a processor when `OTP_DELIVERY=email` or notifications are enabled.
- **Breach handling**: see [runbook - incident response](runbook.md#incident-response).
