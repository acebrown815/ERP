"""Registrations this module makes with shared services at startup."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lookup
from app.modules.attachments import api as attachments
from app.modules.auth.api import CurrentUser
from app.modules.parties.service import names


async def _can_read(_: AsyncSession, user: CurrentUser, __: str) -> bool:
    return user.can("parties.read")


async def _can_write(_: AsyncSession, user: CurrentUser, __: str) -> bool:
    return user.can("parties.manage")


def setup() -> None:
    lookup.register("party", names)
    attachments.register_entity("party", can_read=_can_read, can_write=_can_write)
