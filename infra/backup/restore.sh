#!/bin/sh
# Restore a dump into a database. DESTRUCTIVE for the target database.
#   docker compose -f infra/docker-compose.yml exec backup sh /restore.sh /backups/erp_<stamp>.dump [target_db]
# Default target is a scratch database "erp_restore" so you can check a backup without touching production
# (the restore drill in docs/operations.md). Restoring over "erp" requires stopping api and worker first.
set -eu
dump="${1:?usage: restore.sh <dump file> [target database]}"
target="${2:-erp_restore}"
: "${PGHOST:=postgres}" "${PGUSER:=erp}"
psql -v ON_ERROR_STOP=1 -d postgres -c "DROP DATABASE IF EXISTS \"${target}\";" -c "CREATE DATABASE \"${target}\";"
pg_restore --no-owner --exit-on-error --dbname="${target}" "${dump}"
psql -d "${target}" -At -c "SELECT 'schema ' || version_num FROM alembic_version;"      -c "SELECT 'journal lines ' || count(*) FROM journal_lines;"      -c "SELECT 'payments ' || count(*) FROM payment_entries;"
echo "restored ${dump} into ${target}"
