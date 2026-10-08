# Run the website on Windows

Copy these commands into **PowerShell**. This guide runs the local demo with Docker or with a
locally installed MySQL server. In every terminal, replace `C:\Users\arunv\Documents\web` if
your project is in another folder.

The commands use API port **8001** because another application on this PC uses port 8000.
Choose one setup at a time. Existing environment files and database data are preserved.

| Setup | Website | API documentation | Email inbox |
|---|---|---|---|
| Docker | http://localhost:3000 | http://localhost:8001/docs | http://localhost:8025 |
| Without Docker, development frontend | http://localhost:5173 | http://localhost:8001/docs | http://localhost:8025, if Mailpit is running |
| Without Docker, built frontend | http://localhost:4173 | http://localhost:8001/docs | http://localhost:8025, if Mailpit is running |

## 1. Run with Docker

Install Docker Desktop and start it. Docker supplies MySQL, the API, worker, frontend and Mailpit;
you do not need a local Python, Node.js or MySQL installation for this setup.

### First start, or after changing the source

```powershell
Set-Location 'C:\Users\arunv\Documents\web'
$env:BACKEND_PORT = '8001'
$env:FRONTEND_PORT = '3000'
docker compose up -d --build
docker compose ps -a
```

The first build can take several minutes. Wait until the backend and frontend show `healthy`.
The one-time `db-init` and `migrate` services should finish with `Exited (0)`.
Migrations and demo data are loaded automatically. Open http://localhost:3000.

### Get your login code

Keep this running in a second PowerShell terminal. After submitting your email and password,
look for the latest `OTP for your-email (sign-in): 123456` entry. Enter that code in the browser.

```powershell
Set-Location 'C:\Users\arunv\Documents\web'
docker compose logs -f backend
```

Press **Ctrl+C** to stop following the log; the website stays running.

### Health, emails and troubleshooting logs

```powershell
Set-Location 'C:\Users\arunv\Documents\web'
Invoke-RestMethod 'http://127.0.0.1:8001/health/ready' | ConvertTo-Json -Depth 5
docker compose logs --tail 100 backend worker migrate db-init
```

View approval and decision emails at http://localhost:8025. They are captured locally by Mailpit.

### Stop and start again

Stop the demo while keeping its database volume:

```powershell
Set-Location 'C:\Users\arunv\Documents\web'
docker compose down
```

Start the existing images again:

```powershell
Set-Location 'C:\Users\arunv\Documents\web'
$env:BACKEND_PORT = '8001'
$env:FRONTEND_PORT = '3000'
docker compose up -d
```

## 2. Run without Docker

### Prerequisites

Install these first, then open a new PowerShell terminal:

- Python 3.11 or later; the verified Windows environment uses Python 3.11.
- Node.js 22 LTS, version 22.22.2 or later, or Node.js 24 LTS, version 24.15 or later.
- MySQL 8.0 or later; MySQL 8.4 LTS is the project's recommended version. Start its Windows service.
- Optional: the Windows Mailpit executable, if you want to view notification emails.

Native MySQL is currently not installed on this PC. Install it before following this section.
The Docker and native MySQL instances have separate data.

```powershell
python --version
node --version
npm.cmd --version
Get-Service -Name '*MySQL*' -ErrorAction SilentlyContinue
```

`npm.cmd` avoids PowerShell's script execution-policy issue. Python commands below use the virtual
environment executable directly, so activating it or changing execution policy is unnecessary.

If the Docker demo is running, stop it first using the `docker compose down` command above so
ports 3306, 8001, 1025 and 8025 are available. If your native MySQL uses a different port, use
that port in both the database setup command and `DATABASE_URL` below.

### One-time database setup

Run this against your **native MySQL server**. Enter the root password chosen during MySQL installation.

```powershell
Set-Location 'C:\Users\arunv\Documents\web\backend'
mysql -h 127.0.0.1 -P 3306 -u root -p -e "source scripts/setup_local_mysql.sql"
```

If `mysql` is not on PATH, use its installed executable instead; adjust the folder if necessary:

```powershell
Set-Location 'C:\Users\arunv\Documents\web\backend'
& 'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe' -h 127.0.0.1 -P 3306 -u root -p -e "source scripts/setup_local_mysql.sql"
```

Choose the command that matches your installation. The script creates `sims`, the two test databases
and the local demo database account. It also enables the MySQL setting required by migration triggers.

### One-time backend setup

```powershell
Set-Location 'C:\Users\arunv\Documents\web\backend'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Creating the Python environment failed.' }
}
& .\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Installing backend dependencies failed.' }
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
notepad .env
```

In `backend/.env`, set these values. Edit existing entries rather than adding duplicates.
Use port 3307 in `DATABASE_URL` instead if that is where your native MySQL runs.

```dotenv
ENVIRONMENT=development
DATABASE_URL=mysql+pymysql://sims:sims_password@127.0.0.1:3306/sims
DATABASE_PASSWORD=
REDIS_URL=
REDIS_PASSWORD=
COOKIE_SECURE=false
LOGIN_OTP_REQUIRED=true
OTP_DELIVERY=log
FRONTEND_URL=http://localhost:5173
CORS_ORIGINS=http://localhost:5173,http://localhost:4173,http://localhost:3000
EMAIL_ENABLED=false
SMTP_HOST=127.0.0.1
SMTP_PORT=1025
SMTP_USER=
SMTP_PASSWORD=
SMTP_STARTTLS=false
SMTP_SSL=false
```

Save and close Notepad. With `EMAIL_ENABLED=false`, notifications are recorded as `SKIPPED`;
the order and approval workflow still runs. For email verification, use the optional Mailpit
step below and change `EMAIL_ENABLED` to `true` before starting the API and worker.

Apply migrations and load the demo accounts. Normal seeding skips an already seeded database.

```powershell
Set-Location 'C:\Users\arunv\Documents\web\backend'
& .\.venv\Scripts\python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed; check MySQL and backend/.env.' }
& .\.venv\Scripts\python.exe -m scripts.seed
if ($LASTEXITCODE -ne 0) { throw 'Loading demo data failed.' }
```

### Optional: start Mailpit in its own terminal

Download and extract the Windows executable following the [official installation instructions](https://mailpit.axllent.org/docs/install/).
This example assumes it is saved as `C:\Tools\Mailpit\mailpit.exe`; replace the path with yours.
Keep this terminal open while testing emails.

```powershell
& 'C:\Tools\Mailpit\mailpit.exe' --listen 127.0.0.1:8025 --smtp 127.0.0.1:1025
```

The two flags bind the inbox and SMTP listener to this computer; see the
[official Mailpit runtime options](https://mailpit.axllent.org/docs/configuration/runtime-options/).
Set `EMAIL_ENABLED=true` in `backend/.env`. Open http://localhost:8025 to view emails.

### Terminal 1: API

```powershell
Set-Location 'C:\Users\arunv\Documents\web\backend'
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Keep this terminal open. Login codes appear here. API docs: http://localhost:8001/docs.

### Terminal 2: background worker

The worker sends queued approval/decision emails and performs scheduled cleanup.

```powershell
Set-Location 'C:\Users\arunv\Documents\web\backend'
& .\.venv\Scripts\python.exe -m app.worker
```

Keep this terminal open too.

### Terminal 3: frontend

Run `npm.cmd ci` on first setup or after changing the lockfile. Create the frontend configuration
only if missing, then ensure it contains `VITE_PROXY_TARGET=http://127.0.0.1:8001`.

```powershell
Set-Location 'C:\Users\arunv\Documents\web\frontend'
npm.cmd ci
if ($LASTEXITCODE -ne 0) { throw 'Installing frontend dependencies failed.' }
if (-not (Test-Path -LiteralPath '.env.local')) {
    Set-Content -LiteralPath '.env.local' -Value 'VITE_PROXY_TARGET=http://127.0.0.1:8001' -Encoding ascii
}
notepad .env.local
```

Save and close Notepad, then start the frontend in that terminal:

```powershell
npm.cmd run dev -- --port 5173 --strictPort
```

Open **http://localhost:5173**. On subsequent starts, keep the API and worker commands above
and run only the frontend start command from the frontend folder.

### Run the built frontend instead

Stop the development frontend with **Ctrl+C**. In `backend/.env`, change
`FRONTEND_URL=http://localhost:4173` so email links point to the preview. Restart the API and worker
after editing backend settings. Keep `VITE_PROXY_TARGET=http://127.0.0.1:8001` in `frontend/.env.local`.

```powershell
Set-Location 'C:\Users\arunv\Documents\web\frontend'
npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'The frontend build failed.' }
npm.cmd run preview -- --port 4173 --strictPort
```

Open **http://localhost:4173**. Preview serves the built frontend locally; public production
deployment is described separately in [the README](README.md#production-deployment).

### Stop the native setup

Press **Ctrl+C** in the frontend, worker and API terminals, and in the Mailpit terminal if used.
The MySQL Windows service and its database data stay in place.

## 3. Demo login accounts

| Role | Email | Password |
|---|---|---|
| Admin | admin@example.com | Admin@123 |
| Manager | manager@example.com | Manager@123 |
| Sales | sales@example.com | Sales@123 |
| Second Sales user | sales2@example.com | Sales@123 |

Enter the email and password, then get the current six-digit code from Docker's backend log or
the native API terminal. Codes expire after five minutes. Use a regular browser window for Sales
and an Incognito window for Manager when testing approval decisions.

## 4. Verify that it works

For either setup, check the API after it has started:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8001/health/ready' | ConvertTo-Json -Depth 5
```

Then check these in the browser:

1. Sign in as Admin and create/edit a product and customer.
2. Create a Sales order below the configured approval threshold; confirm completion and stock deduction.
3. Create an order above the threshold; confirm pending approval and unchanged stock.
4. As Manager, approve it; confirm completion, stock deduction and notification emails if email is enabled.
5. Reject another pending order; confirm unchanged stock.
6. Restock the same product by five units twice; stock should increase by ten.
7. Try insufficient stock and empty required fields; check validation messages.
8. Refresh, log out and refresh again; confirm you remain signed out.
9. Use browser responsive mode at 360, 390, 768, 1024 and 1440px to check menus, forms and dialogs.

## 5. Common startup problems

| Problem | What to check |
|---|---|
| Docker cannot connect | Open Docker Desktop and wait for its engine to start. |
| A port is occupied | Stop the other setup you started. For native MySQL on another port, update both the setup command and `DATABASE_URL`. For a different API port, change both `--port` and `VITE_PROXY_TARGET`. |
| `mysql` is not recognized | Use the full MySQL executable path shown above. |
| API reports database connection failure | Check that native MySQL is running, the setup SQL succeeded and `DATABASE_URL` matches its port/account. |
| MySQL error 1419 during migration | Run `scripts/setup_local_mysql.sql` as MySQL root before migrating. |
| Frontend shows network errors or 502 | Check API health, the API terminal and the frontend proxy target. Restart Vite after changing `.env.local`. |
| Emails do not arrive | Run the worker and Mailpit, set `EMAIL_ENABLED=true`, and restart API/worker after configuration changes. |
| Login code is missing | Submit the password first, then check the latest backend/API log entry for that email. |
| Login returns 429 | Follow the retry time shown by the app; repeated failed attempts are limited. |

These `localhost` addresses work on the computer running the application. Reviewers can use the
same guide after cloning or extracting the source; sharing a localhost URL does not publish the site.
