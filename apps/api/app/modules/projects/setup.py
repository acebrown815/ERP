"""Registrations this module makes with shared services at startup."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lookup
from app.modules.attachments import api as attachments
from app.modules.auth.api import CurrentUser
from app.modules.projects.service import names, visible_project_ids
from app.modules.rbac.api import Scope


async def _can_read(session: AsyncSession, user: CurrentUser, entity_id: str) -> bool:
    scope = user.scope_for("projects.read")
    if scope == Scope.ALL:
        return True
    return scope is not None and entity_id in {str(i) for i in await visible_project_ids(session, user)}


async def _can_write(session: AsyncSession, user: CurrentUser, entity_id: str) -> bool:
    return user.can("projects.manage", Scope.ALL) or (
        user.can("projects.manage") and entity_id in {str(i) for i in await visible_project_ids(session, user)}
    )


async def _names(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    return await names(session, ids)


def setup() -> None:
    lookup.register("project", _names)
    attachments.register_entity("project", can_read=_can_read, can_write=_can_write)
