#!/bin/sh
# Least-privilege database accounts. Runs on every `docker compose up` (idempotent), so it also
# applies password rotations: change the value in the environment and re-run.
#
#   sims          schema owner (created by the MySQL image): migrations only
#   sims_app      the API and the worker: read/write data, no DDL
#   sims_backup   mysqldump: read-only
#   sims_restore  restore verification: full rights on the scratch database only
#
# Passwords must be URL-safe random strings (see production.env.example).
set -eu
umask 077

for password in "$MYSQL_ROOT_PASSWORD" "$MYSQL_MIGRATION_PASSWORD" "$MYSQL_APP_PASSWORD" "$MYSQL_BACKUP_PASSWORD" "$MYSQL_RESTORE_PASSWORD"; do
  case "$password" in ''|*[!A-Za-z0-9_-]*) echo "Database passwords must be nonempty URL-safe strings." >&2; exit 1 ;; esac
done
CNF=$(mktemp /tmp/provision.XXXXXX.cnf)
trap 'rm -f "$CNF"' 0
printf '[client]\nuser=root\npassword=%s\nhost=%s\nssl-mode=%s\n' "$MYSQL_ROOT_PASSWORD" "${MYSQL_HOST:-mysql}" "${MYSQL_SSL_MODE:-PREFERRED}" > "$CNF"

mysql --defaults-extra-file="$CNF" <<SQL
ALTER USER 'sims'@'%' IDENTIFIED BY '${MYSQL_MIGRATION_PASSWORD}';

CREATE USER IF NOT EXISTS 'sims_app'@'%' IDENTIFIED BY '${MYSQL_APP_PASSWORD}';
ALTER USER 'sims_app'@'%' IDENTIFIED BY '${MYSQL_APP_PASSWORD}';
GRANT SELECT, INSERT, UPDATE, DELETE ON sims.* TO 'sims_app'@'%';

CREATE USER IF NOT EXISTS 'sims_backup'@'%' IDENTIFIED BY '${MYSQL_BACKUP_PASSWORD}';
ALTER USER 'sims_backup'@'%' IDENTIFIED BY '${MYSQL_BACKUP_PASSWORD}';
GRANT SELECT, SHOW VIEW, TRIGGER, EVENT, LOCK TABLES ON sims.* TO 'sims_backup'@'%';

CREATE USER IF NOT EXISTS 'sims_restore'@'%' IDENTIFIED BY '${MYSQL_RESTORE_PASSWORD}';
ALTER USER 'sims_restore'@'%' IDENTIFIED BY '${MYSQL_RESTORE_PASSWORD}';
GRANT ALL PRIVILEGES ON sims_restore_check.* TO 'sims_restore'@'%';

FLUSH PRIVILEGES;
SQL

rm -f "$CNF"
echo "Database accounts provisioned: sims_app (DML), sims_backup (read-only), sims_restore (scratch DB only)."
