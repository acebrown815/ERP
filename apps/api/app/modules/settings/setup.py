"""Registrations this module makes with shared services at startup."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attachments import api as attachments
from app.modules.auth.api import CurrentUser


async def _can_read(_: AsyncSession, user: CurrentUser, __: str) -> bool:
    return True  # company documents (logo, registration papers) are visible to every signed-in user


async def _can_write(_: AsyncSession, user: CurrentUser, __: str) -> bool:
    return user.can("settings.manage")


def setup() -> None:
    attachments.register_entity("company_settings", can_read=_can_read, can_write=_can_write)
