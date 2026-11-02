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

## Tests and checks

```bash
cd apps/api && pytest -q                         # needs the dev database (erp_test) running
ruff check app tests migrations && ruff format --check app tests migrations
alembic check                                    # migrations match models

cd apps/web && npm run typecheck && npm run lint && npm test && npm run build
```

API tests use a real PostgreSQL database because triggers and constraints are part of the design. Point them elsewhere with `ERP_TEST_DATABASE_URL`.

## Deployment (Docker Compose)

```bash
cp .env.example .env          # set POSTGRES_PASSWORD and ERP_DOMAIN
docker compose -f infra/docker-compose.yml --env-file .env up -d --build
docker compose -f infra/docker-compose.yml exec api python -m app.cli seed --company "Your Company"
docker compose -f infra/docker-compose.yml exec -e ERP_ADMIN_PASSWORD='...' api python -m app.cli create-admin --email you@company.com
```

Caddy terminates TLS for `ERP_DOMAIN` and routes `/api` to the API and everything else to the web app. Migrations run automatically on start (`migrate` service).

Pushes to `main` that pass CI are deployed to the server by GitHub Actions, which runs [infra/deploy.sh](infra/deploy.sh) over SSH; the images are built on the server. Server sizing and setup: [docs/operations.md](docs/operations.md).
