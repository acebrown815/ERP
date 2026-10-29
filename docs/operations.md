# Operations runbook

For whoever runs the ERP server. The stack is one VM with Docker Compose (`infra/docker-compose.yml`):

| Service | What it does |
|---|---|
| `postgres` | PostgreSQL 16, data in the `pgdata` volume |
| `migrate` | Runs database migrations on every start, then exits |
| `api` | FastAPI on port 8000 (internal) |
| `worker` | Outbox events; calendar reminders every minute; nightly consistency checks |
| `web` | Next.js on port 3000 (internal) |
| `caddy` | HTTPS for `ERP_DOMAIN`; `/api/*` to the API, everything else to the web app |
| `backup` | Daily `pg_dump` into the `backups` volume, kept `BACKUP_KEEP_DAYS` days |

## First install

```bash
cp .env.example .env            # set POSTGRES_PASSWORD (long, random), ERP_DOMAIN, ERP_ENV=prod
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
docker compose -f infra/docker-compose.yml exec api python -m app.cli seed --company "Your Company"
docker compose -f infra/docker-compose.yml exec -e ERP_ADMIN_PASSWORD='…' api python -m app.cli create-admin --email you@company.com
```

Then sign in, and follow the [admin guide](admin-guide.md) to set up the company.

## Upgrading

```bash
git pull
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
```

`migrate` applies new migrations before `api` and `worker` start. If a migration fails, the API does not start; the error is in `docker compose logs migrate`. A backup is taken automatically at start-up by the `backup` service, but take one by hand before any upgrade (below).

## Health and monitoring

| Check | Use |
|---|---|
| `GET /api/health` | Liveness: the API answers and reaches the database |
| `GET /api/health/ready` | Readiness: also checks that the schema is at the latest migration (HTTP 503 if not). Docker's health check uses this |
| **Settings → System Checks** | Ledger debits = credits, balance sheet balances, revenue splits match receipts, salary records match salary payments and employee expenses, audit log untampered, worker keeping up |
| Nightly checks | The worker runs the same checks after 02:00. Any failure notifies administrators in the app (bell icon) and is logged as `check.result ok=false` |
| Logs | `docker compose -f infra/docker-compose.yml logs -f api worker`. With `ERP_LOG_JSON=true` (the default in compose) lines are JSON with a request id, so they can be shipped to any log service |

External monitoring: point an uptime checker at `https://<ERP_DOMAIN>/api/health/ready` (expect 200), and alert on `check.result` warnings in the worker log.

## Backups

The `backup` service writes `erp_<UTC timestamp>.dump` (PostgreSQL custom format) daily at `BACKUP_HOUR` (UTC) and once at start-up, checks that each dump is readable, and deletes dumps older than `BACKUP_KEEP_DAYS`.

Take one now:

```bash
docker compose -f infra/docker-compose.yml exec backup /backup.sh
```

**Copy backups off the server.** The volume is on the same disk as the database. For example, every night:

```bash
docker run --rm -v erp_backups:/b -v /mnt/offsite:/o alpine sh -c 'cp -n /b/*.dump /o/'
```

(or `rclone`/`aws s3 sync` from the volume path). Uploaded files (attachments) live in the `attachments` volume; back that up the same way.

## Restore drill (do it monthly)

Restore the latest dump into a scratch database and look at the counts. Production is not touched:

```bash
docker compose -f infra/docker-compose.yml exec backup sh -c 'ls -1t /backups | head -3'
docker compose -f infra/docker-compose.yml exec backup /restore.sh /backups/erp_<stamp>.dump      # into "erp_restore"
```

It prints the schema version and the number of journal lines and payments. Compare with the live system (Trial Balance, Payment Entries). Then drop the scratch database:

```bash
docker compose -f infra/docker-compose.yml exec backup psql -d postgres -c 'DROP DATABASE erp_restore;'
```

## Restoring production (after data loss)

1. `docker compose -f infra/docker-compose.yml stop api worker web`
2. `docker compose -f infra/docker-compose.yml exec backup /restore.sh /backups/erp_<stamp>.dump erp`
3. `docker compose -f infra/docker-compose.yml start api worker web`
4. Sign in, open **Settings → System Checks**, and confirm everything passes.

Anything entered after the dump's time must be re-entered.

## Security notes

- Secrets live only in `.env` (never committed). Rotate `POSTGRES_PASSWORD` by changing it in `.env` and in PostgreSQL (`ALTER USER erp PASSWORD '…'`), then restarting.
- Passwords are hashed with Argon2id. Sign-in is locked for 15 minutes after 5 failures. Sessions are server-side, cookies are `HttpOnly`, `Secure` (prod) and `SameSite=Lax`, and changes need a CSRF token.
- HTTPS and security headers come from Caddy (HSTS, `nosniff`, `X-Frame-Options: DENY`, referrer and permissions policies). The API and web app send them too, and the web app sets a same-origin Content-Security-Policy.
- Every change to money, salary, categories and settings is in the audit log (Settings → Audit Log). The log is hash-chained and verified nightly.
- Dependencies: `npm audit --omit=dev` (web) and `pip-audit` (API) were clean on 2026-10-29. Re-run them before each upgrade.
- Only Administrators can reopen closed salary periods, change the salary cycle, manage formulas and roles.

## Performance

`python tools/loadtest/loadtest.py --base https://<domain> --email … --password …` signs in and reads the busiest pages concurrently (read-only). On the development machine (300 requests, 10 at a time): p50 132 ms, p95 905 ms. The company dashboard is the slowest page (~0.9 s) because it recalculates every open salary period. Everything else is ~100–450 ms.

## Troubleshooting

| Symptom | Look at |
|---|---|
| "Background worker" check fails | `docker compose … ps worker` / `logs worker`. Reminders and checks stop while it is down; nothing is lost, it catches up |
| API unhealthy after an upgrade | `docker compose … logs migrate` |
| A receipt can't be cancelled ("salary period … is closed") | Intended: an administrator reopens the salary period first (Salary board) |
| Balance sheet check fails | Do not edit data by hand. The ledger refuses unbalanced entries, so this points to a data import or manual SQL; restore or contact the developer |
