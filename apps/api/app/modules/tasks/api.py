"""Public facade of the tasks module."""

from app.modules.tasks.models import Task
from app.modules.tasks.service import progress

__all__ = ["Task", "progress"]
