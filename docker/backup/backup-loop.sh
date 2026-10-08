#!/bin/bash
# Scheduler for the backup container: back up, verify by restoring, sleep, repeat.
set -u
: "${BACKUP_INTERVAL_SECONDS:=86400}"
: "${BACKUP_DIR:=/backups}"
if ! { [[ "$BACKUP_INTERVAL_SECONDS" =~ ^[0-9]+$ ]] && [ "$BACKUP_INTERVAL_SECONDS" -ge 60 ]; }; then
  echo "BACKUP_INTERVAL_SECONDS must be an integer of at least 60" >&2
  exit 1
fi
DIR=$(dirname "$0")

trap 'echo "{\"event\":\"backup.stopping\"}"; exit 0' TERM INT

# Wait for the database to accept connections
until mysqladmin ping -h "${MYSQL_HOST:-mysql}" --silent > /dev/null 2>&1; do sleep 3; done

while true; do
  if bash "$DIR/backup.sh" && bash "$DIR/restore-check.sh"; then
    date +%s > "$BACKUP_DIR/.last-success.tmp"
    mv "$BACKUP_DIR/.last-success.tmp" "$BACKUP_DIR/.last-success"
  else
    echo '{"event":"backup.failed"}' >&2
  fi
  sleep "$BACKUP_INTERVAL_SECONDS" &
  wait $!
done
