"""Human-readable document numbers, e.g. PE-2026-00042 (yearly) or CUS-00042 (continuous)."""

from datetime import date

from sqlalchemy import Integer, String, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NumberSeries(Base):
    __tablename__ = "number_series"

    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)  # 0 = continuous series
    last_value: Mapped[int] = mapped_column(Integer, default=0)


async def next_number(session: AsyncSession, prefix: str, on: date | None, width: int = 5) -> str:
    """Atomically reserve the next number. Pass `on=None` for a series that never resets.

    Gaps are possible if the transaction rolls back.
    """
    year = on.year if on else 0
    value = (
        await session.execute(
            text(
                "INSERT INTO number_series (key, year, last_value) VALUES (:key, :year, 1) "
                "ON CONFLICT (key, year) DO UPDATE SET last_value = number_series.last_value + 1 "
                "RETURNING last_value"
            ),
            {"key": prefix, "year": year},
        )
    ).scalar_one()
    return f"{prefix}-{on.year}-{value:0{width}d}" if on else f"{prefix}-{value:0{width}d}"
