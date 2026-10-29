#!/bin/sh
# Nightly PostgreSQL backup with rotation. Runs inside the `backup` service (infra/docker-compose.yml),
# or by hand:  docker compose -f infra/docker-compose.yml exec backup /backup.sh
# Keeps BACKUP_KEEP_DAYS daily dumps (default 14) in /backups (the `backups` volume).
set -eu
: "${PGHOST:=postgres}" "${PGUSER:=erp}" "${PGDATABASE:=erp}" "${BACKUP_KEEP_DAYS:=14}"
stamp=$(date -u +%Y-%m-%dT%H%M%SZ)
file="/backups/erp_${stamp}.dump"
pg_dump --format=custom --no-owner --file="${file}.partial" "${PGDATABASE}"
mv "${file}.partial" "${file}"
# Quick integrity check: the archive's table of contents must be readable.
pg_restore --list "${file}" > /dev/null
echo "backup ok: ${file} ($(du -h "${file}" | cut -f1))"
find /backups -name 'erp_*.dump' -mtime +"${BACKUP_KEEP_DAYS}" -delete
