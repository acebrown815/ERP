"""Public facade of the projects module."""

from app.modules.projects.models import PRIORITIES, Milestone, Project
from app.modules.projects.service import (
    can_manage,
    can_manage_id,
    create,
    customer_ids_for,
    default_split,
    ensure_visible,
    find_by_name,
    get,
    get_milestone,
    is_team_member,
    list_stmt,
    members,
    milestones,
    names,
    team_ids,
    visible_project_ids,
)

__all__ = [
    "PRIORITIES",
    "Milestone",
    "Project",
    "can_manage",
    "can_manage_id",
    "create",
    "customer_ids_for",
    "default_split",
    "ensure_visible",
    "find_by_name",
    "get",
    "get_milestone",
    "is_team_member",
    "list_stmt",
    "members",
    "milestones",
    "names",
    "team_ids",
    "visible_project_ids",
]
