# Sales & Inventory Management System (SIMS)

A web application for managing products, customers, sales orders and inventory, with a **manager approval workflow** for high-value orders and **email notifications** at each step.

**Stack:** React 18 + TypeScript (Vite, MUI) · FastAPI · Python 3.11 · SQLAlchemy 2 · MySQL 8 · Alembic · JWT

![Dashboard](docs/screenshots/dashboard.png)

---

## Contents

- [Quick start (Docker)](#quick-start-docker)
- [Demo accounts](#demo-accounts)
- [Requirements coverage](#requirements-coverage)
- [Features](#features)
- [How the approval workflow works](#how-the-approval-workflow-works)
- [Architecture](#architecture)
- [Database design](#database-design)
- [API overview](#api-overview)
- [Key design decisions](#key-design-decisions)
- [Security](#security)
- [Production deployment](#production-deployment)
- [Run without Docker](#run-without-docker)
- [Tests and code quality](#tests-and-code-quality)
- [Configuration](#configuration)
- [Project structure](#project-structure)

---

## Quick start (Docker)

Requires Docker Desktop. No Docker? See [Run without Docker](#run-without-docker).

For Windows PowerShell commands for both setups, see [RUN_COMMANDS.md](RUN_COMMANDS.md).

```bash
docker compose up --build
```

| What | URL |
|---|---|
| Web app | http://localhost:3000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Email inbox (Mailpit) | http://localhost:8025 |

This is the **demo stack**. On first start the backend applies the database migrations and loads demo data: 4 users, 8 customers, 12 products and two months of order history. (For a real deployment, see [Production deployment](#production-deployment).)

Every email the system sends is captured by **Mailpit**, so you can watch the approval emails arrive without configuring a real mail server.

**Signing in takes two steps:** a password, then a 6-digit one-time code. In this setup the code is written to the backend log. Keep this running in a second terminal while you test:

```bash
docker compose logs -f backend          # look for:  OTP for manager@example.com (sign-in): 482913
```

When running the backend directly with `uvicorn`, the code appears in that terminal. To email codes instead, set `OTP_DELIVERY=email`.

> If a port is already in use, override it, e.g. `BACKEND_PORT=8001 FRONTEND_PORT=3001 MYSQL_PORT=3307 docker compose up`.

## Demo accounts

| Role | Email | Password | Can do |
|---|---|---|---|
| Admin | admin@example.com | Admin@123 | Everything, plus users and the approval threshold |
| Manager | manager@example.com | Manager@123 | Approve or reject orders, manage products and stock |
| Sales | sales@example.com | Sales@123 | Create orders and customers, see their own orders |
| Sales | sales2@example.com | Sales@123 | Same as above (useful for testing visibility rules) |

The sign-in page has one-click buttons that fill these in (outside production). New accounts can also be created at **Create an account**: they confirm their email with a code and start with the Sales role.

**Suggested walkthrough:**
1. Sign in as **Sales** (enter the code from the backend log) and create an order over ₹50,000. The order form warns that approval is required.
2. Open Mailpit to see the approval request email sent to the manager.
3. Sign in as **Manager**, open **Approvals**, and approve or reject the order.
4. Check Mailpit again for the decision email, then look at the order's status timeline and the **Stock Ledger**.

---

## Requirements coverage

Each requirement in the brief, where it is implemented, and the [acceptance test](e2e/test_acceptance.py) step that proves it end to end, in a real browser with real email.

| Requirement (from the brief) | Implementation | Proven by |
|---|---|---|
| React.js, FastAPI, Python, MySQL | `frontend/` (React 18 + TypeScript), `backend/` (FastAPI, Python 3.11, SQLAlchemy), MySQL 8 | the whole stack runs in `docker compose` or [without Docker](#run-without-docker) |
| Users manage products | Products page; `POST/PATCH/DELETE /products` | step 2 |
| Users manage customers | Customers page; `POST/PATCH/DELETE /customers` | step 3 |
| Create sales orders | New Order page; `POST /orders` | steps 5, 6 |
| Validate the order and stock on creation | Zod in the form, Pydantic at the API, stock checked under row locks | step 4 |
| Orders above a defined amount need manager approval before confirmation | Admin-editable threshold; `PENDING_APPROVAL` state; `order_service.create_order` | steps 5, 6 |
| Email the manager when approval is required | `notification_service.enqueue_approval_requests` (durable outbox, SMTP worker after commit) | step 6 |
| Manager approves or rejects | Approvals page and order page; `POST /orders/{id}/approve` and `/reject` | steps 7, 9 |
| User notified of the decision by email | `notification_service.enqueue_decision` | steps 8, 9 |
| On approval, update inventory and complete the order | `order_service.approve_order`: stock re-checked, deducted, ledger written, `COMPLETED`, all in one transaction | step 7 |
| Maintain inventory | Restocks and adjustments; stock ledger | step 10 |
| Dashboard with sales, order, approval and inventory information | Dashboard page; `GET /dashboard/*` | step 11 |
| Authentication | Two-step JWT sign-in (password + one-time code), sign-up with email verification, rotating refresh sessions, roles checked on every endpoint and route | steps 1, 14 |
| Validation, error handling, transactions | One error shape, field-level messages, rollbacks, `409`/`422`/`503` | steps 4, 9, plus the backend suite |

---

## Features

| Area | What's included |
|---|---|
| **Authentication** | Verified sign-up; two-step sign-in using codes or an authenticator app; recovery codes and password reset; Argon2id passwords with bcrypt upgrade; JWT access tokens and rotating HttpOnly refresh sessions; device management and idle/absolute expiry; Admin / Manager / Sales permissions |
| **User experience** | Modern dashboard with a period picker, change-versus-previous-period indicators and sparklines; keyboard shortcuts (press `?`); works from 360px phones to wide screens; WCAG 2.1 AA checked with axe-core |
| **Products** | Create, edit and soft-delete products; search and low-stock filter; stock changes only through restocks and adjustments, all recorded in a ledger |
| **Customers** | Create, edit and soft-delete customers, with search; customers can be added from inside the order form |
| **Sales orders** | Multi-line orders with live totals and tax; stock validated on the client, on the server, and again under row locks when stock is deducted |
| **Approval workflow** | Orders above a configurable threshold wait for a manager, who approves or rejects them (a reason is required to reject). Managers cannot approve their own orders. Creators can cancel orders that are still pending. |
| **Email** | HTML approval/decision emails through a transactional outbox and independent worker, retry with backoff, dead-letter inspection and retry; delivery status on the order page |
| **Inventory** | Append-only stock ledger (opening stock, sales, restocks, adjustments) with the balance after every movement |
| **Dashboard** | Revenue KPIs, pending approvals and their total value, 30-day revenue trend (chart or table view), orders by status, top products, low-stock list |
| **Admin** | Runtime threshold/tax settings, user/role administration, audit search/export, system health, worker jobs and feature flags |

| New order | Order detail |
|---|---|
| ![New order](docs/screenshots/new-order.png) | ![Order detail](docs/screenshots/order-detail.png) |

| Approvals | Approval-request email |
|---|---|
| ![Approvals](docs/screenshots/approvals.png) | ![Email](docs/screenshots/email-approval-request.png) |

| Two-step sign-in (code from the server log) |
|---|
| ![Sign-in code](docs/screenshots/sign-in-code.png) |

---

## How the approval workflow works

```mermaid
stateDiagram-v2
    [*] --> APPROVED: total ≤ threshold<br/>(auto-approved)
    [*] --> PENDING_APPROVAL: total > threshold<br/>email → managers
    PENDING_APPROVAL --> APPROVED: manager approves
    PENDING_APPROVAL --> REJECTED: manager rejects (reason required)<br/>email → creator
    PENDING_APPROVAL --> CANCELLED: creator or manager cancels
    APPROVED --> COMPLETED: stock deducted in the same transaction<br/>email → creator (if approval was needed)
    COMPLETED --> [*]
    REJECTED --> [*]
    CANCELLED --> [*]
```

1. **Create.** The server checks that the customer and products are active and that there is enough stock for every line. It returns `409 INSUFFICIENT_STOCK` with a per-line breakdown when there isn't.
2. **Below or equal to the threshold.** In a single transaction the products are locked, stock is deducted, ledger rows are written, and the order is set to `COMPLETED`.
3. **Above the threshold.** The order and an approval record are saved as `PENDING_APPROVAL`, and stock is not touched. After the commit, every active manager is emailed (admins are used if there are no managers).
4. **Approve.** The order row and the product rows are locked and **stock is re-validated**, because it may have changed since the order was placed. Then stock is deducted and the order is completed. If stock has run out, the whole transaction rolls back, the order stays pending, and the manager sees a clear message telling them to restock or reject.
5. **Reject or cancel.** The status changes and no stock is touched.
6. **Notify.** The creator is emailed the decision, including the manager's comment.

Every transition is written to `order_status_history`, which the UI shows as a timeline.

---

## Architecture

```mermaid
flowchart LR
    subgraph Browser
        UI[React SPA<br/>MUI · React Query · RHF + Zod]
    end
    subgraph Backend[FastAPI]
        R[Routers<br/>validation · auth · RBAC] --> S[Services<br/>business rules · transactions]
        S --> M[SQLAlchemy models]
    end
    UI -- "/api/v1 (JWT)" --> R
    M --> DB[(MySQL 8)]
    W[Independent worker<br/>email notifications] -- claims committed outbox jobs --> DB
    W --> SMTP[SMTP<br/>Mailpit in dev]
```

- **Routers validate requests and enforce access.** Business services perform transactional changes and enqueue notifications; platform routes also query status and administration data.
- **Services hold the business logic.** Each state change runs as one unit of work: commit on success, roll back on any error.
- **Emails use a durable transactional outbox.** Notification jobs commit with the order, and an independent worker sends them afterward, so an SMTP outage does not roll back an order. Workflow notifications retry with backoff up to `JOB_MAX_ATTEMPTS` (6 by default); one-time-code jobs allow 3 attempts before expiry. Delivery outcomes are recorded in `email_logs`, and failed jobs can be inspected and retried by an administrator. Delivery is at least once, so a worker failure after sending can produce a duplicate email.
- **A database outage is reported, not hidden.** The API answers `503` with `Retry-After`, the health check fails so a load balancer can react, and the backend recovers by itself when MySQL returns.
- **Errors share one JSON shape**, which the frontend maps onto form fields and messages:
  ```json
  { "error": { "code": "INSUFFICIENT_STOCK", "message": "Insufficient stock for: CAM-HD (requested 50, available 7)",
               "details": [{ "product_id": 11, "sku": "CAM-HD", "requested": 50, "available": 7 }] } }
  ```

---

## Database design

```mermaid
erDiagram
    users ||--o{ sales_orders : creates
    customers ||--o{ sales_orders : places
    sales_orders ||--|{ sales_order_items : contains
    products ||--o{ sales_order_items : "sold as"
    sales_orders ||--o| order_approvals : "may require"
    users ||--o{ order_approvals : decides
    sales_orders ||--|{ order_status_history : "audited by"
    products ||--o{ inventory_transactions : "stock moves"
    sales_orders ||--o{ inventory_transactions : causes
    sales_orders ||--o{ email_logs : notifies

    products {
        int id PK
        varchar sku UK
        decimal unit_price "CHECK >= 0"
        int stock_qty "CHECK >= 0"
        int reorder_level
        bool is_active
    }
    sales_orders {
        int id PK
        varchar order_number UK
        enum status
        decimal subtotal
        decimal tax_amount
        decimal total_amount
        bool requires_approval
    }
    sales_order_items {
        int order_id FK
        int product_id FK
        int quantity "CHECK > 0"
        decimal unit_price "price snapshot"
    }
    order_approvals {
        int order_id FK,UK
        enum status
        decimal threshold_amount "threshold at request time"
        int decided_by_id FK
        text comment
    }
    inventory_transactions {
        int product_id FK
        enum txn_type "OPENING/SALE/RESTOCK/ADJUSTMENT"
        int qty_change
        int balance_after
    }
```

Also: `order_status_history` (audit trail), `email_logs` (delivery log), `app_settings` (runtime-editable threshold and tax rate), `users`, `customers`.

- **Money is `DECIMAL`**, never float. Python uses `Decimal` with half-up rounding to 2 places.
- **Integrity is enforced by the database too:** `CHECK` constraints (stock and price never negative, quantity > 0), unique SKU, email and order number, a unique product per order, and foreign keys everywhere.
- **Line prices are snapshots**, so later price changes never rewrite historical orders.
- **Soft deletes** for products and customers, because orders reference them.
- **Indexes** on foreign keys, `status + created_at` (order lists and the dashboard) and `product_id + created_at` (the ledger).
- **Migrations are managed by Alembic** (`backend/alembic/versions`).

---

## API overview

All endpoints are under `/api/v1` and documented interactively at `/docs`.

| Method & path | Who | Purpose |
|---|---|---|
| `POST /auth/signup` · `POST /auth/login` | anyone | Create an account (Sales) / check the password; both answer with a one-time-code challenge |
| `POST /auth/otp/verify` · `POST /auth/otp/resend` | anyone with a challenge | Exchange the code for a session (access token + refresh cookie) / get a new code |
| `POST /auth/refresh` · `POST /auth/logout` | cookie + `X-Requested-With` header | Rotate the session / end it (revokes the refresh token) |
| `GET /auth/me` · `GET /auth/config` | signed in · anyone | Current profile / public sign-in settings |
| `GET/POST /users` · `PATCH /users/{id}` | Admin | Manage users and roles |
| `GET/POST /customers` · `GET/PATCH/DELETE /customers/{id}` | signed in (delete: Manager+) | Customers, with `search`, `is_active` and pagination |
| `GET /products` · `GET /products/{id}` | signed in | Products, with `search`, `is_active`, `low_stock` and pagination |
| `POST/PATCH/DELETE /products...` | Manager+ | Create, edit, deactivate |
| `POST /products/{id}/stock-adjustments` | Manager+ | Restock or adjust (writes to the ledger) |
| `GET /inventory/transactions` | signed in | Stock ledger |
| `POST /orders` · `GET /orders` · `GET /orders/{id}` | signed in (Sales see only their own) | Create, list (filter by status, search, date range), detail |
| `POST /orders/{id}/cancel` | creator or Manager+ | Cancel a pending order |
| `GET /approvals?status=` | Manager+ | Approval queue and decision history |
| `POST /orders/{id}/approve` · `POST /orders/{id}/reject` | Manager+ (not on their own orders) | Decide |
| `GET /dashboard/summary` · `/sales-trend` · `/top-products` | signed in | Dashboard data |
| `GET /settings` · `PUT /settings` | signed in · Admin | Approval threshold, tax rate |

Status codes: `400` business rule broken, `401` not authenticated, `403` not allowed, `404` not found, `409` conflict (stock, duplicates, already decided), `422` validation error, `429` too many failed sign-ins (with a `Retry-After` header), `503` database temporarily unavailable (also with `Retry-After`).

---

## Key design decisions

- **Concurrency safety.** Stock-changing paths use `SELECT … FOR UPDATE`. Products are always locked in ascending id order, so two transactions can't deadlock each other, and the order row is locked during approve and reject so two managers can't decide the same order. The test suite includes a real two-thread race, and exactly one order wins.
- **READ COMMITTED isolation** keeps plain reads fresh; the correctness-critical reads are locking reads.
- **Stock only changes through the ledger.** `stock_qty` can't be edited directly (the update schema rejects it), so the ledger always explains the current stock level.
- **Threshold history.** The threshold that applied is stored on each approval, so changing it later doesn't distort the history.
- **Separation of duties.** Managers can't approve or reject their own orders.
- **Validation in three layers:** Zod in the browser (fast feedback), Pydantic at the API (the authority), and constraints in MySQL (the last line of defence).
- **Information hiding.** Sales users only see their own orders, and login doesn't reveal whether an email exists: the response time is the same either way.

---

## Security

| Area | Measure |
|---|---|
| **Passwords** | Argon2id hashes; legacy bcrypt hashes upgrade at sign-in. Passwords are 8–128 characters with a letter and a number; common passwords and those containing the account's name or email identifier are rejected. |
| **Sign-in** | Two steps: password, then a 6-digit one-time code. Codes are random, valid for 5 minutes, single-use, locked after 5 wrong tries, resendable after 30 seconds (5 times at most), and stored only as a keyed hash. Sign-up needs the same code to verify the email; new accounts can only be Sales. |
| **Tokens** | Access tokens are signed JWTs (HS256, issuer, audience and type checked) that live 15 minutes and are kept only in memory by the web app. The session itself is a refresh token in an `HttpOnly`, `Secure` (in production), `SameSite=Strict` cookie scoped to `/api/v1/auth`, stored server-side as a hash and rotated on every use. Reusing an old refresh token ends all of that user's sessions (stolen-token detection). Logout, password changes and deactivation revoke sessions. On every request the current user, role, active flag and server session are checked in the database. |
| **Brute force** | Failed sign-ins are limited per account (5 per 10 minutes) and per client IP (20 per 10 minutes), returning `429` with `Retry-After`. nginx overwrites `X-Forwarded-For`, so clients can't fake their IP to dodge the limit. |
| **Authorization** | Role checks on every endpoint; sales users only see their own orders; managers can't decide their own orders; activating or deactivating customers is manager-only |
| **Input** | Pydantic validation with unknown fields rejected (no mass assignment); bounded string lengths, quantities and page sizes; parameterised SQL only |
| **Output** | Email templates auto-escape HTML; React escapes everything it renders; `500` responses never include internal details |
| **HTTP** | CSP (scripts from the site's own origin only), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`; API responses are `no-store`; CORS lists explicit origins and sends no credentials |
| **Production config** | The app refuses to start with a default or short JWT secret; API docs are off; demo data can't be loaded; the backend container runs as an unprivileged user; only the web port is published |
| **Dependencies** | `pip-audit`, `npm audit` and `bandit` report no known vulnerabilities (Bandit's only notes are `random` used for demo data in the seed script) |

**Known limitations (accepted for this scope):**
- **Code delivery:** with `OTP_DELIVERY=log` (the default, as requested for this project), anyone who can read the server logs can read sign-in codes. Use `OTP_DELIVERY=email` for real users.
- **Offline logout:** the browser immediately clears local authentication and remembers the sign-out across reloads. If the logout request cannot reach the API, server revocation is retried when connectivity returns. A completed server logout revokes the session, so its access tokens are rejected by the active-session check.
- **Rate limiting:** limits are kept in memory per backend process. Use Redis if you run several replicas. If many staff sign in from one shared office IP, raise `LOGIN_MAX_FAILURES_PER_IP`, so a few typos (or one attacker on that network) can't lock out the whole office.
- **Email delivery:** notification emails are sent in-process after the commit. A crash in that window loses the email, though the order is unaffected. A persistent outbox would make delivery guaranteed.

---

## Production deployment

The development stack publishes its web, API, database and Mailpit ports on `127.0.0.1`.
Use the production overlay for public access; it exposes the HTTPS edge and keeps data services
private. Monitoring additionally requires `GRAFANA_ADMIN_PASSWORD` and binds to loopback.

`docker-compose.prod.yml` layers production settings over the demo stack:
- secrets are required;
- no demo data, no API docs, no Mailpit;
- MySQL and the API are reachable only inside the Docker network, through nginx.

```bash
cp production.env.example production.env      # fill in secrets, SMTP and PUBLIC_URL
docker compose --env-file production.env -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# create the first administrator (prompts for a password, or reads ADMIN_PASSWORD)
docker compose --env-file production.env -f docker-compose.yml -f docker-compose.prod.yml \
    exec backend python -m scripts.create_admin --email you@company.com --name "Your Name"
```

Before going live:
- **Sign-in codes:** set `OTP_DELIVERY=email` so codes reach users by email instead of the server log. Self sign-up is off in production; turn it on with `SIGNUP_ENABLED=true` and limit it with `SIGNUP_ALLOWED_DOMAINS=yourcompany.com`.
- **HTTPS:** the production overlay includes Caddy with HTTPS, redirects and HSTS. Set `SITE_ADDRESS` to your real domain and expose the edge's configured ports; use the matching HTTPS `PUBLIC_URL`.
- **Mail:** use a real SMTP provider. Configure SPF and DKIM for the `MAIL_FROM` domain so the approval emails aren't marked as spam.
- **Backups:** the production backup service writes encrypted dumps and verifies each with a scratch restore. Configure an off-site copy and keep encryption keys separately; see the [runbook](docs/operations/runbook.md).
- **Monitoring:** liveness/readiness, worker health and Prometheus metrics are available internally. Add `docker-compose.observability.yml` with `GRAFANA_ADMIN_PASSWORD`, then connect alerts and log retention.

---

## Run without Docker

Everything also runs directly on Windows, macOS or Linux, with no containers.

**You need:** Python 3.11+, Node.js 22 LTS (22.22.2+) or 24 LTS (24.15+), and MySQL 8.0 or later (8.4 LTS recommended). The Node versions include the requirements of the frontend test tools.
[Mailpit](https://mailpit.axllent.org/docs/install/), a single program, is optional: it catches the
emails so you can read them at http://localhost:8025. Without it, set `EMAIL_ENABLED=false` in
`backend/.env`; everything else works the same, and each email is recorded as `SKIPPED`.

**1. Database (once).** Install MySQL, then run this from the `backend` folder:

```bash
mysql -u root -p -e "source scripts/setup_local_mysql.sql"
```

[The script](backend/scripts/setup_local_mysql.sql) creates the `sims` database (plus `sims_test`
and `sims_migrations` for the automated tests) and the account `sims` / `sims_password` that
`.env.example` uses. It also turns on `log_bin_trust_function_creators`: without it, MySQL refuses
to let the migrations create the audit log's triggers while binary logging is on (the default).
On Windows, if `mysql` is not on your PATH, open the *MySQL Command Line Client* from the Start
menu and run `source C:/path/to/backend/scripts/setup_local_mysql.sql`, or run the file in MySQL
Workbench.

**MySQL Installer on Windows:** the defaults are fine (*Development Computer*, port 3306, strong
password encryption, Windows service); remember the root password. *Open Windows Firewall ports*
is only needed if other computers must reach the database. If the installer marks port 3306 as
in use (for example by this project's Docker MySQL), choose 3307 instead, and use that port in
two places: `-P 3307` when running the setup script (PowerShell:
`& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u root -p -P 3307 -e "source scripts/setup_local_mysql.sql"`)
and `DATABASE_URL=mysql+pymysql://sims:sims_password@127.0.0.1:3307/sims` in `backend/.env`.

**2. API** (terminal 1):

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env
alembic upgrade head
python -m scripts.seed            # demo accounts and data; add --force to reset them
uvicorn app.main:app --reload     # http://localhost:8000/docs - sign-in codes appear here
```

If PowerShell refuses to run `activate`, allow local scripts once with
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use Command Prompt.

**3. Worker** (terminal 2). It sends the emails the API queues (approval requests and decisions,
with retries) and runs the scheduled clean-up:

```bash
cd backend
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
python -m app.worker
```

**4. Frontend** (terminal 3):

```bash
cd frontend
npm ci
npm run dev                       # http://localhost:5173 - forwards /api to the API
```

Open http://localhost:5173 and sign in with a [demo account](#demo-accounts); the one-time code
appears in terminal 1. Redis is not needed: a single API process keeps its rate limits in memory.

- **Port 8000 already in use?** Start the API with `uvicorn app.main:app --reload --port 8001` and
  create `frontend/.env.local` containing `VITE_PROXY_TARGET=http://127.0.0.1:8001`.
- **Production build of the frontend:** `npm run build`, then `npm run preview` serves
  `frontend/dist` at http://localhost:4173 with the same `/api` forwarding. Set
  `FRONTEND_URL=http://localhost:4173` in `backend/.env` so links in emails open it. On a server,
  any web server can serve `dist/` and forward `/api` to the API, as
  [`frontend/nginx.conf`](frontend/nginx.conf) does.
- **Docker for the services only:** `docker compose up -d mysql mailpit` starts a ready-configured
  MySQL and Mailpit; skip step 1.

---

## Tests and code quality

```bash
# Backend: integration, concurrency, security, migration and API-contract tests against real MySQL
# (sims_test: created by docker-compose, or by scripts/setup_local_mysql.sql without Docker)
cd backend
pip install -r requirements-dev.txt
pytest --cov=app
ruff check . && ruff format --check .
mypy app scripts
alembic check                      # the migration matches the models

# Frontend
cd frontend
npm ci
npm run typecheck && npm run lint && npm run format:check && npm run test:coverage
npm run build && npm run size

# Acceptance (end to end): the brief's requirements, step by step, in a real browser.
# Needs the running app (docker compose up, or Run without Docker) with Mailpit receiving the emails.
cd e2e
pip install -r requirements.txt && python -m playwright install chromium
pytest                           # includes responsive/a11y and enterprise flows; frontend npm ci required
# Without Docker: save the API's output (uvicorn app.main:app > backend.log 2>&1), then set
# E2E_BASE_URL=http://localhost:5173 and E2E_OTP_LOG_FILE=../backend/backend.log
# Against another deployment: set E2E_BASE_URL, E2E_MAILPIT_URL, E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD
```

The acceptance suite ([`e2e/test_acceptance.py`](e2e/test_acceptance.py)) creates its own manager, sales user, customer and product on every run. It then walks through the brief in order:
1. sign-in and role checks;
2. managing products;
3. managing customers;
4. order and stock validation;
5. an order within the threshold, confirmed immediately;
6. an order over the threshold, with the manager's email;
7. approval by clicking the link in that email, with the inventory update;
8. the decision email to the user;
9. a rejection with its email;
10. a restock and the stock ledger;
11. the dashboard figures;
12. no errors in the browser console;
13. a check that the accounts created for the run can sign in;
14. self sign-up with email verification (skipped when sign-up is turned off).

Signing in, it reads each development one-time code from the backend log. Set `E2E_OTP_LOG_COMMAND` to point it at another development deployment's log, `E2E_OTP_LOG_FILE` to read a saved log file, or `E2E_OTP_SOURCE=email` to read production login codes from the configured Mailpit test sink.

The backend tests cover:
- **Workflow:**
  - order totals and tax rounding;
  - auto-approval vs approval required, including the threshold boundary;
  - approve, reject and cancel, and double decisions;
  - self-approval;
  - stock running out between order and approval (full rollback);
  - a concurrent oversell race;
  - email failure not affecting orders.
- **Management:** users, customers and products end to end, plus the list filters and the stock ledger.
- **Security:**
  - account and IP lockout;
  - forged, unsigned and expired tokens;
  - immediate effect of deactivation and role changes;
  - mass assignment and SQL-injection strings;
  - HTML escaping in emails;
  - the password policy;
  - security headers and CORS;
  - production config refusing weak secrets;
  - no leaks in 500 errors;
  - `503` during a database outage.

The current hardening review also exercises an isolated production configuration through HTTPS,
with email OTP, real MySQL transactions and the mail worker. The browser suite runs with CSP
enforced and covers the assignment workflow, password reset, offline logout, permission checks,
query failures, 108 responsive page/dialog states and 36 automated accessibility scans per
environment. Encrypted backup restore, live monitoring, release smoke tests and API load tests
have been checked separately. Exact executed results, test settings and remaining deployment
checks are recorded in [docs/qa/verification.md](docs/qa/verification.md).

---

## Configuration

Backend settings come from environment variables or `backend/.env` (see [`backend/.env.example`](backend/.env.example)).

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `production` enforces a strong JWT secret and explicit CORS origins, and hides the API docs |
| `ENABLE_API_DOCS` | on, except in production | Force Swagger/ReDoc on or off |
| `DATABASE_URL` | `mysql+pymysql://sims:sims_password@127.0.0.1:3306/sims` | |
| `JWT_SECRET_KEY` | dev value | **At least 32 random characters in production** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_DAYS` | `15` / `7` | Short-lived access token; the refresh cookie rotates on every use |
| `COOKIE_SECURE` | on in production | Send the refresh cookie over HTTPS only |
| `LOGIN_OTP_REQUIRED` | `true` | Second sign-in step with a one-time code |
| `OTP_DELIVERY` | `log` | `log`: printed to the backend terminal / `docker compose logs backend`; `email`: sent via SMTP |
| `OTP_TTL_SECONDS` / `OTP_MAX_ATTEMPTS` / `OTP_RESEND_COOLDOWN_SECONDS` / `OTP_MAX_SENDS` | `300` / `5` / `30` / `5` | Code rules |
| `SIGNUP_ENABLED` / `SIGNUP_ALLOWED_DOMAINS` | `true` (off in the production overlay) / any | Self sign-up; e.g. `company.com` limits it to company addresses |
| `LOGIN_MAX_FAILURES_PER_EMAIL` / `_PER_IP` / `LOGIN_FAILURE_WINDOW_SECONDS` | `5` / `20` / `600` | Sign-in brute-force limits |
| `SEED_DEMO_DATA` | `true` in the demo stack, `false` in production | Docker only: load demo data on start |
| `SMTP_HOST` / `SMTP_PORT` | `127.0.0.1` / `1025` | Mailpit. For Gmail: `smtp.gmail.com`, `587`, `SMTP_STARTTLS=true`, an app password in `SMTP_USER` / `SMTP_PASSWORD` |
| `EMAIL_ENABLED` | `true` | `false` logs emails as `SKIPPED` instead of sending them |
| `FRONTEND_URL` | `http://localhost:5173` | Used for links inside emails |
| `DEFAULT_APPROVAL_THRESHOLD` / `DEFAULT_TAX_RATE` | `50000.00` / `18.00` | Starting values; admins can change them in the app |

---

## Project structure

```
├── docker-compose.yml          demo stack: MySQL, Mailpit, backend, frontend
├── docker-compose.prod.yml     production overrides (see Production deployment)
├── production.env.example      template for production secrets
├── backend/
│   ├── app/
│   │   ├── api/                routers (v1) and dependencies (auth, roles, pagination)
│   │   ├── core/               config, database session and transactions, security, error handling
│   │   ├── models/             SQLAlchemy models
│   │   ├── schemas/            Pydantic request/response models (validation)
│   │   ├── services/           business logic: orders, inventory, email, dashboard…
│   │   └── templates/email/    HTML email templates (Jinja2)
│   ├── alembic/                migrations
│   ├── scripts/                seed.py (demo data), create_admin.py (first admin in production)
│   └── tests/                  pytest suite
├── e2e/                        acceptance tests: the brief, step by step, in a real browser
└── frontend/
    └── src/
        ├── api/                axios client and typed endpoint functions
        ├── auth/               auth context and route guards
        ├── components/         layout, data table, charts, shared UI
        └── pages/              dashboard, orders, approvals, products, customers, ledger, settings
```

### Enterprise architecture and verification

The production controls, platform setup required before launch, and decisions about the wider
engineering checklist are documented in [docs/enterprise-readiness.md](docs/enterprise-readiness.md).
The [architecture diagrams](docs/architecture/README.md) describe domains, deployment and trust
boundaries. See the [current verification record](docs/qa/verification.md) for executed checks.

### Optional product extensions

- Reserve stock while an order is pending (today it is re-checked at approval instead)
- Signed one-click approve/reject links in the email
- CSV export and per-period reports
