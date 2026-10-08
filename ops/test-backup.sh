#!/bin/bash
# Exercise the real encryption/restore pipelines against fake SQL clients; never contacts a database.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
scratch=$(mktemp -d /tmp/sims-backup-test.XXXXXX)
trap 'rm -rf "$scratch"' EXIT
mkdir "$scratch/bin" "$scratch/backups"
export TEST_SCRATCH=$scratch
export PATH="$scratch/bin:$PATH"
export BACKUP_DIR="$scratch/backups"
export BACKUP_ENCRYPTION_KEY=validation_only_0123456789_0123456789_0123456789
export MYSQL_BACKUP_PASSWORD=validation_only
export MYSQL_RESTORE_PASSWORD=validation_only
export MYSQL_SSL_MODE=REQUIRED

cat > "$scratch/bin/mysqldump" <<'SH'
#!/bin/sh
[ "${FAIL_DUMP:-false}" != true ] || exit 1
printf '%s\n' '-- synthetic SQL for an isolated test' 'CREATE TABLE test_backup (id INT);'
SH
cat > "$scratch/bin/mysql" <<'SH'
#!/bin/sh
printf '%s\n' invoked >> "$TEST_SCRATCH/mysql-calls"
case " $* " in *' -e '*) exit 0 ;; esac
cat > "$TEST_SCRATCH/restored.sql"
SH
chmod 700 "$scratch/bin/mysql" "$scratch/bin/mysqldump"

bash "$root/docker/backup/backup.sh"
files=("$BACKUP_DIR"/*.sql.gz.enc)
[ "${#files[@]}" = 1 ]
file=${files[0]}
[ -s "$file.hmac" ] && [ -s "$file.sha256" ]
bash "$root/docker/backup/restore.sh" "$file" sims_restore_check sims_restore
grep -q 'CREATE TABLE test_backup' "$scratch/restored.sql"

# Tamper detection must reject the backup before any SQL client can run.
rm -f "$scratch/mysql-calls"
printf 'tampered' >> "$file"
if bash "$root/docker/backup/restore.sh" "$file" sims_restore_check sims_restore >/dev/null 2>&1; then
  echo "Tampered backup was accepted" >&2; exit 1
fi
[ ! -f "$scratch/mysql-calls" ]
if bash "$root/docker/backup/restore.sh" "$file" 'scratch;DROP DATABASE sims' sims_restore >/dev/null 2>&1; then
  echo "An invalid database identifier was accepted" >&2; exit 1
fi
[ ! -f "$scratch/mysql-calls" ]

# A failed dump must leave no published incomplete ciphertext or temporary credentials.
if FAIL_DUMP=true bash "$root/docker/backup/backup.sh" >/dev/null 2>&1; then
  echo "A failed SQL dump was accepted" >&2; exit 1
fi
if compgen -G "$BACKUP_DIR/*.partial" >/dev/null || compgen -G '/tmp/backup.*.cnf' >/dev/null || compgen -G '/tmp/restore.*.cnf' >/dev/null; then
  echo "Backup/restore temporary files leaked" >&2; exit 1
fi
echo "Encrypted backup, restore, tamper rejection, identifier validation and cleanup checks passed."
