# Administrator guide

How to set up and run the ERP day to day. For servers, backups and monitoring see [operations.md](operations.md).

## 1. First-time setup (in this order)

1. **Company** (Settings → Company): name, time zone, base currency. The base currency locks after the first posting.
2. **Salary cycle** (Settings → Salary Cycle): the day a salary month starts (e.g. the 25th → "Nov" = Oct 25 – Nov 24). Dashboards, salary and employee reports use these months. Accounting periods stay calendar months.
3. **Currencies & rates** (Settings → Currencies & Rates): add the currencies you hold (USDT, EUR…) and their rates. A payment with no rate typed uses the latest saved rate on or before its date.
4. **Chart of accounts** (Accounting → Chart of Accounts): the default chart works; rename or add accounts as needed.
5. **Payment accounts** (Settings → Payment Accounts): your bank accounts, wallets, cards and cash, each linked to a ledger account.
6. **Custom categories** (Settings → Custom Categories): payment methods, purposes, income/expense categories (with default accounts), project types, event types.
7. **Users and roles** (Settings → Users / Roles & Permissions): Administrator, Finance Manager, Project Manager, Employee. Link each person's sign-in to their employee record so they see their own salary, tasks and calendar.
8. **Employees and departments** (Employees → Directory), then **salary formulas** (Employees → Salary Formulas) and assign each employee a formula.
9. **Opening balances** (Accounting → Journal Entries → Opening balances) if you are moving from another system. Customers, suppliers, employees and projects can be imported (Settings → Data Import).

**Bidding** (Settings → Bidding Sheets): under Connections, paste each sheet's web app URL and secret, Test, and Save (details in operations.md → Bidding sheets). Then give each bidder a *bidding profile name* for every tab their extension writes to (its Sheet Tab Name), or let them set their own on My Bidding → Profile. One employee can have several, and their bids are added together. A tab nobody has claimed is listed as unclaimed.

**Backups** (Settings → Backups): a backup is made every night. Download one now and then and keep it off the server. Restoring a backup replaces all data; the data before the restore is kept as a "Before restore" backup. To move everything from one installation to another, back up and download on the old one, then upload and restore on the new one.

## 2. Every day

- **Record payments** (Accounting → Payment Entries → New payment). Customer payments can be split between employees (optional; if you split, it must cover 100%). Expenses can be tagged to an employee (it reduces their revenue) or a project.
- **Projects**: tasks, the board, the timeline, milestones. Assignees move their own tasks and log time.
- **Calendar**: meetings, company events, leave requests. Leave goes to approvers (Team Calendar → Leave requests); approved leave shows company-wide and sets capacity to 0 in Workload.
- **Bidding**: Team Overview and Daily Report show who bid how much over a date range and with what match scores; Job List shows every scraped job, who bid on it and which were missed ("Not bid"). Employees see their own numbers on My Bidding. The Dashboard also shows the last 30 days: anyone with a bidding profile name sees their own numbers, even with a Project Manager role, and a manager with no profile name sees everyone's. It only chooses what the Dashboard shows: a Project Manager can still see everyone on Team Overview, Daily Report and All Bids.

## 3. Every month (salary month)

1. Check the **Salary board** (Employees → Salary): revenue, expenses, net, formula, calculated, paid, balance per employee.
2. Add bonuses or deductions as **adjustments** if needed.
3. **Pay salaries**: the Pay button opens a pre-filled salary payment. Salary cost is split across projects automatically.
4. After the month ends, **close the salary period**. Its figures freeze, and receipts or employee expenses dated in it can no longer be submitted or cancelled. Only an Administrator can reopen it (with a reason; audited).
5. **Close the accounting month** (Settings → Accounting Periods) once the books are checked.
6. Review **Reports**:
   - **Monthly Summary**: income, costs, profit and margin per month with a chart, change against the previous month, year to date, and cash in, out and held.
   - **Cash Flow & Runway**: income received, expenses and salary paid, and owner capital and drawings per month (transfers between your own accounts left out), cash held at each month end (in total and per currency), fees by account, and how many months the cash lasts at the recent pace. Needs opening balances to be right.
   - **Customer Analysis**: revenue per customer per month, how much depends on the biggest customers, and customers who have gone quiet (no payment for 60+ days).
   - **Income & Expense Trends**: per category and per supplier or customer, month by month, with the biggest changes between the last two full months.
   - **Employee Performance**: per person, revenue brought in (net of their tagged expenses), salary earned, what is left for the company, salary as a % of revenue, and revenue per hour logged.
   - **Income & Expenses by Category** and **Customer & Supplier Payments**: any date range, compared with the previous period.
   - **Project Financials**: profit per project with a chart, hours against estimate and revenue per hour; each project's Financials tab shows it month by month against its budget.
   - **Employee Salary Report**.

   Months are salary periods. Amounts in tables open Payment Entries filtered to the payments behind them. Every report exports to CSV, Excel or PDF.

## 4. Checks and safety nets

- **Settings → System Checks**: run any time; also nightly, with a notification to administrators if anything fails.
- **Settings → Audit Log**: who changed what and when, for every financial and settings change.
- Posted payments are never edited or deleted: **cancel** (reversal on the same date) and **amend** (corrected copy).
- Changing a formula adds a version from a date; closed months keep the version they used.

## 5. Roles at a glance

| Role | Can |
|---|---|
| Administrator | Everything, including reopening closed periods, formulas, salary cycle, roles |
| Finance Manager | Payments, accounting, reports, salary board and closing salary periods, all projects' financials |
| Project Manager | Their projects: tasks, milestones, team calendar, approving their team's leave; everyone's bidding numbers |
| Employee | Own salary (read-only), own tasks (move, log time), comments, own calendar and leave requests; own bidding numbers and the shared job list |

Permissions can be adjusted per role (Settings → Roles & Permissions); scopes are *own*, *project* or *all*.
