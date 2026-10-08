#!/bin/bash
# Encrypted logical backup of the sims database.
#   output: /backups/sims-<UTC timestamp>.sql.gz.enc  + .hmac (integrity) + .sha256 (transport check)
#   mysqldump --single-transaction: a consistent snapshot without locking the application.
#   Encryption: AES-256-CBC with PBKDF2 (200k iterations), then an HMAC-SHA256 over the ciphertext
#   (encrypt-then-MAC), both keyed from BACKUP_ENCRYPTION_KEY. Keep that key in a secret manager,
#   not next to the backups.
set -euo pipefail
umask 077

: "${MYSQL_HOST:=mysql}"
: "${MYSQL_BACKUP_USER:=sims_backup}"
: "${BACKUP_DIR:=/backups}"
: "${BACKUP_RETENTION_DAYS:=14}"
: "${BACKUP_ENCRYPTION_KEY:?BACKUP_ENCRYPTION_KEY is required}"
: "${MYSQL_BACKUP_PASSWORD:?MYSQL_BACKUP_PASSWORD is required}"
[[ "$BACKUP_RETENTION_DAYS" =~ ^[0-9]+$ ]] || { echo "BACKUP_RETENTION_DAYS must be a nonnegative integer" >&2; exit 1; }
[ "${#BACKUP_ENCRYPTION_KEY}" -ge 32 ] || { echo "BACKUP_ENCRYPTION_KEY must contain at least 32 characters" >&2; exit 1; }
mkdir -p "$BACKUP_DIR"

CNF=$(mktemp /tmp/backup.XXXXXX.cnf)
printf '[client]\nuser=%s\npassword=%s\nhost=%s\nssl-mode=%s\n' "$MYSQL_BACKUP_USER" "$MYSQL_BACKUP_PASSWORD" "$MYSQL_HOST" "${MYSQL_SSL_MODE:-REQUIRED}" > "$CNF"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="$BACKUP_DIR/sims-$stamp.sql.gz.enc"
tmp="$out.partial"
trap 'rm -f "$CNF" "$tmp" "$tmp.hmac" "$tmp.sha256"' EXIT

# No --databases: the dump restores into any database name (the restore check uses a scratch one).
mysqldump --defaults-extra-file="$CNF" --single-transaction --quick --no-tablespaces --triggers \
    --set-gtid-purged=OFF --column-statistics=0 sims \
  | gzip -6 \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BACKUP_ENCRYPTION_KEY -out "$tmp"
# Encrypt-then-MAC: tampering or truncation is detected before anything is decrypted.
openssl dgst -sha256 -hmac "$BACKUP_ENCRYPTION_KEY" -r "$tmp" | cut -d' ' -f1 > "$tmp.hmac"
sha256sum "$tmp" | cut -d' ' -f1 > "$tmp.sha256"
# Publish the ciphertext last: the restore checker sees only complete backup sets.
mv "$tmp.hmac" "$out.hmac"
mv "$tmp.sha256" "$out.sha256"
mv "$tmp" "$out"
rm -f "$CNF"

size=$(wc -c < "$out")
echo "{\"event\":\"backup.created\",\"file\":\"$(basename "$out")\",\"bytes\":$size}"

# Retention
find "$BACKUP_DIR" -name 'sims-*.sql.gz.enc*' -type f -mtime +"$BACKUP_RETENTION_DAYS" -print -delete \
  | sed 's/^/{"event":"backup.expired","file":"/; s/$/"}/'
