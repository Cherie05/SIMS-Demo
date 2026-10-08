# Enterprise readiness and scope

The assignment is a single-company Sales & Inventory Management System using React, FastAPI,
Python and MySQL. The engineering checklist supplied alongside it informs the controls below.
MySQL remains the system of record. A production deployment also needs the company's domain,
mail service, secrets, backup destination and operational owners.

## Assignment requirements

| Requirement | Implementation | Verification |
|---|---|---|
| Products and customers | Validated forms, paginated APIs, soft deletion, role permissions | Acceptance steps 2 and 3; management/product tests |
| Create orders and validate stock | Server-owned prices, decimal amounts, deterministic row locks, stock ledger | Acceptance steps 4 and 5; concurrent order tests |
| Manager approval above a defined amount | Runtime threshold; pending approval; approve/reject endpoints; self-approval refused | Acceptance steps 6, 7 and 9; order/permission tests |
| Manager email and decision email to the creator | Transactional MySQL outbox, independent worker, backoff, dead-letter queue and admin retry | Acceptance steps 6, 8 and 9; worker tests |
| Approval updates inventory and completes the order | Stock is rechecked and deducted in the same transaction as approval/history/audit/outbox | Acceptance step 7; rollback and oversell tests |
| Maintain inventory | Restock/adjustment operations, append-only movement records | Acceptance step 10; inventory tests |
| Dashboard | Sales, orders, approval and inventory summaries | Acceptance step 11; dashboard tests |
| Authentication, validation and error handling | JWT + rotating sessions, second factor, schema validation, consistent errors and request IDs | Acceptance steps 1 and 14; auth/security/contract tests |

## Engineering checklist assessment

"Implemented" describes repository code and configuration. "Deployment action" needs a configured
service or an operational process. It does not imply a cloud service or compliance certification
has been provisioned.

| Area | Implemented in this repository | Deployment action or scope decision |
|---|---|---|
| Architecture and domain boundaries | Modular monolith, frontend/API separation, versioned REST API, independent worker; context/container/flow/trust diagrams and ADRs | Single company, one configured deployment; no claim of tenant isolation |
| Scaling and shared state | Stateless API replicas; MySQL sessions/outbox; Valkey shared rate limits; MySQL locks for housekeeping | Compose is one host. Managed HA databases, multi-host load balancing and replicas need platform setup |
| Frontend build and delivery | TypeScript strict, ESLint, Prettier, npm lockfile, lazy routes, gzip bundle budgets, self-hosted font, source maps disabled in production | Chromium checked locally; CI also configured for Firefox/WebKit acceptance |
| Frontend resilience | Error boundary, query error/retry states, timeouts, cancellation, offline banner, protected routes, session expiry and cross-tab sign-out | Device/network testing remains part of each release |
| Frontend accessibility | Keyboard navigation, labeled forms/dialogs, focus handling, responsive layouts; repeatable axe checks at phone/desktop widths | Automated checks supplement manual keyboard and screen-reader review |
| Backend and API design | Pydantic validation, SQLAlchemy transactions, Alembic, pagination, pools/timeouts, uniform errors, correlation IDs, API contract tests | Compatibility changes follow the documented API lifecycle |
| Authentication | Argon2id with bcrypt upgrade, password reset, one-time codes, optional TOTP/recovery codes, device sessions, refresh rotation/reuse detection, idle/absolute expiry | Development codes remain in terminal/logs. Production Compose defaults to email; protect any explicitly configured log delivery |
| Authorization | Three roles mapped to explicit permissions; ownership rules; deactivation and permission changes effective immediately; audited user changes | SSO/OIDC/SAML/SCIM and organization-specific ABAC are integration projects, outside the assignment |
| Browser and session security | HttpOnly/Secure/SameSite cookies, cookie-endpoint CSRF check, CSP, frame protection, nosniff, referrer/permissions headers; HTTPS/HSTS edge | Configure a real public hostname and valid certificate before public launch |
| API abuse and data integrity | User/IP/account limits, body/content-type limits, parameterized queries, mass-assignment protection, idempotent order creation | WAF/CDN rules and an external penetration test require a deployment |
| Database | MySQL TLS, separate application/schema/backup users, constraints/indexes, stock row locks, query/lock timeouts, slow-query log, binlogs | Disk encryption, HA/PITR, off-site binlog shipping and managed replicas require host/cloud configuration |
| Secrets and cryptography | Environment/secret-file configuration, weak-secret rejection, JWT key rotation, encrypted TOTP/outbox secrets, authenticated encrypted backups | Secret-manager/KMS integration, rotation ownership and encrypted host volumes are operational decisions |
| Containers and network | Multi-stage builds, non-root app/web users, read-only filesystems, dropped capabilities, no-new-privileges, resource limits, health checks, private data networks | Use scanned digest-pinned release images; keep Docker/host access restricted |
| Background work and integrations | Durable outbox, claims with locking, retries/backoff, dead-letter inspection/retry, graceful worker shutdown, scheduled cleanup | SMTP remains an external integration; delivery is at least once because SMTP offers no distributed transaction |
| Storage and uploads | Business data resides in MySQL; no user upload endpoint | S3/MinIO and upload malware scanning are unnecessary until file attachments become a requirement |
| Delivery and supply chain | CI lint/types/tests/security scans/builds/E2E, dependency updates, CodeQL, Gitleaks, Semgrep, Trivy, SBOM and signed image release workflow | Connect GitHub environments, registry, host credentials and branch protection; hosted CI has to run after upload |
| Deployment safety | One-shot DB account/migration stages, health-gated deployment, smoke test and finite image rollback; expand/contract guidance | Rollback across migrations requires compatible images or a forward fix. Multi-host rolling, blue/green, canaries, Terraform and Kubernetes are platform choices |
| Observability | JSON logs/redaction, request IDs, audit trail, metrics, optional Prometheus/Grafana overlay, browser errors/web vitals, SLO/alert rules | Connect alert routing and log retention. Vendor tracing/APM/SIEM integrations are optional |
| Recovery and operations | Backup/restore scripts, restore checks, retention, runbook, incident process, recovery objectives and load-test harness | Off-site copies and full recovery drills are required to validate the stated recovery targets |
| Audit and governance | Security/business audit events, database triggers, export, threat model, engineering/release/data-classification documents, CODEOWNERS | SOC 2/ISO 27001/GDPR readiness needs organization processes, evidence and legal review; this repo is not certification |
| Email and DNS | Escaped templates, durable retries, TLS-capable SMTP and security notifications | Real mail credentials, SPF/DKIM/DMARC and DNS ownership must be supplied |
| Testing | MySQL integration/concurrency/security/migration/API tests, Vitest/RTL, PDF acceptance, recovery/permission E2E, responsive/a11y suite, k6 | Latest executed checks and limitations are recorded in [qa/verification.md](qa/verification.md) |

## Corrections from the current review

The review targets correctness in existing features as well as missing infrastructure. Regression
coverage is included for idle timeout, concurrent idempotent retries, expired worker claims,
outstanding login challenges after password changes, query failure visibility, keyboard table
navigation, deployment rollback and smoke-test input handling.

## Launch prerequisites

1. Configure `production.env` from `production.env.example`, including independently generated
   keys/passwords, the HTTPS public URL and real SMTP settings. Use `OTP_DELIVERY=email` for
   ordinary production users. Keep log delivery for development or an explicit controlled test.
2. Run migrations with the schema account, create the first admin, and confirm secure login,
   manager/decision emails, approval transactions and readiness through the public HTTPS path.
3. Configure off-site encrypted backup copies, retain encryption keys separately, and complete a
   restore drill on a separate database/host. RPO/RTO figures are targets until measured.
4. Enable the monitoring stack or platform equivalent, connect alerts, and assign an owner for
   application, infrastructure, incident response and security reviews.
5. Run hosted CI and deployment acceptance against the intended environment. Configure repository
   protection and release approval, review administrative access, and publish the data notice.

See [architecture/README.md](architecture/README.md), [operations/runbook.md](operations/runbook.md),
[operations/slo.md](operations/slo.md) and [security/threat-model.md](security/threat-model.md).
