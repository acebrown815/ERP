# Phase 1 — Foundation: completion note

Date: 2026-10-27 · Status: **done, pending your review**

## Scope delivered

| Area | What exists |
|---|---|
| Repository | `apps/api`, `apps/web`, `infra`, `tools/devdb`, CI workflow (`.github/workflows/ci.yml`) |
| Database | Alembic migration `0001_foundation`: users, sessions, identities (for Google later), roles, grants, audit log, company settings, currencies, exchange rates, categories, attachments, idempotency keys, number series, outbox. Extensions `ltree` and `btree_gist` enabled for Phase 2 |
| Authentication | Email + password (Argon2id), Postgres-backed sessions (hashed tokens, 12 h idle / 7 day absolute), CSRF token per session, lockout after 5 failures for 15 min, change password (signs out other sessions), admin password reset, logout / logout-everywhere |
| Authorization | Code-defined permission registry (all phases), roles with per-permission scope (own / project / all), 4 default roles from the design, `require(permission)` on every endpoint, can't change own roles or deactivate self, last-admin protection |
| Audit log | Append-only (database trigger), SHA-256 hash chain with a verify endpoint, request id and IP on every row, before/after diffs, money stored as strings |
| Company settings | Name and contact details, base currency (USD, lockable), time zone, fiscal year start, **salary cycle start day (1–28)**, eligible-revenue policy (net of company-paid fees by default) |
| Currencies & rates | 12 seeded currencies incl. BTC, ETH, USDT, USDC; add/deactivate; dated exchange rates with on-or-before lookup and automatic inverse |
| Custom categories | 11 groups, each seeded with built-in values and a protected "Other"; sub-categories, per-group settings, rename, move, deactivate, merge/unmerge (history never rewritten), delete only if unreferenced, per-domain permissions, shared `validate_choice` rule for "Other" requiring a description |
| Shared services | Decimal money helpers with exact largest-remainder splitting, UUIDv7 ids, document number series, Idempotency-Key handling, transactional outbox + worker, attachments (type allowlist, 25 MB limit, SHA-256, soft delete, per-record permission hooks), problem+json errors |
| Web app | Login, app shell (role-aware sidebar with later-phase items marked P2–P5, mobile drawer, dark mode, user menu), dashboard, Settings: Company (with live salary-period preview), Users, Roles & Permissions matrix, Custom Categories (tree + reusable `CategorySelect` picker preview), Currencies & Rates, Audit Log (diffs + integrity check) |
| Infra | Dockerfiles, Compose (postgres, migrate, api, worker, web, caddy), Caddyfile, `.env.example` |

## Verification

| Check | Result |
|---|---|
| API tests (`pytest`, real PostgreSQL 16) | **80 passed** |
| Lint / format (`ruff`) | clean |
| Migration upgrade → downgrade → upgrade, `alembic check` | clean, no drift |
| Web typecheck, ESLint, unit tests (salary-cycle periods) | clean, 7 passed |
| `next build` (production) | succeeds |
| HTTP smoke test through the web app | redirect to login, login via `/api` proxy, permission checks (Project Manager: 403 on users and finance categories, 201 on project types), security headers |

**Not verified yet:**
- The UI was not checked in a browser in this session; there was no browser tool available. Please click through it once.
- The Docker images and Compose stack were written but not built here, because Docker isn't installed on this machine.

## Decisions made during implementation

1. **Sessions are stored in Postgres, not Redis.** One less service to run, and sessions are revocable with a plain `UPDATE`. Redis will be added when a feature needs it.
2. **The worker polls the outbox table** instead of using `arq`, so Phase 1 runs on Postgres alone.
3. **Module boundaries are enforced by a test** (`tests/test_architecture.py`) instead of `import-linter`. The test is simpler and checks exactly the rule "import other modules only via `api.py`".
4. **The salary cycle start day is editable in Company settings for now.** No salary periods exist yet, so changing it is harmless. Phase 3 moves it to its own endpoint with the transition-period preview.
5. **Local database without Docker**: `tools/devdb` runs the official PostgreSQL 16 binaries from npm.

## How to try it

See the [README](../README.md). On this machine the dev database, the API (port 8000) and the web app (port 3000) are already set up and seeded:

| User | Password | Role |
|---|---|---|
| admin@example.com | Admin-Pass-2026 | Administrator |
| finance@example.com | Demo-Pass-2026 | Finance Manager |
| pm@example.com | Demo-Pass-2026 | Project Manager |
| alice@example.com, bob@example.com | Demo-Pass-2026 | Employee |

These are local demo credentials only. Change them, or don't create them, anywhere real.

## Next: Phase 2 — Accounting & Payments

Chart of Accounts, periods, posting engine with database-level invariants, journal entries and reversals, opening balances, parties, payment methods and accounts, Payment Entries (receive, pay, transfer, fees, FX, cancel/amend), basic employees and projects, the 100% employee split on receipts, CSV import, and GL / Trial Balance / P&L / Balance Sheet reports.
