#!/bin/bash
# Restore an encrypted backup into a database.
#   restore.sh <backup file> [target database] [mysql user]
# Verifies the HMAC before decrypting. Restoring over the live "sims" database is a deliberate,
# manual step (see docs/operations/runbook.md, "Restore from backup"): stop the API and worker first.
set -euo pipefail
umask 077

file=${1:?usage: restore.sh <backup file> [target database] [mysql user]}
target=${2:-sims_restore_check}
user=${3:-sims_restore}
password=${RESTORE_DB_PASSWORD:-${MYSQL_RESTORE_PASSWORD:-}}
: "${MYSQL_HOST:=mysql}"
: "${BACKUP_ENCRYPTION_KEY:?BACKUP_ENCRYPTION_KEY is required}"
[[ "$target" =~ ^[A-Za-z_][A-Za-z0-9_]{0,63}$ ]] || { echo "Target database must be a valid SQL identifier" >&2; exit 2; }
[[ "$user" =~ ^[A-Za-z_][A-Za-z0-9_]{0,31}$ ]] || { echo "MySQL user must be a valid identifier" >&2; exit 2; }
[ -n "$password" ] || { echo "A restore database password is required" >&2; exit 2; }
if [ ! -f "$file" ] || [ ! -f "$file.hmac" ]; then
  echo "Backup and HMAC files are required" >&2
  exit 2
fi

expected=$(cat "$file.hmac")
actual=$(openssl dgst -sha256 -hmac "$BACKUP_ENCRYPTION_KEY" -r "$file" | cut -d' ' -f1)
if [ "$expected" != "$actual" ]; then
  echo "{\"event\":\"restore.refused\",\"reason\":\"HMAC mismatch\",\"file\":\"$(basename "$file")\"}" >&2
  exit 2
fi

CNF=$(mktemp /tmp/restore.XXXXXX.cnf)
trap 'rm -f "$CNF"' EXIT
printf '[client]\nuser=%s\npassword=%s\nhost=%s\nssl-mode=%s\n' "$user" "$password" "$MYSQL_HOST" "${MYSQL_SSL_MODE:-REQUIRED}" > "$CNF"
mysql --defaults-extra-file="$CNF" -e "CREATE DATABASE IF NOT EXISTS \`$target\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
# Triggers are dumped with DEFINER=<schema owner>; recreating them as another account would need
# SET_ANY_DEFINER, so the clause is dropped and the restoring account becomes the definer.
# SQL identifiers use literal backticks; they must not be expanded by the shell.
# shellcheck disable=SC2016
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_ENCRYPTION_KEY -in "$file" \
  | gunzip \
  | sed -E 's#/\*!50017 DEFINER=`[^`]+`@`[^`]+`\*/ ##' \
  | mysql --defaults-extra-file="$CNF" "$target"
rm -f "$CNF"
echo "{\"event\":\"restore.completed\",\"file\":\"$(basename "$file")\",\"database\":\"$target\"}"
