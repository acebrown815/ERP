"""Permission registry. Permissions are code-defined; roles grant them with a data scope.

Keys for later phases are registered now so roles can be configured once and the matrix in
docs/architecture.md (Section 15.2) stays the single reference.
"""

from dataclasses import dataclass
from enum import StrEnum


class Scope(StrEnum):
    OWN = "own"
    PROJECT = "project"
    ALL = "all"

    @property
    def rank(self) -> int:
        return {"own": 1, "project": 2, "all": 3}[self.value]


@dataclass(frozen=True)
class Permission:
    key: str
    label: str
    group: str
    scopes: tuple[Scope, ...] = (Scope.ALL,)


ALL_ONLY = (Scope.ALL,)
SCOPED = (Scope.OWN, Scope.PROJECT, Scope.ALL)
PROJECT_OR_ALL = (Scope.PROJECT, Scope.ALL)

_DEFINITIONS: list[Permission] = [
    # Administration
    Permission("settings.manage", "Manage company settings", "Administration"),
    Permission("users.manage", "Manage users", "Administration"),
    Permission("roles.manage", "Manage roles and permissions", "Administration"),
    Permission("imports.manage", "Run data imports", "Administration"),
    Permission("audit.read", "Read audit log", "Administration"),
    Permission("backups.manage", "Create, download and restore backups", "Administration"),
    Permission("currencies.manage", "Manage currencies and exchange rates", "Administration"),
    # Categories
    Permission("categories.manage.finance", "Manage finance categories", "Categories"),
    Permission("categories.manage.people", "Manage people categories", "Categories"),
    Permission("categories.manage.delivery", "Manage project, task and event categories", "Categories"),
    Permission("categories.manage.general", "Manage document categories", "Categories"),
    # Accounting & payments (Phase 2)
    Permission("accounts.read", "View chart of accounts and balances", "Accounting"),
    Permission("accounts.manage", "Manage chart of accounts", "Accounting"),
    Permission("journals.post", "Post manual journal entries", "Accounting"),
    Permission("periods.close", "Close accounting periods", "Accounting"),
    Permission("periods.reopen", "Reopen accounting periods", "Accounting"),
    Permission("payments.create", "Create payment entries", "Payments"),
    Permission("payments.submit", "Submit payment entries", "Payments"),
    Permission("payments.cancel", "Cancel payment entries", "Payments"),
    Permission("payment_accounts.manage", "Manage payment accounts", "Payments"),
    Permission("parties.read", "View parties", "Parties", PROJECT_OR_ALL),
    Permission("parties.manage", "Manage parties", "Parties"),
    Permission("reports.financial", "View financial reports", "Reports"),
    # People (Phase 2-3)
    Permission("employees.read", "View employees", "People", SCOPED),
    Permission("employees.manage", "Manage employees", "People"),
    Permission("employees.read_compensation", "View compensation data", "People", (Scope.OWN, Scope.ALL)),
    Permission("revenue.read", "View attributed revenue", "People", (Scope.OWN, Scope.ALL)),
    Permission("comp_formulas.read", "View salary formulas", "People", (Scope.OWN, Scope.ALL)),
    Permission("comp_formulas.manage", "Manage salary formulas", "People"),
    Permission("salary.read", "View salary statements", "People", (Scope.OWN, Scope.ALL)),
    Permission("salary.adjust", "Add salary adjustments", "People"),
    Permission("salary.close_period", "Close salary periods", "People"),
    Permission("salary.reopen_period", "Reopen salary periods", "People"),
    Permission("salary.configure_cycle", "Configure salary cycle", "People"),
    # Delivery (Phase 4-5)
    Permission("projects.read", "View projects", "Projects", PROJECT_OR_ALL),
    Permission("projects.manage", "Manage projects", "Projects", PROJECT_OR_ALL),
    Permission("projects.read_financials", "View project financials", "Projects", ALL_ONLY),
    Permission("tasks.manage", "Manage tasks", "Projects", PROJECT_OR_ALL),
    Permission("tasks.update_own", "Update own tasks", "Projects", SCOPED),
    Permission("calendar.manage.company", "Manage company calendar", "Calendar"),
    Permission("calendar.manage.team", "Manage team calendars", "Calendar", PROJECT_OR_ALL),
    Permission("leave.approve", "Approve leave", "Calendar", PROJECT_OR_ALL),
    # Bidding analytics (read live from the Google Sheets; docs/bidding-analytics-plan.md)
    Permission("bidding.read", "View bidding analytics and job list", "Bidding", (Scope.OWN, Scope.ALL)),
    Permission("bidding.manage", "Manage bidding sources and profile names", "Bidding"),
]

PERMISSIONS: dict[str, Permission] = {p.key: p for p in _DEFINITIONS}


def get_permission(key: str) -> Permission:
    try:
        return PERMISSIONS[key]
    except KeyError as exc:  # programming error, not user input
        raise KeyError(f"Unknown permission {key!r}") from exc
