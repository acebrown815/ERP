# Phase 2 — Accounting & Payments: completion note

Date: 2026-10-28 · Branch: `phase-2-accounting` · Status: **done, merged into `main`**

## Scope delivered

| Area | What exists |
|---|---|
| Chart of accounts | Default chart (39 accounts, design §6.1), unlimited nesting, groups vs posting accounts, per-account currency (BTC/USDT wallets), system accounts the rules depend on (can be renamed, not removed), deactivate only at zero balance, delete only if never used, balances rolled up from the ledger |
| Ledger | One posting gateway. The **database** enforces: balanced entries (checked at commit), at least 2 lines, append-only lines, posted entries immutable except posted → reversed, no posting into closed periods, posting accounts only. Reversals mirror the entry on its original date |
| Periods | Monthly, created automatically. Close (past months only) / reopen with a reason; both audited |
| Journals | Manual entries with a live preview, opening-balances wizard (difference goes to Opening Balance Equity), reversal |
| Parties | Customers, suppliers, other (with "Other" subtype), organizations linking records of the same company, totals received/paid, payment history |
| Employees | Directory, departments, employment type, link to a sign-in account. Each employee gets a financial party (used by salary payments) |
| Projects (minimal) | Customer, manager, type, dates, contract value, members with a **default revenue split** |
| Payment accounts | Separate from methods (design §4). Backed by one money account in the ledger, details masked for people who don't manage them |
| Payment Entries | Receive / Pay / Internal transfer · Draft → Submitted → Cancelled → Amend · all posting rules R1–R3, P1–P3, T1/T2 · fees paid by client or company · multi-currency and crypto at **carrying cost** with realized gain/loss · method ↔ account-kind rules · "Other" needs a description and never skips the account rules · duplicate warning · live posting preview · idempotent submit and cancel |
| Revenue split | Pre-filled from the project's default (e.g. 60/40), by percent or amount, **must cover exactly 100% to submit**, exact rounding (3 × 33.33% of $100 = $100.00), follows the payment (active on submit, cancelled with it) |
| Reports | General Ledger (running balance, filters, cancelled pairs hidden by default), Trial Balance, Profit & Loss (optionally per project), Balance Sheet (balance check). All with CSV export |
| Import | CSV for parties, employees and projects: templates, dry run with row-level errors, all-or-nothing import |
| Web app | Payment Entries (list, editor with live preview and split editor, detail with ledger lines, cancel/amend/bank-check), Chart of Accounts, Journal Entries, General Ledger, Financial Statements, Customers/Suppliers/Other + detail, Employees, Projects, Settings → Payment Accounts / Accounting Periods / Data Import, dashboard with live figures |

## Verification

| Check | Result |
|---|---|
| API tests (real PostgreSQL 16) | **113 passed** (80 from Phase 1 + 33 new) |
| Lint / format (`ruff`), migration up/down/up, `alembic check` | clean, no drift |
| Web typecheck, ESLint, unit tests (money formatting, salary periods) | clean, 15 passed |
| `next build` | succeeds, 26 routes |
| End-to-end on the dev database (demo data) | $10,000 receipt split $6,000 / $4,000; P&L net $9,579.50; Balance Sheet balanced; Trial Balance ties at $10,420.50 |

The tests cover the Phase 2 half of the reference scenario, company- vs client-paid fees, three-way rounding, expense defaults from categories, the "Other" rules, salary payments to employees, transfers with no P&L effect, crypto receipt and conversion with realized loss, cancel/amend, idempotent submit, closed periods, permissions per role, and ledger tampering attempts blocked by the database.

**Not verified:** the new screens haven't been clicked through in a browser yet. There was no browser tool in this session. Every route returns 200 and the data behind them is checked, but please review the UI.

## Decisions made during implementation

1. **Carrying cost for foreign-currency and crypto outflows.** This is a correction found while testing. Valuing money that leaves a USDT wallet at today's rate left the wallet at 0 USDT but −$2. Valuing it at average cost fixes that and books the realized gain or loss properly (design §6.6 updated).
2. **Account tree uses a plain materialized path** instead of `ltree`. It's simpler, needs no extra type, and is indexed for prefix queries.
3. **The revenue split is either all percentages or all amounts per payment.** No mixing, which keeps the "exactly 100%" rule obvious.
4. **Method and purpose are optional on drafts** so you can save early. Both are required to submit.
5. **Customer advances, invoices and supplier bills are not included**, per Q1.

## Try it

`python -m app.cli demo` now also creates sample business data:
- Customer ABC and a supplier.
- Employees A and B, linked to `alice@` and `bob@`.
- The "ABC Web Platform" project with a 60/40 split.
- A submitted $10,000 receipt and a $420.50 hosting expense.

Sign in as `finance@example.com` / `Demo-Pass-2026` to see it.

## Next: Phase 3 — Salary

Salary formulas (rate curve, tiers, fixed, bonuses, preview chart), salary cycle setting with transition periods, salary periods and statements recalculated live from the revenue split, close/reopen period, salary payments linked to statements with running balances, employee self-service dashboard, employee revenue and salary reports.
