"""Registrations this module makes with shared services at startup."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attachments import api as attachments
from app.modules.auth.api import CurrentUser
from app.modules.projects import api as projects
from app.modules.rbac.api import Scope
from app.modules.tasks.models import Task


async def _project_of(session: AsyncSession, task_id: str) -> Task | None:
    import uuid

    try:
        return await session.get(Task, uuid.UUID(task_id))
    except ValueError:
        return None


async def _can_read(session: AsyncSession, user: CurrentUser, entity_id: str) -> bool:
    task = await _project_of(session, entity_id)
    if task is None:
        return False
    scope = user.scope_for("projects.read")
    return scope == Scope.ALL or (scope is not None and await projects.is_team_member(session, user, task.project_id))


async def _can_write(session: AsyncSession, user: CurrentUser, entity_id: str) -> bool:
    task = await _project_of(session, entity_id)
    if task is None:
        return False
    return user.can("tasks.manage", Scope.ALL) or (
        user.can("tasks.manage") and await projects.is_team_member(session, user, task.project_id)
    )


def setup() -> None:
    attachments.register_entity("task", can_read=_can_read, can_write=_can_write)
