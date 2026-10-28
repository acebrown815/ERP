# Phase 4 — Projects: completion note

Date: 2026-10-28 · Branch: `phase-4-projects` · Status: **done, merged into `main`**

## Scope delivered

| Area | What exists |
|---|---|
| Projects | Budget, priority, manual completion % (otherwise calculated from tasks), milestones (planned / in progress / done / cancelled). Project page with Overview, Tasks, Board, Timeline and Financials tabs |
| Tasks | Numbered tasks (TSK-…) with subtasks, milestone, category, status (backlog → to do → in progress → review → done), priority, start/due dates, estimate, several assignees. "Done" is time-stamped |
| Dependencies | Finish-to-start, same project only, cycles refused ("TSK-3 already waits for TSK-1") |
| Kanban | One board per project: drag cards between columns and within a column. A move rewrites only the moved card (lexicographic rank), with a version check so two people dragging at once don't overwrite each other |
| Gantt | Bars from start to due with progress fill, drag to move, drag the edges to change dates, dependency arrows (red when a task ends after the one waiting for it starts), milestones, today line, deadline line, day / week / month zoom. Board and timeline read the same rows |
| Time tracking | Hours per task, employee and day (max 24 h per person per day). Progress on the timeline = time logged ÷ estimate until the task is done |
| Comments | On every task, by anyone who can see the project |
| My tasks | Tasks across projects: assigned to me (default) or all I can see, open first, soonest due first. **New task** there asks for the project |
| Project financials | From the ledger (design §11.1): revenue received, direct expenses, salary paid, salary earned but not paid, profit (cash) and profit after salary owed, margin, budget used / left, contract value still to receive, task progress and hours. Per project and as a profitability report (CSV too) |
| Salary cost per project | A salary payment's expense line is split across the projects the employee earned revenue on in the period it pays, in proportion to that revenue (design §10.4). With no revenue (fixed pay) it stays untagged overhead |

**Who can do what** (defaults, editable in Roles):
- **Administrators and Finance:** everything on all projects.
- **Project managers:** manage tasks and milestones on their projects.
- **Employees:** see projects they're on, move tasks assigned to them, log their own time and comment. They can't change other task details, and they don't see financials.

## Verification

| Check | Result |
|---|---|
| API tests (real PostgreSQL 16) | **180 passed** (5 new test groups for Phase 4) |
| Lint / format, `alembic check` | clean, no drift |
| Web typecheck, ESLint, unit tests | clean, 12 passed (incl. the board rank, shared with the server) |
| `next build` | succeeds |
| Pages and endpoints on the dev database | all return 200 |

The tests cover:
- Kanban ordering and stale moves.
- The assignee-only status change.
- Estimate-weighted progress (10 h of 41 h → 24.4%).
- A subtask can't become a task's own parent.
- Dependency cycles.
- Time-entry limits, and deleting a task blocked once time is logged.
- Comments.
- Timeline delay detection.
- Outsiders get 404.
- The Section 16 numbers through project financials: revenue 10,000, expenses 500, salary paid 626.67 (tagged to the project), salary owed 352.59, profit 8,873.33, profit after owed 8,520.74.

**Not verified:** the screens haven't been clicked through in a browser (no browser tool in this session). Drag-and-drop on the board and timeline in particular needs a manual try.

## Decisions made during implementation

1. **Comments belong to tasks** (`task_comments`), not a generic comments table. That's simpler, and nothing else needs comments yet.
2. **Assignees can change only the status** of their tasks (and log time). Everything else is for the project's managers.
3. **Salary cost per project uses the revenue of the period the payment pays** (the chosen period, else the oldest unpaid, else the current one). Payments recorded before Phase 4 keep their untagged salary line; the ledger is never rewritten.
4. **Salary owed per project** = each period's salary shared by the employee's revenue per project in that period, minus what was paid of it.
5. **Calendar items (Phase 5) will read tasks and milestones directly**; nothing is copied.

## Next: Phase 5 — Calendar & Reporting

Calendars (personal, team, company) with recurrence and time zones, leave and availability, workload, reminders; dashboards; remaining reports and exports.
