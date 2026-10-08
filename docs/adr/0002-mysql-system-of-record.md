# 0002 MySQL 8.4 as the system of record

**Context.** The brief specifies MySQL. The enterprise checklist suggests PostgreSQL.

**Decision.** MySQL 8.4 LTS, with InnoDB row locks (`SELECT ... FOR UPDATE`, taken in id order to
avoid deadlocks), READ COMMITTED isolation, CHECK constraints, triggers for the audit trail,
binary logs for point-in-time recovery, `require_secure_transport`, statement and lock-wait
timeouts, and separate accounts for schema changes, the application, backups and restore checks.

**Consequences.** Everything the checklist asks of the database (constraints, timeouts, TLS, least
privilege, encrypted backups with restore tests, PITR) is met on MySQL. `SKIP LOCKED` makes the
outbox safe for many workers. Creating triggers needs `log_bin_trust_function_creators=ON` (set in
Compose; on RDS/Cloud SQL through the parameter group).
