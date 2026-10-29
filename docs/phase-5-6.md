# Phases 5 & 6 — Calendar, Reporting, Production readiness: completion note

Date: 2026-10-29 · Branch: `phase-5-6` · Status: **done, merged into `main`**

## Phase 5: Calendar & Reporting

| Area | What exists |
|---|---|
| Calendars | **My calendar** (my meetings and leave, my team's and projects' events, company events, my tasks, project milestones and deadlines), **Team calendar** (a department or a project team), **Company calendar** (company events, approved leave, milestones, deadlines). Month, week (hour grid) and agenda views |
| Events | Personal, team, project or company scope; all-day or timed; location, attendees with accept/decline; types and colours from Custom Categories |
| Recurrence | Daily / weekly (chosen days) / monthly / yearly, ending never, on a date or after N times (RFC 5545). Repeats keep their local time across daylight-saving changes. One occurrence can be skipped |
| Time zones | Timed events are stored in UTC plus the zone they were created in; all-day items are plain dates |
| Leave | "Request leave": approvers (Administrators everywhere, Project Managers for their teams) approve or reject; the employee is notified. Approved leave shows company-wide and sets capacity to 0. Moving approved leave sends it back for approval |
| Derived items | Tasks, milestones and project deadlines are read live from Projects, never copied, so a date changed on the board or Gantt shows at once |
| Workload | Per person per day for a department or project team: capacity (8 h weekdays, 0 on leave) vs meetings + remaining task estimates spread over each task's working days. Heat strip |
| Reminders | In-app notifications (bell icon): event reminders (at start, 5/15/30/60 min, 1 day before) and a "due today" note for tasks; each sent once |
| Dashboard | Company figures for the current salary month: cash (at today's rates), income, expenses incl. salary, profit, salary owed, salary this month, tasks overdue / due this week, active projects and those needing attention (past deadline, over budget, overdue tasks, losing money), milestones and deadlines in the next 2 weeks. Everyone also sees **This week** (their tasks due and events) |
| Reports | **Monthly Summary** (per salary month: income, expenses, salary paid, profit, salary earned, with a chart), **Income & Expenses by Category**, **Customer & Supplier Payments**, plus the existing statements, ledger, project financials and salary reports |
| Exports | Every report and list export as **CSV** (exact decimals), **Excel** (.xlsx, formatted numbers) or **PDF**, with the same columns and totals as on screen |

## Phase 6: Production readiness

| Area | What exists |
|---|---|
| Consistency checks | **Settings → System Checks**: ledger debits = credits, balance sheet balances, revenue splits match receipts, salary records match salary payments and employee expenses, audit log untampered, background worker keeping up. Also run nightly by the worker; failures notify administrators |
| Health | `/api/health` (live) and `/api/health/ready` (database reachable and schema at the latest migration; 503 otherwise), used by Docker's health check |
| Backups | `backup` service: daily `pg_dump` with integrity check and rotation; `restore.sh` restores into a scratch database for drills or over production after a loss (docs/operations.md) |
| Security | Security headers on the API, web app (incl. Content-Security-Policy) and Caddy; API responses not cached. Dependency audit: npm 3 → **0** (Zod 4, patched PostCSS inside Next.js), Python 0 |
| Performance | Load test script (`tools/loadtest`). Payment list 530 → 128 ms by loading names and splits in bulk; salary cost per project computed per period instead of per employee |
| Docs | [Operations runbook](operations.md) (install, upgrade, monitoring, backups, restore drill, security, troubleshooting) and [Administrator guide](admin-guide.md) (setup order, daily, month-end, roles). API reference at `/api/docs` |

## Verification

| Check | Result |
|---|---|
| API tests (real PostgreSQL 16) | **185 passed** (5 new groups for Phases 5–6) |
| Lint / format, `alembic check` | clean, no drift |
| Web typecheck, ESLint, unit tests | clean, 14 passed |
| `next build` | succeeds |
| Dev database | all new pages and endpoints return 200; Excel and PDF exports download; all 6 system checks pass (after starting the worker, see below) |
| Load test (300 requests, 10 concurrent) | 0 errors, p50 132 ms, p95 905 ms; dashboard ~0.9 s, everything else 90–450 ms |

The tests cover:
- A weekly meeting staying at 09:00 local time across the October clock change.
- Yearly all-day events.
- Invitees seeing a meeting and other people not seeing a private appointment.
- Skipping one occurrence.
- Employees blocked from company events.
- Reminders sent exactly once.
- Leave request → approval → notification → company and team views → capacity 0.
- A task's hours spread over its working days.
- Income by category, customer payments, monthly summary, the Excel and PDF formats, and the dashboard.
- Every system check passing.
- Readiness and the security headers.

## Found while checking

- **The background worker wasn't running** in this development setup, so 114 events were waiting (the "Background worker" check failed). It now runs alongside the API (`python -m app.worker`). In production it's the `worker` service.
- **Your dev data shows negative assets (−4,077.49):** more expenses than receipts have been recorded so far, and there are no opening balances. The books are consistent (the balance sheet balances), but enter opening balances (Accounting → Journal Entries → Opening balances) to reflect real starting cash.

## Not done / decisions

1. **Google sign-in** was optional ("if wanted by then"); not added.
2. **The backup scripts weren't run here**: this machine has no `pg_dump`. They run in the `postgres:16-alpine` container in production; do the restore drill once after deploying.
3. **No external alerting service:** health endpoints, JSON logs and in-app notifications are in place to connect to one.
4. **Email reminders** aren't sent; reminders are in-app only.
5. **The screens haven't been clicked through in a browser** (no browser tool in this session).
