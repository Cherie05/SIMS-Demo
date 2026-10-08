# Assignment submission review - 7 October 2026

This is a fresh review of the current source and running application, including the supplied
Sales & Inventory Management assignment. Results below distinguish application verification
from the remaining GitHub, video and email submission steps.

On 8 October, a [Windows command guide](../../RUN_COMMANDS.md) was added and the source ZIP
was refreshed to include it. This documentation update does not change the application test results below.
GitHub preparation on the same day also corrected the README's logout description to match the
existing active-session check and prepared the local `main` branch for upload.

## Issue found and corrected

The stock adjustment dialog retained its idempotency key after a successful restock. Reopening
the same mounted dialog and submitting an identical delivery could replay the previous result
instead of increasing stock again. The key now clears only after confirmed success. An uncertain
failure retains the key so retrying that request remains safe.

Two frontend regression tests verify separate identical deliveries and retries after a lost
response. The repeated-delivery test failed before the fix and passes afterward. Browser
acceptance step 10 now submits two identical five-unit restocks without reloading the page and
checks both stock movements: 7 -> 12 -> 17 units.

The README also now describes the current outbox worker, delivery retries, password hashing and
required Node versions accurately.

## Fresh verification

| Area | Executed result |
|---|---|
| Backend | 258 tests passed against MySQL, 95.12% application coverage |
| Backend quality | Ruff lint/format, mypy, dependency consistency and Alembic schema comparison passed |
| Windows installation | A clean virtual environment installed the hash-locked runtime requirements; API and worker imports passed; uvloop correctly skipped |
| Backend security | pip-audit: no known runtime dependency vulnerabilities; Bandit: no findings or scan errors |
| Frontend | 50 tests passed across 11 files, including the two new stock regressions |
| Frontend quality | TypeScript, ESLint, Prettier, production build and bundle budgets passed |
| Frontend dependencies | npm audit: zero known vulnerabilities |
| Docker browser tests | Chromium: 24/24 passed; Firefox: 24/24 passed on the rebuilt app |
| Windows application browser tests | Chromium: 24/24 passed in one run; WebKit: all 18 workflow tests and all 6 viewport cases passed across separate runs; API and worker ran directly on Windows |
| Responsive/accessibility | Six widths passed in Chromium, Firefox and WebKit; 108 layout checks and 36 axe scans per matrix, without document overflow or axe violations |
| Live-source comparison | All 80 backend Python files in the demo container exactly match current host source |
| Repository review | Environment files, logs, dependencies, caches, backups and temporary data excluded; source secret scan passed |
| Workflow/docs | actionlint passed; local links checked; reviewer setup instructions provided |

Browser runs include product/customer management, stock validation, immediate and manager-approved
orders, rejection, email notifications, inventory ledger, dashboard, login/sign-up, password
reset, offline logout, query recovery and role enforcement. Real MySQL transactions and Mailpit
email delivery are used; browser tests keep the application's CSP enabled where configured.

The responsive suite covers 18 pages/dialog states at 360, 390, 768, 1024, 1440 and 1920 pixels:
108 layout checks per run. At 390 and 1440 pixels it performs 36 axe scans using WCAG 2/2.1
A/AA and best-practice rules. It checks intended routes/headings, mobile navigation, horizontal
document overflow and unexpected browser errors. Screenshots are also reviewed for visible
layout issues. Automated checks cannot establish that every possible interaction is bug-free.

The initial Docker WebKit run passed all 14 assignment acceptance steps, then reached the
password-reset IP budget during the recovery scenario. Repeated suites had accumulated the
default five-per-hour budget on the same address. The UI correctly displayed the 429 recovery
message. The completed WebKit verification used a fresh isolated Windows application process
and database, preserving the same normal limits and leaving the demo's shared counters intact.

WebKit diagnostics also distinguished expected offline request failures from real JavaScript
exceptions. Playwright's WebKit engine can report those network failures as `pageerror` events.
The offline scenario now observes actual window `error` and `unhandledrejection` events, without
preventing either event. Network diagnostics showed cancelled/offline requests and no such DOM
exception events. Chromium and Firefox passed the revised exception-tracking check as well.
Healthy-flow console checks remain strict. The rejection workflow uses the real Approvals
navigation link, allowing normal route cleanup instead of tearing down an in-flight document.
See the [Playwright handler](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/server/webkit/wkPage.ts)
and [WebKit network-error logging](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/loader/ThreadableLoader.cpp).

One longer WebKit run passed the 18 workflow tests and the 360/390px cases, then timed out at
the 768px sign-in step. The UI showed no validation or API error; no matching login request was
recorded. A diagnostic rerun of the remaining 768/1024/1440/1920px cases passed all four, with
no unexpected console or exception events. Thus all cases passed across separate runs; this
review does not claim an uninterrupted 24/24 WebKit run. Hosted CI should still run on upload.

The Windows runtime check starts the API, worker and built frontend directly on Windows in an
isolated QA database. MySQL itself and the Mailpit inbox remain container services because no
native MySQL installation is available on this workstation. This verifies the application
outside containers; it does not claim to verify installing a native Windows MySQL server.

## Assignment coverage

| PDF requirement | Current implementation and acceptance coverage |
|---|---|
| React, FastAPI, Python, MySQL | Required stack retained |
| Manage products/customers | CRUD, forms, validation and role permissions; steps 2/3 |
| Create orders and validate stock | Server-owned prices, stock locks and rollback; steps 4/5 |
| Manager approval above threshold | Pending approval, approve/reject and ownership checks; steps 6/7/9 |
| Manager and decision emails | Durable transactional outbox plus SMTP worker; steps 6/8/9 |
| Deduct inventory and complete approved order | One transaction plus append-only stock history; step 7 |
| Maintain inventory | Restock/adjustment ledger, including repeated deliveries; step 10 |
| Sales/order/approval/inventory dashboard | API summaries and UI panels; step 11 |
| Authentication, validation, transaction/error handling | Auth/security/integration tests and acceptance steps 1/4/9/14 |

## Public repository and submission

The source is suitable for a public assignment repository when uploaded with the current
`.gitignore`. Demo credentials and synthetic example.com records are deliberately documented;
actual environment files, private keys, session tokens and generated data must stay excluded.
The prepared source-only ZIP contains the 286 files Git would include, with archive integrity
checked. Environment files, dependencies, logs, temporary data and build output are excluded.
The 7 October Gitleaks scan of the previous 285-file archive found no secrets. On 8 October,
the native Windows Gitleaks 8.30.1 scanner checked all 286 source candidates and found no leaks.
Its download was verified against the checksums from the
[official release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1).
Environment files and personal recording notes were excluded from the scan and upload candidates.
The refreshed 286-file ZIP passed archive integrity checks; all 17 PowerShell command blocks
in the Windows run guide passed syntax checks. Only documentation and Git preparation changed;
the application test results above were not rerun during this preparation.

The initial submission commit was uploaded to the public
[Cherie05/SIMS-Demo repository](https://github.com/Cherie05/SIMS-Demo) on 8 October.
The first hosted run passed backend, frontend, security scans, both container scans and CodeQL;
ShellCheck 0.9.0 failed on indirect smoke-test callbacks and two backup conditionals, preventing
the end-to-end job from starting. The callbacks now have scoped ShellCheck annotations and
the conditionals use explicit guards. The same Ubuntu 24.04 ShellCheck version, six deployment
tests and the encrypted-backup tests passed locally after this correction.
Dependency graph was also enabled to support pull-request dependency review.
See the [live CI results](https://github.com/Cherie05/SIMS-Demo/actions/workflows/ci.yml) for the
current commit and [repository setup](../github-repository-setup.md) for the applied protection.
The application's code review is separate from completing these submission steps:

1. Verify the final `main` commit passes hosted CI and can be cloned publicly.
2. Use the final commit's source-only ZIP and the clone's quick-start instructions.
3. Provide the complete source ZIP and a Loom walkthrough of the order/email/approval/stock flow.
4. Reply to HR with the repository, ZIP and Loom link before **8 October 2026, 4:00 PM**, as
   stated in the supplied email. This review has not sent HR messages.

A hosted public website is not listed as a required submission item. If one is supplied,
configure real HTTPS/domain settings, production secrets and real SMTP first; see
[enterprise readiness](../enterprise-readiness.md). Native MySQL installation on this PC
remains unverified in this review. Earlier deployment/security/performance checks are recorded
in [the verification history](verification.md), separately from these freshly executed checks.
