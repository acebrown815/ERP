"""Registrations this module makes with shared services at startup."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lookup
from app.modules.attachments import api as attachments
from app.modules.auth.api import CurrentUser
from app.modules.employees.service import for_user, names
from app.modules.rbac.api import Scope


async def _can_read(session: AsyncSession, user: CurrentUser, entity_id: str) -> bool:
    if user.scope_for("employees.read") == Scope.ALL:
        return True
    own = await for_user(session, user.id)
    return own is not None and str(own.id) == entity_id


async def _can_write(_: AsyncSession, user: CurrentUser, __: str) -> bool:
    return user.can("employees.manage")


async def _names(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    return await names(session, ids)


def setup() -> None:
    lookup.register("employee", _names)
    attachments.register_entity("employee", can_read=_can_read, can_write=_can_write)
