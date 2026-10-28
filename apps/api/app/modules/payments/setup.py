"""Registrations this module makes with shared services at startup."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attachments import api as attachments
from app.modules.auth.api import CurrentUser


async def _can_read(_: AsyncSession, user: CurrentUser, __: str) -> bool:
    return user.can("payments.create") or user.can("reports.financial")


async def _can_write(_: AsyncSession, user: CurrentUser, __: str) -> bool:
    return user.can("payments.create")


def setup() -> None:
    attachments.register_entity("payment_entry", can_read=_can_read, can_write=_can_write)
