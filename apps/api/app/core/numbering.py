"""Human-readable document numbers per type and year, e.g. PE-2026-00042."""

from datetime import date

from sqlalchemy import Integer, String, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NumberSeries(Base):
    __tablename__ = "number_series"

    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, default=0)


async def next_number(session: AsyncSession, prefix: str, on: date, width: int = 5) -> str:
    """Atomically reserve the next number. Gaps are possible if the transaction rolls back."""
    value = (
        await session.execute(
            text(
                "INSERT INTO number_series (key, year, last_value) VALUES (:key, :year, 1) "
                "ON CONFLICT (key, year) DO UPDATE SET last_value = number_series.last_value + 1 "
                "RETURNING last_value"
            ),
            {"key": prefix, "year": on.year},
        )
    ).scalar_one()
    return f"{prefix}-{on.year}-{value:0{width}d}"
