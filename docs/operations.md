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

## Server

One VPS runs everything, and the images are built on it.

| | Minimum | Recommended |
|---|---|---|
| CPU | 2 vCPU | 2 vCPU |
| RAM | 2 GB + 4 GB swap | 4 GB (+ swap) |
| Disk | 30 GB SSD | 50 GB+ SSD |

The stack uses about 1 GB of RAM when running; the Next.js build briefly needs another 1.5–2 GB, which is why a 2 GB server needs swap. Ubuntu 22.04 or 24.04 (20.04 also works but is out of standard support).

The ERP is served at **https://chonryong.com**; `www.chonryong.com` redirects to it. Before the first install, add two DNS A records pointing at the server's IP (Caddy needs both to get the certificates):

| Name | Type | Value |
|---|---|---|
| `@` (chonryong.com) | A | VPS IPv4 |
| `www` | A | VPS IPv4 |

Then as root:

```bash
apt update && apt upgrade -y
adduser deploy && usermod -aG sudo deploy
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw enable

fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

curl -fsSL https://get.docker.com | sh
usermod -aG docker deploy
cat > /etc/docker/daemon.json <<'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "20m", "max-file": "5" } }
EOF
systemctl restart docker
```

Only Caddy publishes ports (80, 443); PostgreSQL, the API and the web app are reachable only on Docker's internal network.

## First install

As `deploy` (the GitHub deploy key is set up in [Continuous deployment](#continuous-deployment)):

```bash
git clone git@github.com:acebrown815/ERP.git ~/erp && cd ~/erp
cp .env.example .env            # set POSTGRES_PASSWORD (openssl rand -hex 32; hex, as it goes into the database URL); ERP_DOMAIN is chonryong.com
chmod 600 .env
bash infra/deploy.sh
docker compose -f infra/docker-compose.yml --env-file .env exec api python -m app.cli seed --company "ChonRyong Inc"

openssl rand -base64 24         # the administrator password: save it in a password manager now
docker compose -f infra/docker-compose.yml --env-file .env exec api python -m app.cli create-admin --email admin@chonryong.com --name "Administrator"
```

`create-admin` asks for the password at a hidden prompt; paste the generated one. Don't pass it with `-e ERP_ADMIN_PASSWORD=…` on the server, where it would stay in the shell history.

Always pass `--env-file .env`: Compose otherwise looks for `.env` next to the compose file (`infra/`), and warns that `POSTGRES_PASSWORD` is not set. A shortcut for the server:

```bash
echo "alias dc='docker compose -f infra/docker-compose.yml --env-file .env'" >> ~/.bashrc   # then: dc ps, dc logs -f api
```

Then sign in at https://chonryong.com, and follow the [admin guide](admin-guide.md) to set up the company.

## Upgrading

Pushes to `main` deploy automatically (next section). By hand, on the server:

```bash
bash infra/deploy.sh             # latest origin/main; or: bash infra/deploy.sh <commit sha>
```

[`infra/deploy.sh`](../infra/deploy.sh) fetches the commit and resets the checkout to it (do not edit tracked files on the server; `.env` and the volumes are not touched), builds the images, takes a backup, restarts the stack, waits until the API is healthy and the other services are running, then prunes old images. If the build fails, the running version stays up. `migrate` applies new migrations before `api` and `worker` start; if a migration fails, the API does not start, the deploy fails and prints `docker compose logs migrate`.

To roll back, deploy the previous commit: `bash infra/deploy.sh <older sha>`. Migrations are not reversed, so if the bad release changed the schema, restore the pre-deploy backup instead (see [Restoring production](#restoring-production-after-data-loss)).

## Continuous deployment

`.github/workflows/ci.yml` runs the API and web checks on every push and pull request. On a push to `main` where both pass, the `deploy` job connects to the server over SSH and runs `infra/deploy.sh <sha>`. Deploys run one at a time.

One-time setup:

1. **Server → GitHub (to fetch the code).** On the server, as `deploy`:
   ```bash
   ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519 -C erp-server
   cat ~/.ssh/id_ed25519.pub
   ```
   In GitHub: [acebrown815/ERP → Settings → Deploy keys](https://github.com/acebrown815/ERP/settings/keys) → **Add deploy key**, paste it, leave "Allow write access" off. Then `ssh -T git@github.com` on the server to accept GitHub's host key, and clone (First install).
2. **GitHub → server (to run the deploy).** On your own machine:
   ```bash
   ssh-keygen -t ed25519 -N '' -f erp-actions -C github-actions
   ```
   Append `erp-actions.pub` to `/home/deploy/.ssh/authorized_keys` on the server, restricted to deploying:
   ```
   restrict,command="bash /home/deploy/erp/infra/deploy.sh" ssh-ed25519 AAAA… github-actions
   ```
   The forced command is required: the workflow sends only the commit sha, which arrives in the script as `SSH_ORIGINAL_COMMAND`, and the key can do nothing but deploy. Adjust the path if you cloned elsewhere.
3. **Host key.** On your machine: `ssh-keyscan -p 22 <server>` and keep the output.
4. **GitHub settings.** [acebrown815/ERP → Settings → Environments](https://github.com/acebrown815/ERP/settings/environments) → **New environment** `production` (optionally add required reviewers so each deploy waits for approval). In that environment add:

   | Kind | Name | Value |
   |---|---|---|
   | Secret | `DEPLOY_SSH_KEY` | Contents of the private key `erp-actions` |
   | Secret | `DEPLOY_KNOWN_HOSTS` | Output of `ssh-keyscan` |
   | Variable | `DEPLOY_HOST` | Server IP or host name |
   | Variable | `DEPLOY_USER` | `deploy` |
   | Variable | `DEPLOY_PORT` | SSH port (optional, default 22) |

   Then delete `erp-actions` from your machine.

Deploy output is in the Actions run log. A failed deploy marks the run red and leaves the old containers running if the build failed, or prints the failing service's log if start-up failed.

## Health and monitoring

| Check | Use |
|---|---|
| `GET /api/health` | Liveness: the API answers and reaches the database |
| `GET /api/health/ready` | Readiness: also checks that the schema is at the latest migration (HTTP 503 if not). Docker's health check uses this |
| **Settings → System Checks** | Ledger debits = credits, balance sheet balances, revenue splits match receipts, salary records match salary payments and employee expenses, audit log untampered, worker keeping up |
| Nightly checks | The worker runs the same checks after 02:00. Any failure notifies administrators in the app (bell icon) and is logged as `check.result ok=false` |
| Logs | `docker compose -f infra/docker-compose.yml --env-file .env logs -f api worker`. With `ERP_LOG_JSON=true` (the default in compose) lines are JSON with a request id, so they can be shipped to any log service |

External monitoring: point an uptime checker at `https://chonryong.com/api/health/ready` (expect 200), and alert on `check.result` warnings in the worker log.

## Backups

The `backup` service writes `erp_<UTC timestamp>.dump` (PostgreSQL custom format) daily at `BACKUP_HOUR` (UTC) and once at start-up, checks that each dump is readable, and deletes dumps older than `BACKUP_KEEP_DAYS`.

Take one now:

```bash
docker compose -f infra/docker-compose.yml --env-file .env exec backup sh /backup.sh
```

**Copy backups off the server.** The volume is on the same disk as the database. For example, every night:

```bash
docker run --rm -v erp_backups:/b -v /mnt/offsite:/o alpine sh -c 'cp -n /b/*.dump /o/'
```

(or `rclone`/`aws s3 sync` from the volume path). Uploaded files (attachments) live in the `attachments` volume; back that up the same way.

## Restore drill (do it monthly)

Restore the latest dump into a scratch database and look at the counts. Production is not touched:

```bash
docker compose -f infra/docker-compose.yml --env-file .env exec backup sh -c 'ls -1t /backups | head -3'
docker compose -f infra/docker-compose.yml --env-file .env exec backup sh /restore.sh /backups/erp_<stamp>.dump      # into "erp_restore"
```

It prints the schema version and the number of journal lines and payments. Compare with the live system (Trial Balance, Payment Entries). Then drop the scratch database:

```bash
docker compose -f infra/docker-compose.yml --env-file .env exec backup psql -d postgres -c 'DROP DATABASE erp_restore;'
```

## Restoring production (after data loss)

1. `docker compose -f infra/docker-compose.yml --env-file .env stop api worker web`
2. `docker compose -f infra/docker-compose.yml --env-file .env exec backup sh /restore.sh /backups/erp_<stamp>.dump erp`
3. `docker compose -f infra/docker-compose.yml --env-file .env start api worker web`
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

`python tools/loadtest/loadtest.py --base https://chonryong.com --email … --password …` signs in and reads the busiest pages concurrently (read-only). On the development machine (300 requests, 10 at a time): p50 132 ms, p95 905 ms. The company dashboard is the slowest page (~0.9 s) because it recalculates every open salary period. Everything else is ~100–450 ms.

## Troubleshooting

| Symptom | Look at |
|---|---|
| "Background worker" check fails | `docker compose … ps worker` / `logs worker`. Reminders and checks stop while it is down; nothing is lost, it catches up |
| API unhealthy after an upgrade | `docker compose … logs migrate` |
| A receipt can't be cancelled ("salary period … is closed") | Intended: an administrator reopens the salary period first (Salary board) |
| Balance sheet check fails | Do not edit data by hand. The ledger refuses unbalanced entries, so this points to a data import or manual SQL; restore or contact the developer |
