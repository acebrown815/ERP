"""Public facade of the revenue attribution module."""

from app.modules.attribution.models import RevenueAllocation
from app.modules.attribution.service import (
    SplitIn,
    activate,
    active_for_employee,
    cancel,
    compute,
    copy_as_draft,
    employee_project_totals,
    employee_totals,
    for_payment,
    proposal,
    replace_draft,
)

__all__ = [
    "RevenueAllocation",
    "SplitIn",
    "activate",
    "active_for_employee",
    "cancel",
    "compute",
    "copy_as_draft",
    "employee_project_totals",
    "employee_totals",
    "for_payment",
    "proposal",
    "replace_draft",
]
