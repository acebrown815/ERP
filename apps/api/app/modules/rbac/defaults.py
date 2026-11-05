"""Default roles (docs/architecture.md, Section 15.2). Seeded once; admins can edit them afterwards."""

from app.modules.rbac.permissions import Scope

A, P, OWN = Scope.ALL, Scope.PROJECT, Scope.OWN

# What every hired manager, contractor and freelancer can do. It comes from their employee record, linked to their
# sign-in, not from a role. 'project' scope means only the projects they're connected to: tasks there, nothing else.
RESTRICTED_GRANTS = {
    "projects.read": P,
    "tasks.manage": P,
    "tasks.update_own": P,
    "payments.read_own": A,
}

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
            "hired_managers.read": A,
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
            "revenue.read": OWN,
            "projects.read": P,
            "projects.manage": P,
            "tasks.manage": P,
            "tasks.update_own": P,
            "calendar.manage.team": P,
            "leave.approve": P,
            "bidding.read": A,
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
            "hired_managers.read": OWN,
            "projects.read": P,
            "projects.create_own": OWN,
            "tasks.update_own": OWN,
            "bidding.read": OWN,
        },
    },
    {
        "key": "hired_manager",
        "name": "Hired Manager",
        "description": "Label only: access comes from the linked employee being marked as a hired manager.",
        "grants": {},
    },
    {
        "key": "supervisor",
        "name": "Supervisor",
        "description": "Read-only view of every project and hired manager, plus the audit log.",
        "grants": {
            "audit.read": A,
            "employees.read": A,
            "hired_managers.read": A,
            "projects.read": A,
        },
    },
]
