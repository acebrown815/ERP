# Phase 3 — Salary: completion note

Date: 2026-10-28 · Branch: `phase-3-salary` · Status: **done, merged into `main`**

## Scope delivered

| Area | What exists |
|---|---|
| Salary formulas | Named formulas with **versions from a date**. Rate curve (your rule), flat tiers, progressive tiers or no revenue share; fixed amount, revenue-threshold bonuses, minimum/maximum payout, rounding. Live preview: rate/salary chart and example table. The provisional rule is seeded as "Revenue Share (provisional)" |
| Assignments | Employee → formula over a date range, no overlaps (enforced by the database). "Switch formula" ends the previous one the day before |
| Salary cycle | Own settings screen: pick the start day (1–28), preview the next periods including any **transition period**, confirm. Periods are stored with explicit dates, contiguous, no overlaps (database constraint) |
| Salary statements | One per employee per period: revenue credited, formula and version, rate, breakdown, adjustments, calculated, paid, status. **Open periods are calculated live**, so a receipt or cancellation shows immediately |
| Adjustments | Bonus, deduction or correction with a reason, per employee per open period. Never capped by the formula's min/max |
| Close / reopen | Close a period after it ends (oldest first): statements are frozen and the formula versions used are locked. Receipts dated in a closed period can't be submitted or cancelled. An administrator reopens it with a reason (newest first); everything is audited |
| Salary payments | Payment Entry → Pay → Employee Salary (unchanged posting: Dr 5100 / Cr bank). The form now shows the employee's **salary balance**, offers "pay the full balance" and lets you pick the period it pays; otherwise it pays the **oldest unpaid period first**. Overpaying leaves a credit |
| Balances | Per employee: Σ calculated − Σ paid. Positive = owed, negative = paid ahead |
| Employee self-service | **My Salary** (read-only, own data only): current period revenue and projected salary, the formula with its chart, breakdown, salary by period, payments, and the payments behind the revenue |
| Screens | Salary board (period switcher, KPIs, per-employee rows with breakdown, adjust, pay, close/reopen), Salary Formulas (list, detail with versions and employees, new formula), employee detail page, Revenue Contributions report, Employee Salary report, Salary Cycle settings. CSV export for both reports |

## Verification

| Check | Result |
|---|---|
| API tests (real PostgreSQL 16) | **174 passed** |
| Lint / format (`ruff`), `alembic check` | clean, no drift |
| Web typecheck, ESLint, unit tests | clean, 11 passed |
| `next build` | succeeds, 33 routes |
| Pages and endpoints on the dev database | all return 200 |

**The reference scenario (design Section 16) passes end to end:**
- 25th cycle; a $10,000 receipt on Nov 10 counts in "Nov 2026" (Oct 25 – Nov 24) and is split A $6,000 / B $4,000.
- Calculated salary: A $626.67, B $352.59.
- After paying A $626.67 and B $200, B is owed $152.59.
- Checking holds $9,173.33, net profit is $9,173.33, the trial balance ties at $10,826.67 and the balance sheet balances.
- Closing before Nov 24 is refused; on Nov 25 it works and freezes the figures. Cancelling the receipt is then blocked until an admin reopens the period.
- After reopening and cancelling, both projected salaries drop to $0, and A is −$626.67 and B −$200 (paid ahead).

Also covered by tests:
- Your salary table: $2,999.99 → $0, $3,000 → $240, and up to $40,000 → $12,000.
- Receipts on Nov 24 and Nov 25 fall in different periods.
- All 28 start days give contiguous periods across year ends and leap years.
- Transition periods in both directions.
- Payments targeted at a period vs. oldest-first, and the resulting credit.
- Adjustments.
- Version locking and closed-date rules.
- Overlapping assignments.
- Each employee sees only their own data.
- Permissions per role.

**Not verified:** the new screens haven't been clicked through in a browser. There was no browser tool in this session.

## Decisions made during implementation

1. **Open periods are calculated live; only closed periods store statements.** There is no background recalculation that could lag or fail, and a closed period shows exactly what was frozen. Reopening deletes the frozen rows; the audit log keeps their figures.
2. **The version used is the one in effect on the period's last day**, not its first. Then "change the formula from today" applies to the current period, as people expect. Nothing can be dated inside a closed period.
3. **Which period a payment pays is derived**, not stored. Cancelling a payment or reopening a period never leaves stale links.
4. **Min/max payout applies to the formula part**; manual adjustments are added after and never capped.
5. **Changing the cycle when nothing depends on periods yet** simply regenerates them without a transition period. That's useful during setup.
6. The salary cycle moved out of the company settings form into its own screen, because changing it needs the preview.
7. **Splitting salary cost across projects (design §10.4) moves to Phase 4** with project financials. Salary payments post one 5100 line per employee for now.

## Your dev data

The dev database already has the cycle on the 25th, so the current period is Nov 2026 (Oct 25 – Nov 24). Your employees have no formula yet, so the salary board is empty. To see it work:
1. Open Employees → (an employee) → Salary formula → **Change**.
2. Pick "Revenue Share (provisional)" from their start date.
3. Revenue already credited to them in the period turns into salary on the board.

## Changes made during review (2026-10-28)

| Change | What it does |
|---|---|
| Saved exchange rate used by default | A payment with no rate typed uses the saved rate on or before its date (Settings → Currencies & Rates). With no saved rate and none typed, it can't be submitted; 1.0 is never assumed. The rate used is frozen on submit (migration 0004) |
| Assets by currency | Dashboard card and chart-of-accounts columns: balance in the account's own currency, value at the latest saved rate, and the recorded USD value. Display only, nothing is posted. `GET /reports/holdings` (CSV too) |
| Currency filter | Chart of accounts can show one currency's accounts |
| Revenue split optional | A customer payment may have no employee split (it then counts toward nobody's salary). If employees are added, the split must still cover exactly 100%. This changes the Q9 rule |
| Employees on payments | Payment Entries list (and CSV) shows the split or the salary / tagged employee |
| Category settings | Every setting is a choice list, checkbox or account picker, validated by the server. Built-in payment purposes keep their posting rule. "Required on payments" for income/expense categories is now enforced |
| Currencies and rates editable | Edit name, symbol, decimals (decimals can't shrink once used) and existing rates |
| Display | Lists show money with 2 decimals; detail pages keep full precision. Payment Entries opens on Submitted |
| Data fix | The mistaken expense session (PE-2026-00013 to 00018) was removed from the dev database on request; a full copy was kept as `erp_backup_20261028` |

### Follow-up (2026-10-28)

| Change | What it does |
|---|---|
| Employee expenses reduce revenue | Expenses tagged to an employee are subtracted from the revenue credited to them in the same salary period; the formula runs on the net (a negative net pays no revenue share; fixed pay and adjustments still apply). Salary payments are not expenses here. Closed periods block submitting or cancelling such expenses. Existing tagged expenses were backfilled (migration 0005) |
| Reports | Salary board, employee pages, My Salary, Revenue Contributions and the Employee Salary report show revenue, expenses and net; CSV exports too. Period headers show their date range |
| "This month" = salary period | Dashboard income, expenses and net profit, the General Ledger default, and the "This month / Last month" shortcuts follow the salary cycle (e.g. Oct 25 – Nov 24). Accounting period closing stays on calendar months |

## Next: Phase 4 — Projects

Full projects: types, members, milestones, tasks and subtasks, dependencies, comments, attachments and time tracking. List, details, Kanban and Gantt views. Project financials, including salary cost per project.
