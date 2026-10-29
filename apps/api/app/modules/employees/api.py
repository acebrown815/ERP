"""Public facade of the employees module."""

from app.modules.employees.models import Employee
from app.modules.employees.service import (
    active_ids,
    active_in,
    by_ids,
    by_party,
    create,
    create_department,
    department_by_name,
    find_by_email,
    for_user,
    get,
    names,
)

__all__ = [
    "Employee",
    "active_ids",
    "active_in",
    "by_ids",
    "by_party",
    "create",
    "create_department",
    "department_by_name",
    "find_by_email",
    "for_user",
    "get",
    "names",
]
