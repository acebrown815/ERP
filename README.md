# ERP

Web-based ERP for a software services company: double-entry accounting, payments, employee revenue attribution, salary, projects and calendars.

- Design: [docs/architecture.md](docs/architecture.md)
- Running it: [docs/operations.md](docs/operations.md) (servers, backups, monitoring) · [docs/admin-guide.md](docs/admin-guide.md) (setup and month-end)

```
apps/api     FastAPI modular monolith (Python, SQLAlchemy, Alembic, PostgreSQL)
apps/web     Next.js app (React, TypeScript, Tailwind, TanStack Query/Table)
infra        Docker Compose, Caddy
tools/devdb  Local PostgreSQL 16 for machines without Docker
docs         Architecture and phase notes
```

## Local development

Requirements: Python 3.12+, Node 22+. PostgreSQL 16 is either Docker or `tools/devdb`.

**1. Database** (no Docker needed; data lives in `tools/devdb/data`)

```bash
cd tools/devdb && npm install && npm start      # postgresql://erp:erp@127.0.0.1:54329/erp (+ erp_test)
```

**2. API** (http://127.0.0.1:8000, docs at /api/docs)

```bash
cd apps/api
python -m venv .venv && .venv/Scripts/activate   # Windows (macOS/Linux: source .venv/bin/activate)
pip install -e ".[dev]"
python -m app.cli migrate
python -m app.cli seed --company "Your Company"
ERP_ADMIN_PASSWORD='choose-a-strong-one' python -m app.cli create-admin --email you@example.com --name "Your Name"
python -m app.cli demo                           # optional demo users (password Demo-Pass-2026), sample data, salary formula
uvicorn app.main:app --reload --port 8000
python -m app.worker                             # background worker: outbox, reminders, nightly checks (separate terminal)
```

**3. Web** (http://localhost:3000, proxies `/api` to the API)

```bash
cd apps/web
npm install
npm run dev
npm run gen:api          # regenerate src/types/api.ts after API changes (API must be running)
```

**Running them day to day:** once the steps above are done, `tools/dev.py` runs everything in the background, with logs in `.dev/`. Use `py` on Windows, or `python3`.

```bash
py tools/dev.py start            # database, API, worker and web (or name one: db, api, worker, web)
py tools/dev.py status           # what is running, and how much memory it uses
py tools/dev.py restart web      # stop and start again; also finds servers started by hand
py tools/dev.py logs api         # the last lines of a log
py tools/dev.py stop             # everything but the database (`stop db` stops that too)
```

Restart `api` after changing API code: it runs without `--reload`, which hangs on Windows when the server has no terminal of its own. Restart `web` when `status` warns about its memory: `next dev` keeps what each rebuild uses, and pages get slow long before it runs out.

## Tests and checks

```bash
cd apps/api && pytest -q                         # needs the dev database (erp_test) running
ruff check app tests migrations && ruff format --check app tests migrations
mypy app
alembic check                                    # migrations match models

cd apps/web && npm run typecheck && npm run lint && npm test && npm run build
npx playwright install chromium                  # once
npm run test:e2e                                 # browser tests; needs the dev database, and web stopped (it rebuilds .next)
```

API tests use a real PostgreSQL database because triggers and constraints are part of the design. Point them elsewhere with `ERP_TEST_DATABASE_URL`.

Browser tests (`apps/web/e2e`) start their own API and a production build of the web app on ports 8100 and 3100, against a database `erp_e2e` that they delete and rebuild on every run. Point them elsewhere with `E2E_DATABASE_URL`; the name must end in `_e2e`.

## Deployment (Docker Compose)

```bash
cp .env.example .env          # set POSTGRES_PASSWORD; ERP_DOMAIN is chonryong.com
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
docker compose -f infra/docker-compose.yml --env-file .env exec api python -m app.cli seed --company "ChonRyong Inc"
openssl rand -base64 24       # administrator password; keep it in a password manager
docker compose -f infra/docker-compose.yml --env-file .env exec api python -m app.cli create-admin --email admin@chonryong.com --name "Administrator"   # prompts for it
```

Caddy terminates TLS for `ERP_DOMAIN` (www redirects to it) and routes `/api` to the API and everything else to the web app. Migrations and the seed run automatically on start (`migrate` service); the seed is skipped until a first install has been seeded by hand with its company name.

Pushes to `main` that pass CI are deployed to the server by GitHub Actions, which runs [infra/deploy.sh](infra/deploy.sh) over SSH; the images are built on the server. Server sizing and setup: [docs/operations.md](docs/operations.md).
