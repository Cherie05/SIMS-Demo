# Runbook

Commands assume the production checkout on the host (`/opt/sims`) and this alias:

```bash
alias dc='docker compose --env-file production.env -f docker-compose.yml -f docker-compose.prod.yml'
```

Run the checked-in scripts with `sh` or `bash`. Before deploying, set `PUBLIC_URL` in the shell
to the same HTTPS URL in `production.env`; Compose's env file does not export it to the deploy
script. Set `GRAFANA_ADMIN_PASSWORD` when using the monitoring overlay. Its ports bind to loopback.

Every log line and every API error carries a `request_id`; start an investigation by searching the
logs for it: `dc logs --no-color | grep <request id>`.

## Contents

Deploy and rollback · Scaling · Routine administration · Secret rotation · Backups and recovery ·
Alert playbooks · Incident response

---

## Deploy and rollback

Releases are tags (`v1.2.3`). CI builds, signs and publishes the images; the release workflow
deploys to staging, waits for approval, then deploys to production (`ops/deploy.sh`), smoke-tests
(`ops/smoke-test.sh`) and rolls back automatically if the smoke test fails.

Manual deploy of a release:

```bash
PUBLIC_URL=https://sims.example.com sh ops/deploy.sh v1.2.3 ghcr.io/org/sims/backend@sha256:... ghcr.io/org/sims/frontend@sha256:...
```

Order of events: images pulled → `db-init` (accounts) → `migrate` (schema) → API, worker and web
restarted one service at a time (`--wait` for health) → smoke test → release recorded.

Rollback to the previous successful release: `sh ops/deploy.sh --rollback` with `PUBLIC_URL` set.

Rollback switches images without downgrading the database. It is bounded to one attempt and can
fail health checks if the old image does not recognize a newly migrated schema. Test compatibility
before a migration-changing release; use a forward fix when rollback is incompatible. The script
does not promise zero downtime or automatic recovery across arbitrary schema changes.

### Database migration rules (zero downtime)

Migrations run before the new code starts. Plan changes with expand/contract and test the previous
release's readiness and behavior against the new schema:

1. **Expand** release: add nullable columns / new tables / new indexes; code writes both old and new.
2. Backfill in batches (a job or a separate migration), never in a long locking statement.
3. **Contract** release (a later deploy): code stops using the old column; a migration drops it.

Every migration must downgrade cleanly; CI runs upgrade → downgrade → upgrade and compares the
result with the models (`tests/test_migrations.py`).

## Scaling

```bash
dc up -d --scale backend=3      # nginx picks up new replicas within 10 s
dc up -d --scale worker=2       # workers share the queue safely (SKIP LOCKED)
```

The local [performance run](performance.md) measured 59.206 req/s with two API replicas, each
limited to 1 CPU / 512 MB, for its tested traffic mix. Size the intended workload empirically;
this measurement does not establish per-replica capacity or performance after losing a replica.

## Routine administration

| Task | How |
|---|---|
| First admin / locked-out admin (break-glass) | `dc exec backend python -m scripts.create_admin --email you@company.com --name "You"` (prompts for the password; resets it and signs out the account's sessions; audited) |
| User lost their authenticator app and recovery codes | Admin → API `POST /api/v1/users/{id}/mfa/reset` (audited, user is emailed) |
| Sign a user out everywhere (suspected compromise) | `POST /api/v1/users/{id}/sessions/revoke`, then deactivate or reset the password |
| Account locked by failed sign-ins | expires after 10 minutes; to clear at once: `dc restart redis` (clears all counters) |
| Pause order intake / hold emails | System page → feature flags (`orders.create`, `notifications.email`) |
| Retry a failed email | System page → background jobs → Dead → Retry |
| Check health | System page, or `curl -s https://<host>/api/v1/auth/config` and `dc ps` |

## Secret rotation

| Secret | Procedure | Impact |
|---|---|---|
| `JWT_SECRET_KEY` | set `JWT_PREVIOUS_SECRET_KEYS=<old>`, `JWT_SECRET_KEY=<new>`, `dc up -d backend worker`; after 15 minutes remove the previous key and redeploy | none (old tokens stay valid until they expire); open sign-in codes become invalid |
| `DATA_ENCRYPTION_KEYS` | prepend the new key (`new,old`), redeploy; data is decrypted with any key and new secrets use the first; drop the old key only after every row was re-encrypted | none |
| MySQL account passwords | change the value in `production.env`, `dc up -d db-init` (re-applies passwords), then `dc up -d backend worker backup` | a few seconds of reconnects |
| `REDIS_PASSWORD` | change, `dc up -d redis backend worker` | rate-limit counters reset |
| `BACKUP_ENCRYPTION_KEY` | new backups use the new key; keep the old key in the secret manager until its backups expire | none |
| SMTP password | change and `dc up -d worker` | emails wait and retry meanwhile |

## Backups and recovery

- The `backup` service writes an encrypted dump every `BACKUP_INTERVAL_SECONDS` (default daily) to
  `BACKUP_DIR`, verifies it by restoring into a scratch database, and keeps `BACKUP_RETENTION_DAYS`.
- **Copy backups off the host** (object storage with versioning / immutability), e.g. a nightly
  `aws s3 sync ./backups s3://company-sims-backups/ --sse`. Keep `BACKUP_ENCRYPTION_KEY` in the
  secret manager, never next to the backups.
- Status: `dc ps backup` (healthy while the last success is recent) and `backups/restore-check-latest.json`.

### Restore from backup (disaster recovery)

```bash
dc stop backend worker                                # no writes during the restore
dc exec backup bash /scripts/restore.sh /backups/sims-<timestamp>.sql.gz.enc sims sims   # target db, owner account
#   (RESTORE_DB_PASSWORD=<MYSQL_PASSWORD> in the environment for the owner account)
dc up -d migrate backend worker                       # migrations bring an older dump up to date
ops/smoke-test.sh https://<host>
```

### Point-in-time recovery

Binary logs are kept for 7 days. To recover to just before an incident (e.g. a bad bulk update at
14:32): restore the last backup into a new database, then replay the binlogs from the backup time
until 14:31:59 with `mysqlbinlog --start-datetime=... --stop-datetime=... binlog.0000NN | mysql`
(run from a MySQL client image that includes `mysqlbinlog`), verify, and switch the application to
it. On a managed database use the provider's PITR instead.

### Restore drill log

| Date | Backup | Target | Result | Duration |
|---|---|---|---|---|
| 2026-10-07 | automatic check | scratch DB | ok: 20 tables, 2 triggers, revision 8f177e669e12 | 4 s |

---

## Alert playbooks

### API down
`up{job="sims-api"} == 0`. Check `dc ps backend` and `dc logs --tail 200 backend`. Readiness
(`/health/ready`) shows which dependency fails. Common causes: database unreachable (see below),
bad configuration after a deploy (the config validator logs the reason and refuses to start) →
`ops/deploy.sh --rollback`.

### High error rate
More than 1 % of requests return 5xx. Grafana "Traffic by status class" and the logs with
`level=ERROR` give the route and request ids. `503 SERVICE_UNAVAILABLE` means the database is
unreachable or overloaded (lock waits, timeouts): check `dc logs mysql`, the slow-query log
(`dc exec mysql tail -50 /var/lib/mysql/*slow.log`) and connection counts. A spike right after a
deploy → roll back first, investigate second.

### Slow responses
p95 above 500 ms. Check "Slowest routes" in Grafana and CPU (`docker stats`). CPU-bound replicas →
scale out (`--scale backend=N`). One slow route → its queries in the slow-query log. Lock waits →
look for long transactions (`SHOW PROCESSLIST`).

### Worker down
No heartbeat for 2 minutes: emails and housekeeping stop (orders are unaffected - emails wait).
`dc ps worker`, `dc logs --tail 100 worker`; restart with `dc up -d worker`. Pending emails go out
in order once it's back.

### Dead-letter jobs
An email failed 6 times (or the mail server rejected it permanently). System page → background
jobs → Dead shows the error. Fix the cause (SMTP credentials, recipient address), then Retry.

### Email backlog
More than 100 emails waiting for 10 minutes: SMTP slow or failing (see `last_error` on RETRY jobs),
or the `notifications.email` flag is off. Scale workers if SMTP is healthy but slow.

### Sign-in attack
Many failed sign-in steps per minute. Audit log → filter `auth.login.failed` to see targeted
accounts and source IPs. Limits already slow attackers; for a sustained attack block the source at
the WAF/edge, and consider requiring authenticator apps for targeted accounts.

### Redis degraded
Valkey unreachable: rate limits fall back to per-replica memory (still enforced, but per instance).
`dc ps redis`, `dc logs redis`; `dc up -d redis`.

### Browser errors
JavaScript errors reported by browsers: `dc logs backend | grep client.error` shows message, page
and release. A spike right after a deploy points at the release → roll back.

---

## Incident response

1. **Declare** (anyone): open an incident channel, name an incident commander (IC), set a severity
   ([slo.md](slo.md)).
2. **Stabilise before fixing**: roll back, scale out, flip a kill switch, block an IP at the edge.
3. **Communicate**: status to stakeholders every 30 minutes (SEV1) / at milestones (SEV2).
4. **Security incidents** additionally: preserve evidence (export the audit log for the window, keep
   logs), rotate exposed secrets (table above), sign out affected users everywhere, assess personal
   data exposure and contact the organization's incident/privacy owner to apply the relevant
   reporting obligations and deadlines.
5. **Review** within 5 working days: blameless write-up with timeline (request ids, audit entries),
   root cause, what detection missed, and action items with owners - tracked to completion.
