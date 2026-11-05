# Hired Project Managers — Plan (v0.9, 2026-11-05)

An employee can hire someone to help run their project. The ERP should record this: the employee creates the project, stays its Project Manager, and selects a hire. Finance pays the hire from an expense on that project, which comes off the manager's revenue. The hire sees the projects they're connected to and manages their tasks, and the manager and company management monitor the work. One hire can work for several employees.

**Status: all phases built on `feature/hired-managers`, not committed or released.** Where the build differs from the plan below, §14 says so.

## 1. Decisions (answered 2026-11-04)

| # | Question | Decision |
|---|---|---|
| 1 | Who bears the hire's cost? | **It comes off the Project Manager's revenue before the salary formula runs**, as tagged expenses already work (§2). The company bears most of the cost. |
| 2 | Whose money pays the hire? | **A company payment account.** |
| 3 | Who monitors? | **Company management sees all hires. A manager sees a hire's work and pay only on their own projects.** |
| 4 | Can a hire work for several employees? | **Yes**, on separate projects. |
| 5 | Can a hire create projects? | **No (changed 2026-11-04).** Employees and staff create projects. A hire sees only the projects where they're selected as the hire. |
| 6 | Can a hire add their own workers? | **No.** |
| 7 | How do the employee and hire appear on a project? | **The employee is the Project Manager. The hire is a separate Hire field.** Each project has at most one of each. |
| 8 | How is a hire paid? | **On an expense payment, finance selects the project and pays its hire.** The amount comes off the manager's revenue. |
| 9 | Who can select a hire? | **Staff and the project's manager, from any active hire, with no approval.** Assumed; the alternative is staff approving each pairing. |
| 12 | Who else is restricted? | **Contractors and Freelancers, automatically (2026-11-05).** They get the same access as hires whatever their role: connected projects' tasks and their own payments. They can't see their own salary or revenue pages, though staff still can. Part-Time and Other aren't restricted. |
| 13 | What can restricted access do on a project? | **Manage tasks only (2026-11-05).** Projects and milestones are read-only. |
| 14 | Who can select a hire? | **Full-time employees on their own projects, with no approval, and staff (2026-11-05).** This replaces decision 9. |
| 11 | Does the role on a hire's sign-in matter? | **No.** Access comes from three connections: the sign-in is linked to an employee, that employee is marked as a hire, and a project selects them. The Hired Manager role grants nothing by itself, and another role can't show them more. An administrator can't be marked as a hire. |
| 10 | What does a hire see of pay and customers? | **A "Paid this month" tile with their own total, and the customer's name on a project, read-only.** |

## 2. Cost of decision 1

These figures use the salary curve in `tests/test_salary_engine.py`, with $6,000 revenue and a $3,000 hire:

| | No hire | With hire | Change |
|---|---|---|---|
| Manager's salary | $626.67 | $240.00 | −$386.67 |
| Company keeps | $5,373.33 | $2,760.00 | −$2,613.33 |

- **Salary cliff:** paying $3,001 leaves $2,999 of revenue, so the manager's salary drops to $0.
- **Lost shortfalls:** if the fee exceeds a period's revenue, the [shortfall doesn't carry forward](../apps/api/app/modules/salary/service.py#L204), so the company absorbs it.

This plan doesn't change either behaviour. Each would be a separate salary rule.

## 3. How it fits together

```
           Project 1                          Project 2
  Project Manager: Employee A        Project Manager: Employee B
  Hire: Jordan                       Hire: Jordan

Customer receipt on Project 1 ─ 100% split ─▶ Employee A's revenue
                                                  │ minus
Hire payment on Project 1, paid to Jordan ────────┘ (expense charged to Project 1's manager)
                                                  ▼
                                     salary formula ─▶ Employee A's salary
```

| Concept | Implementation |
|---|---|
| Hire | An `Employee` with `is_hired_manager = true`, a login and the `hired_manager` role |
| Project's hire | New column `projects.hire_employee_id` |
| Who is charged | The existing `projects.manager_employee_id` |
| Who a hire works for | Worked out from their projects, with no separate table |
| Revenue | The manager stays a project member with the default split; the hire gets none |
| Pay | New purpose `hire_payment`, using new posting rule `P4`. **One payment per project**, so work for two employees means two payments |
| Hire's rights | Enforced from `is_hired_manager`, so a wrongly assigned role can't widen what they see or edit |

## 4. Phase 1: hire record and role

**Data: migration `0013_hired_managers.py`**
- Add `employees.is_hired_manager`, a boolean defaulting to false.
- Add `projects.hire_employee_id`, a nullable foreign key to `employees.id` with `ondelete=RESTRICT`, plus an index and a check that it differs from `manager_employee_id`.
- Add the role grants listed under Permissions below.

**Permissions: [permissions.py](../apps/api/app/modules/rbac/permissions.py)**

| New permission | Scopes | Purpose |
|---|---|---|
| `payments.read_own` | all | Hire's access to their own payments (Phase 4) |
| `hired_managers.read` | own, all | Monitoring page (Phase 5) |
| `projects.create_own` | own | Employee creates and runs their own projects (§6) |

Don't grant `projects.manage` to the `employee` role for this. It would give every employee who manages a project today full edit rights over its money fields and team.

Grants on existing roles aren't overwritten by seeding, so migration 0013 must add them with `INSERT … SELECT` from `roles`, as [0009](../apps/api/migrations/versions/0009_private_employee_figures.py) does for its grant changes. On a fresh database those rows don't exist yet, so [defaults.py](../apps/api/app/modules/rbac/defaults.py) must carry the same grants:
- `employee`: `hired_managers.read` own, `projects.create_own` own
- `finance_manager`: `hired_managers.read` all

**New default roles: [defaults.py](../apps/api/app/modules/rbac/defaults.py)**

| Role | Grants |
|---|---|
| `hired_manager` | None: a label only. Linked hires get `projects.read` P, `projects.manage` P, `tasks.manage` P, `tasks.update_own` P, `employees.read` P and `payments.read_own` all from `HIRED_MANAGER_GRANTS` |
| `supervisor` | `projects.read` all, `employees.read` all, `hired_managers.read` all, `audit.read` all |

`hired_manager` has no bidding, salary, revenue or party permissions. This avoids the [Project Manager role's access to all bidding data](../apps/api/app/modules/rbac/defaults.py#L50-L61).

**Validation: [employees/service.py](../apps/api/app/modules/employees/service.py)**
- An employee can't be switched to a hire if they have a formula assignment, revenue credit, salary payment, or are a project's manager.
- A hire can't be switched back while they're on a project or have `P4` payments.
- Add `is_hired_manager` to `EDITABLE`, `EmployeeOut` and the create and update schemas. Add an `is_hire` helper exported from `employees/api.py`, since [modules may only import each other's facades](../apps/api/tests/test_architecture.py).
- Add a `hired` filter to the employee list.
- Add `GET /hires/options` under `projects.create_own` or `projects.manage`: every active hire, returning only ID and name. Only staff create hire records.

**Keep hires out of payroll.** Each of these must reject a hire:

| Entry point | Why |
|---|---|
| [Revenue split](../apps/api/app/modules/attribution/service.py#L52) (`replace_draft`) | They earn no revenue credit |
| [Formula assignment](../apps/api/app/modules/compensation/service.py#L343) (`create_assignment`) | They get no salary statement |
| [Salary adjustment](../apps/api/app/modules/salary/service.py#L470) (`add_adjustment`) | Otherwise they could build up a salary balance |
| `P2` salary payment | Phase 2 |
| Employee tag on an expense | They can't be charged for themselves |
| `default_allocation_pct` on a project member | Same as the revenue split |
| `manager_employee_id` on a project | The manager is the one charged, so must earn revenue |

**Hide colleague details from hires.** [`EmployeeOut`](../apps/api/app/modules/employees/router.py#L22-L42) includes `notes`, `phone` and `email`, and hires can read their team's records. For a hire, return `null` for those three fields on anyone but themselves. Show a contact option later if needed.

**Web**
- Employee form: add a "Hired manager" switch, shown only to `employees.manage`.
- Directory: add a "Hired manager" badge and filter.
- [`EmployeePicker`](../apps/web/src/components/erp/pickers.tsx#L79): add an `excludeHires` option, used by the manager, revenue split, expense tag, salary and formula screens.
- Regenerate `src/types/api.ts` with `npm run gen:api`.

**Differences from the plan (Phase 1 as built)**
- **Stricter team rule:** a hire can't be a project team member at all, with or without a split. They only join through the Hire field, so there's one route onto a project.
- **Changing type:** any formula, split, adjustment, payment or project blocks the change in both directions, instead of separate rules for each direction.
- **Done early:** rejecting hires on `P2` salary payments and expense tags is already in place.
- **Also hidden from hires:** colleagues' `user_id` and bidding tab names, as well as `notes`, `phone` and `email`.
- **Employee page:** salary and formula sections don't appear on a hire's record.

## 5. Phase 2: paying the hire

**Form: [entry-editor.tsx](../apps/web/src/components/payments/entry-editor.tsx)**

Finance creates a payment entry, direction Pay, and chooses the purpose **Hired Manager Payment**:

| Field | Behaviour |
|---|---|
| Project | Comes first and is required. Lists only projects with a hire |
| Paid to | Read-only, filled with the project's hire (saved as their employee party in `party_id`) |
| Charged to | Read-only, showing the project's manager, with the hint "Comes off this person's revenue" |
| Amount, method, paid from, date | As on any payment |
| Employee tag, expense split, category, expense account | Hidden |

Changing the project updates "Paid to" and "Charged to" together. If finance starts from Supplier / Operating Expense and picks a project with a hire, show a hint: "This project has a hire. Pay them instead?", which switches the purpose.

**Backend**

| File | Change |
|---|---|
| [groups.py](../apps/api/app/modules/categories/groups.py#L51) | Add `"P4": "Hired manager payment"` to `POSTING_RULES`, and system purpose `hire_payment` with `{"direction": "pay", "posting_rule": "P4"}` |
| [chart.py](../apps/api/app/modules/accounting/chart.py) | Add `AccountSpec("5700", "Hired Manager Fees", "expense", "expense", "5000", system_key="hire_fees")` |
| [accounting/service.py](../apps/api/app/modules/accounting/service.py#L679) | `seed` only builds the chart on an empty database. Make it also add `hire_fees` when missing, using the next free 57xx code if 5700 is taken |
| [posting.py](../apps/api/app/modules/payments/posting.py#L33-L35) | `FIXED_COUNTER["P4"] = "hire_fees"`, `RULE_PARTY_KINDS["P4"] = ("employee",)`, and require a party for `P4` at [line 229](../apps/api/app/modules/payments/posting.py#L229) |
| [posting.py](../apps/api/app/modules/payments/posting.py#L246-L253) | Check the hire and work out who is charged (below), after the project lookup. Reject hires in `P2` |
| [payments/service.py](../apps/api/app/modules/payments/service.py#L457-L458) | On `P4`, always save the calculated `employee_id`, even if the draft held another one |
| [payments/service.py](../apps/api/app/modules/payments/service.py#L421) | `check_expense_split` rejects `P4`, the same as `P2` |

```python
if rule == "P4":
    employee_id = None
    hire = await employees.by_party(session, party.id) if party else None
    if project is None:
        errors.add("project_id", "Choose the project this payment is for", "required")
    elif hire is None or hire.id != project.hire_employee_id:
        errors.add("party_id", "Must be this project's hire")
    elif project.manager_employee_id is None:
        errors.add("project_id", "This project has no manager to charge", "required")
    else:
        employee_id = project.manager_employee_id
```

Warnings in the preview, which don't block submit:
- The manager is terminated.
- The payment is more than the manager's net revenue for the period, so the excess won't reduce anything further (§2).

**No change needed:**
- [The expense step](../apps/api/app/modules/payments/service.py#L494-L503) already lowers the charged employee's revenue, and blocks closed salary periods. Cancelling already reverses it.
- [The consistency check](../apps/api/app/modules/payments/checks.py#L41-L48) already treats any non-`P2` payment with an employee tag as an employee expense.
- [The project ledger](../apps/api/app/modules/accounting/service.py#L741-L744) counts it as a direct expense, because it isn't the salary account.

`employee_id` is saved at submit, so changing a project's manager or hire later doesn't alter past payments.

**Limitation:** only the project's current hire can be paid. Replacing a hire before paying them means they can't be paid on that project any more. Editing the hire field should warn "Pay any amount owed to this hire first". If this comes up often, add a history of a project's past hires.

## 6. Phase 3: project creation and controls

**Rules for everyone**, checked in `_validate` and `set_members` so the money and the project can't drift apart:
- `hire_employee_id` must be an active hire. `manager_employee_id` can't be a hire.
- A project with a hire must have a manager who is on the team with a default split above 0. This stops a staff project manager who earns nothing from the project being charged for the hire.
- That manager can't be removed from the team, or have their split cleared, while the project has a hire.

Add `hire_employee_id` to `EDITABLE`, `ProjectOut` and the create and update schemas. Changes are audited like other project fields.

**Hire's access:** [`visible_project_ids`](../apps/api/app/modules/projects/service.py#L67-L74) and [`team_ids`](../apps/api/app/modules/projects/service.py#L56-L64) must include `hire_employee_id`. `tasks.manage` then works through the [existing team check](../apps/api/app/modules/tasks/router.py#L224-L225). Projects for employees A and B stay separate, because A only sees projects they manage or belong to.

**Employee creates a project (`projects.create_own`)**

| Field | What happens |
|---|---|
| Project manager | Always the employee creating it, shown read-only |
| Hire | Optional picker from `GET /hires/options` |
| Team | The employee is added with a 100% default split |
| Customer, contract value, budget | Left empty for staff to fill in, because `employee` has no `parties.read` and these affect the money |

**What a manager with `projects.create_own` can do on a project they manage**

| Action | Rule |
|---|---|
| Edit project | Name, description, type, dates, priority, status and manual completion |
| Change the hire | Select another hire or remove the hire |
| Tasks and milestones | Create and manage them. Otherwise a project with no hire couldn't have any tasks |
| Money fields, split, team, manager | Can read, can't edit; staff only |

This also applies to regular employees who already manage a project today: they gain these rights, and no others.

**Hire edits a project**

All of these apply when `is_hire(user)` is true. Regular project managers keep their current behaviour.

| Action | Rule for a hire | Where |
|---|---|---|
| Create project | 403, with no New project button | [`create_project`](../apps/api/app/modules/projects/router.py#L137-L145) |
| Edit project | Allow only name, description, type, dates, priority, status and manual completion. Reject other fields with 403 | [`update_project`](../apps/api/app/modules/projects/router.py#L148-L165) |
| Change members | 403 | [`set_members`](../apps/api/app/modules/projects/router.py#L168-L181) |
| Read project | Return `null` for contract value, budget and split percentages. Show the customer's name read-only, through a new `customer_name` on `ProjectOut`, because hires have no `parties.read` | [`_out`](../apps/api/app/modules/projects/router.py#L104-L108), which needs the user passed in |

**Code changes**
- [`create_project`, `update_project`](../apps/api/app/modules/projects/router.py#L137-L165) and the milestone routes currently require `projects.manage`. They need to accept `projects.create_own` too. [`can_manage`](../apps/api/app/modules/projects/service.py#L232-L240) enforces the rules above, and must treat the hire as able to edit.
- [`_access`](../apps/api/app/modules/tasks/router.py#L219-L227) in the tasks router must let the manager manage tasks.
- `ProjectOut` needs `manager_name` and `hire_name`. The `employee` role only has `employees.read` on themselves, so the page can't look these names up today.
- The task assignee picker in [`task-panel.tsx`](../apps/web/src/components/projects/task-panel.tsx) uses `useEmployees`, which would show an employee only themselves. It needs a project-team list, or a manager can't assign tasks to their hire.

**Web**
- The [New project button](<../apps/web/src/app/(app)/projects/page.tsx#L172>) and [Edit button](<../apps/web/src/app/(app)/projects/[id]/page.tsx#L229>) check `projects.manage` and need to accept the new permission. Edit should only appear on projects the user can edit.
- [`ProjectDialog`](../apps/web/src/components/projects/project-dialog.tsx) sends every field on save, then always calls `PUT /members`. The employee and hire versions must hide the staff-only fields, send only allowed fields, and skip the members call. Otherwise it returns a 403 straight after the project was created, and the user sees an error for a successful save.
- The hire version has a required "Project manager" picker, selected automatically if there's only one.
- Staff version: add a "Hire" picker, and show the error if the manager has no split.
- Add a hire column and filter to the project list, and a manager column and filter for hires.

The project pages already show "—" for empty contract values and leave out empty split percentages, but this needs checking in the browser.

**Separate existing bug:** a regular project manager who creates a project without naming themselves as manager gets a [403 from the same members call](../apps/api/app/modules/projects/service.py#L239), after the project was already saved, and then can't see it. It's outside this feature and worth its own fix.

## 7. Phase 4: hire sees their payments

| Change | Where |
|---|---|
| Add `payments.read_own` to `ReadOwnPayments` | [payments/router.py](../apps/api/app/modules/payments/router.py#L31) |
| Show the Payment Entries menu item for that permission | [nav.ts](../apps/web/src/lib/nav.ts#L86) |
| For a hire, list and open only `submitted` payments | [`list_entries`](../apps/api/app/modules/payments/router.py#L489), [`get_entry`](../apps/api/app/modules/payments/router.py#L699), and the totals endpoint |
| For a hire, also limit them to `P4` payments where they are the party | same |
| For a hire, clear `description`, `cancel_reason`, account IDs and `journal_entry_id`, and hide "Charged to" | [`_entry_out`](../apps/api/app/modules/payments/router.py#L340), [`_entries_out`](../apps/api/app/modules/payments/router.py#L366) |
| CSV and PDF exports: same limits and hidden fields | [`list_entries`](../apps/api/app/modules/payments/router.py#L529) |
| Dashboard for hires (below) | [dashboard page](<../apps/web/src/app/(app)/dashboard/page.tsx#L465>). `EmployeeOverview` depends on `/me/salary`, which a hire can't call, so hires get their own overview |
| Hire menu (below) | [nav.ts](../apps/web/src/lib/nav.ts#L179), [dashboard shortcuts](<../apps/web/src/app/(app)/dashboard/page.tsx#L472-L483>). `/me` must return `is_hired_manager` |

A regular employee's drafts stay visible in their own list. That's existing behaviour and isn't changed here.

**What a hire sees after logging in: Dashboard**

| Section | Content |
|---|---|
| Tiles | Open tasks, overdue tasks, active projects, paid this month |
| My projects | Name, Project Manager, progress, open tasks and deadline, linking to the project |
| This week | The existing `MyWeek` card: their tasks due and calendar events |
| Recent payments | Date, project, amount, method, reference and status |
| Shortcuts | My tasks, Projects, My calendar |

**Hire menu**

| Menu item | Shown |
|---|---|
| Dashboard | Yes |
| Projects: All Projects (labelled My Projects), Tasks, Kanban Board, Gantt Timeline | Yes, limited to their projects |
| Payments (the Payment Entries page, relabelled) | Yes, limited to their own |
| My Calendar | Yes |
| Directory | No. It would work through `employees.read`, but team names already appear on projects |
| Team Calendar, Company Calendar | No |
| Settings: Company, Custom Categories, Currencies & Rates | No |

The calendar and settings items have no `anyOf`, so [every signed-in user sees them](../apps/web/src/lib/nav.ts#L55-L56). Add a `hideForHire` flag to `NavItem`, and check it in `canSee`. This only hides menu items. The API routes the app needs, such as company base currency, stay readable, so check during the build that those routes don't return more than a hire should see.

## 8. Phase 5: monitoring

**API:** `GET /api/v1/reports/hired-managers?from=&to=` in the reporting module, using other modules' facades only. It needs `hired_managers.read`:
- **All scope:** every hire and manager pair, plus a total per hire across managers.
- **Own scope:** only pairs where the signed-in user is the manager.

There's **one row per hire and manager pair**, taken from current projects plus any `P4` payments in the range, so a past hire's pay still appears. Every figure counts only that manager's projects. Employee A must never see the hire's activity, projects or pay for employee B, not even as a total.

| Field | Source |
|---|---|
| Hire, status, manager | `employees` |
| Projects; projects created in the range | `projects` (`hire_employee_id`, `manager_employee_id`, `created_by`) |
| Tasks created, completed, open, overdue | `tasks` (`created_by`, `completed_at`, `status`, `due_date`), for those projects |
| Last activity | Latest of task update, comment, time entry and project update on those projects |
| Paid in the range | Submitted `P4` payments with the hire as party and the manager as `employee_id` |
| Manager's gross revenue, and net after expenses | Salary lines for the manager |

**Web**
- New page at `/employees/hired-managers`, with a menu item under `hired_managers.read`.
- Date range, sortable table and CSV export, using the existing report components. In all scope, group rows by hire and show the total for each.
- Rows link to the hire's projects and to the filtered [Payment Entries](../apps/web/src/components/reports/shared.tsx#L30) list.
- Flag hires with no activity for 7 days or more. Make this a constant so it can change later.

**Drill-down:** managers open their own project board. The `supervisor` role opens the existing board, timeline and audit log, with no new screens.

## 9. Tests

New file `tests/test_hired_managers.py`:

| Area | Cases |
|---|---|
| Setup | Rejects switching an employee with salary history to a hire, and a hire as project manager; `hired_manager` passes the same role seed checks as other defaults |
| Payroll exclusion | A hire can't get a split, formula, adjustment, `P2` payment or expense tag |
| Payment | $6,000 receipt to the manager and $3,000 `P4` gives salary $240.00, a $3,000 direct project expense, and nothing on the salary account |
| **Two managers** | One hire is paid on A's project and on B's. Each manager is charged only their own payment, and each salary reflects only that |
| Payment rules | Rejects a missing project, a project with no hire, a party who isn't that project's hire, and a past hire; a mismatched `employee_id` on a draft is replaced; a split is rejected; a closed salary period is blocked |
| Reversal | Cancelling restores salary to $626.67; the `salary_links` check stays clean |
| History | Changing a project's manager or hire leaves past payments on the original employee |
| Project rules | A hire can't be set without a manager on the team with a split above 0; that manager can't be removed or have their split cleared while the hire is set |
| **Employee creates** | The employee is manager with 100%, with or without a hire. They can't name a colleague as manager, or set money fields, the split or the team. The options endpoint returns only ID and name |
| **Manager rights** | The manager manages tasks and changes the hire; another team member can't. A manager can assign tasks to their hire |
| Hire's projects | Creating returns 403; only connected projects are visible, whatever role the sign-in holds; forbidden edits return 403; money fields are `null` for the hire but not for staff |
| Regular PMs | Still edit money fields and members as before |
| **Employee separation** | Employee A can't see B's projects, tasks or payments through the shared hire, in the API or the report |
| Payment visibility | A hire sees only their own submitted `P4` payments, not drafts, cancelled payments or other payments on the project; hidden fields are empty in JSON and CSV |
| Isolation | A hire gets 403 or 404 on salary, revenue, bidding, parties and other employees' projects; team `notes`, `phone` and `email` are `null` |
| Monitoring | Own scope shows only the manager's pairs, with no figures from other managers; all-scope totals equal the sum of the pairs; a hire can't open the report |

Update `test_categories.py` for the new rule, and add web tests with `vitest` for the payment editor's `hire_payment` state.

Run before each merge: `pytest`, `npm run typecheck`, `npm run lint`, `npm run test`, plus a browser pass through §12.

## 10. Build order

| Phase | Size | Depends on | Usable result |
|---|---|---|---|
| 1. Hire record and role | Medium | §1 | Hire records and logins exist, and hires stay out of payroll |
| 3. Project creation and controls | Medium to large | 1 | Employees create projects and select hires. **Required before a real hire uses the role** |
| 2. Paying the hire | Medium | 1, and the `hire_employee_id` column | Finance pays a project's hire and the manager is charged |
| 4. Hire sees payments | Small | 2 | Hires can see their pay |
| 5. Monitoring | Medium | 2, 3 | Managers and management have a summary page |

One PR per phase, starting from an up-to-date `main`.

## 11. Rollout

1. Deploy. `migrate` applies 0013 automatically.
2. Run `python -m app.cli seed` ([operations.md](operations.md)) if this release went out before deploys ran the seed. It adds the new roles, purpose and account, and leaves existing rows alone. Until it runs, the purpose doesn't exist and nothing else changes.
3. Pilot with one hire: staff create the employee record as a hired manager with a login. An employee then creates a project and selects the hire. For an existing project, staff set the hire, and make sure the manager is the employee earning the revenue.
4. Run one payment in an open salary period, and check the manager's salary, project financials and the hire's view.

If someone is already running the manual workaround with a supplier record, leave those past payments as they are. New payments go through `hire_payment`, and the supplier record can be set inactive.

**Rollback:** the new columns and purpose do nothing unless used. Before downgrading, cancel any `P4` payments, then clear the hire flags and project hires.

**Docs to update:** `architecture.md` (§7.3 posting rules, §8, §15.2 permissions) and `admin-guide.md` (how to set up a hire).

## 12. Done when

- [ ] An employee creates a project and selects a hire. They're the Project Manager, with the revenue split.
- [ ] A hire logs in to a dashboard of their own work and pay, and the menu shows only their projects, tasks, payments and calendar.
- [ ] A hire can't create projects, and sees only the projects they're connected to, whatever role their sign-in has.
- [ ] A hire can't change or read the contract value, budget or split, and can't change the manager, hire or team.
- [ ] Finance picks the project on an expense, its hire is filled in as "Paid to", and the manager is charged with no further input.
- [ ] Each manager's salary, project financials and ledger match the §9 worked example.
- [ ] Cancelling a payment fully reverses it.
- [ ] Management sees every hire's activity and pay. A manager sees only the hire's work and pay on their own projects.
- [ ] Hires never appear in salary statements, revenue splits or salary pickers.

## 13. Checked during the build

- **Project type picker:** works for hires and employees, because categories are readable by anyone signed in.
- **Party payments report:** a hire appears under "Suppliers (paid)" with their payments, which is correct.
- **Staff counts:** nothing counts all employees as headcount. Salary boards only list people with salary activity.
- **Task assignment:** a hire, or an employee running their own project, can only assign tasks to the project's team. Regular project managers and staff are unchanged.
- **Calendar:** the team and company views show colleagues' leave, so the API refuses them for hires, on top of removing them from the menu. A hire's own calendar still works.

## 14. Differences from the plan (as built)

- **Saving the team:** `POST` and `PATCH /projects` accept `members`, so the project and its team save together and the hire rules are checked on the end result. The form uses this rather than a second call, which also fixes the existing project manager bug in §6.
- **List of managers for a hire:** the route is `GET /projects/my-managers`, used for the filter on their project list.
- **Fixed permissions:** `auth.deps.user_grants` gives every linked hire `HIRED_MANAGER_GRANTS`, so the role on their sign-in has no effect. The `hired_manager` role itself grants nothing (migration 0014): a sign-in with that role and no link can't see or create anything, and its dashboard says what's missing. The Directory shows "Not linked" for a hire with no sign-in.
- **Who can edit:** `ProjectOut.edit_mode` (`full`, `own`, `hire`, or empty) tells the form what to show. The API enforces the same rules.
- **Names on projects:** `ProjectOut` and its members also carry names, so people with no access to the Directory can see their team. `customer_name` goes to the hire, the project's manager and anyone with `parties.read`.
- **Hire's payment page:** retitled "Payments", amounts shown as money received, and the status, direction, Employees and Received parts removed.
- **Page size:** the API's limit went from 200 to 500 per page. The project Tasks tab, Tasks page and Kanban board already asked for 500 and got a 422, so they showed no tasks on `main` too.
- **Supervisor role:** `hired_managers.read` at all scope shows pay and managers' revenue on the report, so a supervisor sees those figures even though the role has no other money access.
- **Guard (2026-11-05):** a restricted sign-in is refused every route not on `RESTRICTED_ROUTES` in `auth/deps.py`, so a new route is closed to them until someone adds it. `tests/test_hired_manager_guard.py` walks every route to hold this. One who has left has no permissions. They have no employee list, no project-level files (which can hold contracts), no calendar events beyond their feed, and a cut-down view of company settings and categories. Payment search skips the description they can't see.
- **Employee's payment filter:** Payment Entries has a "Hired manager" dropdown for employees, listing hires on their projects or paid by them before, and showing only payments charged to them.
- **Monthly summary:** hired managers aren't in the employee dropdown, because they have no figures of their own. When a manager is selected, or views their own report, a "Hired managers" card and an "Of which hired managers" column show what each hire was paid. That amount is already part of their Expenses. The whole-company view doesn't break it out.
- **Employee dashboard (2026-11-05):** the "Last 12 months" chart and "My expenses this month" tile include the employee's share of split expenses (`shared_expenses` on salary statements), which still don't affect salary. The My Salary page keeps tagged expenses only, so its sum explains the salary. Four tiles show the employee's open, overdue, due-soon and completed tasks.
- **Payment form hint:** an ordinary expense on a project with a hire offers "Pay them instead?".
