# Verification record — 2026-10-07

The latest candidate review, including the repeated-restock correction, is recorded in
[submission-readiness.md](submission-readiness.md). The sections below retain earlier evidence.

This record covers the local hardening review against the supplied Web Developer Assignment
and the existing Sales & Inventory Management System. It records executed checks, separately
from workflows and operational processes that still need to run in the intended environment.

## Environments

- Development Docker stack: React/nginx, FastAPI, worker, MySQL, Valkey and Mailpit.
  UI at `http://localhost:3000`; this workstation uses `BACKEND_PORT=8001` because port 8000
  belongs to another application. Development login codes continue to appear in backend logs.
- Separate production-configuration QA stack: Caddy HTTPS, production nginx/API/worker settings,
  private MySQL with required TLS, two API replicas, production email OTP, and monitoring overlay.
  Tests used a local CA with certificate verification disabled by the test clients. Mailpit was
  the controlled SMTP sink; this local test explicitly disabled SMTP TLS. These are test settings,
  not public-launch settings. Production defaults require secure session cookies.
- Chromium browser tests exercised the real API, database and mail worker with CSP enforced.
  Each acceptance run created its own users and business records.

## Executed results

| Check | Result |
|---|---|
| Backend unit, MySQL integration, concurrency, security, migrations and API contracts | 258 passed; application line coverage 95.12% (90% gate) |
| Backend Ruff lint and format; mypy | Passed; 101 Python files formatted, 80 sources type checked |
| Alembic model/schema comparison | Passed; no migration drift |
| Frontend Vitest/React Testing Library | 48 passed across 10 files |
| Frontend TypeScript, ESLint, Prettier and production build | Passed |
| Frontend gzip bundle budgets | Passed: approximately 32.0 KiB entry, 114 KiB largest chunk, 418.9 KiB total JavaScript |
| Development browser suite | 24 passed: 14 PDF acceptance, 4 recovery/permission scenarios, 6 viewport cases; final mobile-label change also passed both accessibility viewport reruns |
| Production browser suite | 24 passed on the rebuilt app through HTTPS, including email OTP and all six viewport cases |
| HTTPS release smoke test | 9 passed: health/readiness, headers, request IDs, docs protection, anonymous access and HTTP redirect |
| Deployment script regression suite | 6 passed, including startup failure, rollback and bounded timeout handling |
| Infrastructure and workflow validation | Development, production and monitoring Compose configurations; actionlint, ShellCheck, nginx/Caddy validation and 11 Prometheus alert rule tests passed |
| Monitoring runtime | Prometheus, both API scrape targets and worker were up; Grafana database health passed through its loopback port |
| Encrypted backup and scratch restore | Passed twice with populated business data; [latest check](backup-restore.json) restored 20 tables, 2 audit triggers, 30 users, 3 orders and 89 audit entries in 30 seconds |
| Backup corruption and tamper tests | Passed |
| Dependency/security checks | pip-audit and npm audit reported no known vulnerabilities; Bandit found no issues; Gitleaks found no secrets in the source snapshot |
| Container vulnerability scan | Backend and frontend passed Trivy's fixable HIGH/CRITICAL vulnerability filter |

Frontend unit-test line coverage was 21.99% across the whole application (statement coverage
21.86%). The browser suite adds page/workflow checks; it does not increase or replace that
unit-test coverage measurement.

## Browser coverage and corrections

The responsive suite checks 18 page/dialog states at six widths: 360, 390, 768, 1024, 1440 and
1920 pixels, giving 108 layout checks per environment. States include login, sign-up, password
reset, the OTP challenge, all 11 authenticated pages, order detail, product creation and
authenticator setup. It also verifies the mobile drawer closes after navigation.

Axe runs on all 18 states at 390px and 1440px: 36 scans per environment, using WCAG 2 A/AA,
WCAG 2.1 A/AA and best-practice rules. Checks assert the intended route and heading, no
horizontal document overflow, and no unexpected JavaScript or console errors. Automated
scans found no violations in either environment. They supplement manual keyboard and
assistive-technology review.

The final production pass caught a visible-name mismatch on the mobile account button for
the test administrator's initials. Its accessible label now includes the visible initials.
Other regressions fixed and covered include idle logout, concurrent refresh and logout,
offline logout persistence, password-change invalidation of old OTP challenges, final-stock
idempotent retries, expired outbox claims, last-admin deactivation and explicit query retries.

## Load test

The k6 API capacity run used 30 browsing virtual users plus two order attempts per second,
with 20 user tokens and two API replicas limited to one CPU/512 MB each. It sent 10,177 requests
at 59.21 requests/second, with 100% checks passing and no failed requests or server errors.
Median latency was 18.02 ms, p95 79.88 ms, p99 144.69 ms; order creation p95 was 200.55 ms.
All configured latency, server-error and success thresholds passed.

This run addressed the API on its private Docker network. The isolated test disabled the
shared per-IP API budget because all virtual users originated from one load generator;
per-user limits stayed enabled. Production defaults were not changed. A preceding run through
nginx exceeded its 30 requests/second per-IP limit: 52.4% of requests received 429 and the
success/latency checks failed, with no server errors. That result demonstrates throttling and
is not a passing capacity result for the public HTTP path.

Raw summaries: [API capacity](load-api-capacity.json), [shared-IP proxy throttling](load-proxy-limits.json).
See [performance notes](../operations/performance.md) for workload and interpretation. These
local, short runs on a small data set do not establish cloud capacity, failover or sustained SLOs.

## Independent re-verification (second pass, 2026-10-07)

Every check was re-run from a rebuilt stack, without relying on the results above.

| Check | Result |
|---|---|
| Backend: Ruff, format, mypy, Alembic drift, pytest with coverage | All passed; **258 tests**, coverage 95.12%; 87 s run |
| Backend dependency and code scans | pip-audit (runtime and dev): no known vulnerabilities; Bandit: 0 issues |
| Frontend: TypeScript, ESLint, Prettier, Vitest, build, bundle budgets, npm audit | All passed; **48 tests**; 32.0 / 114.0 / 418.9 KB gzip; 0 vulnerabilities |
| Browser suite, demo stack (14 acceptance + 4 enterprise + 6 responsive/axe) | **Chromium 24/24, Firefox 24/24, WebKit 24/24** |
| Browser suite, production stack (HTTPS edge, 2 API replicas, email codes) | **Chromium 24/24** |
| Release smoke test (production stack) | 9/9 |
| Semgrep (p/default, OWASP Top 10, Python, TypeScript, Dockerfile; 564 rules) | 0 findings |
| Gitleaks (all 282 files that would be committed) | No leaks |
| Trivy images (backend, frontend) | 0 fixable critical/high/medium vulnerabilities |
| OWASP ZAP baseline (demo stack) | 0 failures, 63 passed, 1 accepted warning (CSP `style-src 'unsafe-inline'`, required by MUI) |
| actionlint, Compose configurations (demo, production, monitoring) | Valid |
| Production backup + scratch restore check | OK: 20 tables, 2 audit triggers, 26 users, 306 orders, 387 audit entries |

Fixed in this pass:

- **Slow local test runs.** The Compose stack now publishes ports on 127.0.0.1 only; on Windows
  `localhost` resolves to `::1` first, and each refused IPv6 attempt cost about 2 s per new
  database connection (the backend suite took 10.3 minutes). Local and test database URLs now
  use `127.0.0.1` (87 s), and the e2e suite's Python clients use IPv4 loopback for plain-HTTP
  targets. Containers were unaffected: they reach MySQL as `mysql:3306`.
- **WebKit accessibility test race.** axe measured the product dialog while it was still fading in
  (opacity 0.77-0.94), producing intermittent colour-contrast findings; the settled dialog has
  none. The check now waits for dialogs to be fully opaque before scanning.
- `production.env.example` listed `GRAFANA_ADMIN_PASSWORD` twice.
- `loadtest/` had no lint configuration, so its result depended on the working directory.

## Running without Docker (2026-10-07)

The API (uvicorn), the worker and the frontend ran directly on Windows 11 (Python 3.11.9,
Node.js 24.17), following the README's [Run without Docker](../../README.md#run-without-docker)
steps. The database was MySQL 8.4.11 with the server's default settings (binary logging on,
`log_bin_trust_function_creators` off, `utf8mb4_0900_ai_ci`), prepared only with
`backend/scripts/setup_local_mysql.sql`. No MySQL is installed on this workstation, so that server
ran in a throwaway container with no custom options; the development stack's Mailpit received
the emails. Nothing else ran in containers.

| Check | Result |
|---|---|
| App account creating a trigger on the default server | Refused with error 1419 until the setup script's `SET PERSIST log_bin_trust_function_creators` ran; then allowed |
| `alembic upgrade head`, `python -m scripts.seed`, `alembic check` | Passed; no drift |
| Browser suite against `npm run dev` (Vite dev server) | 24/24 |
| Browser suite against `npm run build` + `npm run preview` | 24/24 |
| Backend tests against the same server | 258 passed; coverage 95.12% |
| Fresh Windows virtual environment, `pip install -r requirements.txt` then `requirements-dev.txt` | Previous lockfile failed (`uvloop does not support Windows`); the new one installs with hash checking, and the backend suite passes (258) |
| Docker stack rebuilt with these changes | Browser suite 24/24; worker metrics reachable over the Docker network; worker health check passes |

Fixed by this check:

- **A fresh MySQL install would fail at the first migration.** The README's local setup still ran
  MySQL in Docker, whose configuration enables `log_bin_trust_function_creators`. Added
  `backend/scripts/setup_local_mysql.sql` (databases, account, that setting) and a complete
  Run without Docker section, including the worker and the production frontend build.
- **`pip install -r requirements.txt` would fail on Windows.** The hash-locked lockfile was
  generated for Linux only and required `uvloop`, which does not support Windows. It is now a
  universal lock (`uv pip compile --universal`): same versions and hashes, with platform markers.
- **The worker's metrics server listened on every network interface.** Outside a container that
  exposes it to the local network and triggers a Windows Firewall prompt. It now listens on
  127.0.0.1 unless `WORKER_METRICS_HOST` is set; Compose sets `0.0.0.0` so Prometheus can still
  scrape it over the private Docker network.
- **The end-to-end suite assumed IPv4.** Vite's dev server listens on `::1` only on Windows, so
  the suite now probes which loopback address answers. `E2E_OTP_LOG_FILE` reads sign-in codes
  from a saved API log (UTF-8 or the UTF-16 that Windows PowerShell 5.1 writes).
- The worker wrote its health-check heartbeat to `/tmp`, which on Windows means `C:\tmp`. It now
  uses the system's temporary folder: still `/tmp` in the container, where the check reads it.
- The SMTP host and Vite proxy defaults use 127.0.0.1, avoiding a two-second IPv6 attempt per
  connection on Windows when the target listens on IPv4 only.

## Remaining deployment verification

Hosted GitHub CI, CodeQL and the release workflow are configured but can only run after the
repository is uploaded. Semgrep, ZAP and the Firefox/WebKit browser runs were executed locally
in the second pass above. No public site, cloud HA service, SSO integration or compliance
certification was provisioned by this work.

Public launch still needs a real hostname/certificate, independently generated production
secrets, real SMTP with appropriate TLS and sender DNS, off-site backups with a separate-host
restore drill, alert routing and operational owners. Recovery and availability figures are
targets until measured in that environment. See [enterprise readiness](../enterprise-readiness.md).
