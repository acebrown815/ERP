"""Default roles (docs/architecture.md, Section 15.2). Seeded once; admins can edit them afterwards."""

from app.modules.rbac.permissions import Scope

A, P, OWN = Scope.ALL, Scope.PROJECT, Scope.OWN

DEFAULT_ROLES: list[dict] = [
    {
        "key": "admin",
        "name": "Administrator",
        "description": "Full system access.",
        "grants_all": True,
        "grants": {},
    },
    {
        "key": "finance_manager",
        "name": "Finance Manager",
        "description": "Accounting, payments, revenue attribution and salary.",
        "grants": {
            "currencies.manage": A,
            "categories.manage.finance": A,
            "audit.read": A,
            "accounts.read": A,
            "accounts.manage": A,
            "journals.post": A,
            "periods.close": A,
            "payments.create": A,
            "payments.submit": A,
            "payments.cancel": A,
            "payment_accounts.manage": A,
            "parties.read": A,
            "parties.manage": A,
            "reports.financial": A,
            "employees.read": A,
            "employees.read_compensation": A,
            "revenue.read": A,
            "comp_formulas.read": A,
            "salary.read": A,
            "salary.adjust": A,
            "salary.close_period": A,
            "projects.read": A,
            "projects.read_financials": A,
        },
    },
    {
        "key": "project_manager",
        "name": "Project Manager",
        "description": "Projects, tasks, milestones and team scheduling.",
        "grants": {
            "categories.manage.delivery": A,
            "parties.read": P,
            "employees.read": P,
            "revenue.read": P,
            "projects.read": P,
            "projects.manage": P,
            "projects.read_financials": P,
            "tasks.manage": P,
            "tasks.update_own": P,
            "calendar.manage.team": P,
            "leave.approve": P,
        },
    },
    {
        "key": "employee",
        "name": "Employee",
        "description": "Own profile, tasks, calendar, revenue and salary (read-only).",
        "grants": {
            "employees.read": OWN,
            "employees.read_compensation": OWN,
            "revenue.read": OWN,
            "comp_formulas.read": OWN,
            "salary.read": OWN,
            "projects.read": P,
            "tasks.update_own": OWN,
        },
    },
]
