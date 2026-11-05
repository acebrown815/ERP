"""Registrations this module makes with shared services at startup."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import checks
from app.core.config import get_settings
from app.modules.backups import service


async def _recent(_: AsyncSession) -> tuple[bool, str]:
    return service.recent_backup(production=get_settings().env == "prod")


def setup() -> None:
    checks.register("backup_recent", "A recent backup exists", _recent)
