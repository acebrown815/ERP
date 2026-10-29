#!/bin/sh
# Runs backup.sh once a day at BACKUP_HOUR (UTC, default 01) and once at start-up.
set -eu
: "${BACKUP_HOUR:=01}"
/backup.sh || echo "backup failed" >&2
while true; do
  now=$(date -u +%H%M)
  if [ "${now}" = "${BACKUP_HOUR}00" ]; then
    /backup.sh || echo "backup failed" >&2
    sleep 70
  fi
  sleep 30
done
