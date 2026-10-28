"""Public facade of the RBAC module."""

from app.modules.rbac.permissions import PERMISSIONS, Permission, Scope, get_permission
from app.modules.rbac.service import (
    admin_user_ids,
    assign_roles_system,
    effective_grants,
    role_by_key,
    roles_by_user,
    seed_default_roles,
    set_user_roles,
    user_role_ids,
)

__all__ = [
    "PERMISSIONS",
    "Permission",
    "Scope",
    "admin_user_ids",
    "assign_roles_system",
    "effective_grants",
    "get_permission",
    "role_by_key",
    "roles_by_user",
    "seed_default_roles",
    "set_user_roles",
    "user_role_ids",
]
