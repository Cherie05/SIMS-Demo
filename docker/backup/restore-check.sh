#!/bin/bash
# Prove the newest backup can actually be restored: restore it into a scratch database, check the
# schema, migration version, audit triggers and row counts, then drop the scratch database.
# Writes /backups/restore-check-latest.json. A backup that has never been restored is a hope, not a backup.
set -euo pipefail
umask 077

: "${MYSQL_HOST:=mysql}"
: "${BACKUP_DIR:=/backups}"
SCRATCH=sims_restore_check

latest=''
# Filenames contain UTC timestamps, so lexical order is chronological without parsing ls output.
for candidate in "$BACKUP_DIR"/sims-*.sql.gz.enc; do
  if [ -f "$candidate" ] && [[ "$candidate" > "$latest" ]]; then latest=$candidate; fi
done
if [ -z "$latest" ]; then
  echo '{"event":"restore_check.skipped","reason":"no backups yet"}'
  exit 0
fi

: "${MYSQL_RESTORE_PASSWORD:?MYSQL_RESTORE_PASSWORD is required}"
CNF=$(mktemp /tmp/restore-check.XXXXXX.cnf)
printf '[client]\nuser=sims_restore\npassword=%s\nhost=%s\nssl-mode=%s\n' "$MYSQL_RESTORE_PASSWORD" "$MYSQL_HOST" "${MYSQL_SSL_MODE:-REQUIRED}" > "$CNF"
q() { mysql --defaults-extra-file="$CNF" -N -B -e "$1"; }
cleanup() { q "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1 || true; rm -f "$CNF"; }
trap cleanup EXIT

started=$(date +%s)
q "DROP DATABASE IF EXISTS $SCRATCH"
bash "$(dirname "$0")/restore.sh" "$latest" "$SCRATCH" sims_restore > /dev/null

tables=$(q "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='$SCRATCH'")
triggers=$(q "SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='$SCRATCH'")
revision=$(q "SELECT version_num FROM $SCRATCH.alembic_version")
users=$(q "SELECT COUNT(*) FROM $SCRATCH.users")
orders=$(q "SELECT COUNT(*) FROM $SCRATCH.sales_orders")
audit=$(q "SELECT COUNT(*) FROM $SCRATCH.audit_logs")
q "DROP DATABASE $SCRATCH"

status=ok
[ "$tables" -ge 19 ] || status=failed
[ "$triggers" -ge 2 ] || status=failed
[ -n "$revision" ] || status=failed

result="{\"event\":\"restore_check.$status\",\"file\":\"$(basename "$latest")\",\"tables\":$tables,\"triggers\":$triggers,\"revision\":\"$revision\",\"users\":$users,\"orders\":$orders,\"audit_entries\":$audit,\"seconds\":$(( $(date +%s) - started )),\"checked_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
echo "$result" > "$BACKUP_DIR/restore-check-latest.json"
echo "$result"
[ "$status" = ok ]
