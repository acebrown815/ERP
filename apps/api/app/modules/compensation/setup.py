"""Registrations this module makes with shared services at startup."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lookup
from app.modules.compensation.models import CompFormula


async def _names(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = await session.execute(select(CompFormula.id, CompFormula.name).where(CompFormula.id.in_(ids)))
    return dict(rows.all())  # type: ignore[arg-type]


def setup() -> None:
    lookup.register("comp_formula", _names)
