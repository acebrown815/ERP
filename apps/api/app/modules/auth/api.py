"""Public facade of the auth module."""

from app.modules.auth.deps import CurrentUser, current_user, require, require_any
from app.modules.auth.service import create_user, get_user, get_user_by_email

__all__ = ["CurrentUser", "create_user", "current_user", "get_user", "get_user_by_email", "require", "require_any"]
