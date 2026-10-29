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

## 2. Every day

- **Record payments** (Accounting → Payment Entries → New payment). Customer payments can be split between employees (optional; if you split, it must cover 100%). Expenses can be tagged to an employee (it reduces their revenue) or a project.
- **Projects**: tasks, the board, the timeline, milestones. Assignees move their own tasks and log time.
- **Calendar**: meetings, company events, leave requests. Leave goes to approvers (Team Calendar → Leave requests); approved leave shows company-wide and sets capacity to 0 in Workload.

## 3. Every month (salary month)

1. Check the **Salary board** (Employees → Salary): revenue, expenses, net, formula, calculated, paid, balance per employee.
2. Add bonuses or deductions as **adjustments** if needed.
3. **Pay salaries**: the Pay button opens a pre-filled salary payment. Salary cost is split across projects automatically.
4. After the month ends, **close the salary period**. Its figures freeze, and receipts or employee expenses dated in it can no longer be submitted or cancelled. Only an Administrator can reopen it (with a reason; audited).
5. **Close the accounting month** (Settings → Accounting Periods) once the books are checked.
6. Review **Reports**:
   - Monthly Summary.
   - Income & Expenses by Category.
   - Customer & Supplier Payments.
   - Project Financials.
   - Employee Salary Report.

   Every report exports to CSV, Excel or PDF.

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
| Project Manager | Their projects: tasks, milestones, team calendar, approving their team's leave |
| Employee | Own salary (read-only), own tasks (move, log time), comments, own calendar and leave requests |

Permissions can be adjusted per role (Settings → Roles & Permissions); scopes are *own*, *project* or *all*.
