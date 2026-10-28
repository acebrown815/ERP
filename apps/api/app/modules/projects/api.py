"""Public facade of the projects module."""

from app.modules.projects.models import Project
from app.modules.projects.service import (
    create,
    customer_ids_for,
    default_split,
    ensure_visible,
    find_by_name,
    get,
    names,
    team_ids,
    visible_project_ids,
)

__all__ = [
    "Project",
    "create",
    "customer_ids_for",
    "default_split",
    "ensure_visible",
    "find_by_name",
    "get",
    "names",
    "team_ids",
    "visible_project_ids",
]
