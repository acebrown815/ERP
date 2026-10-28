"""Transactional outbox: events are written in the same transaction as the change that caused them
and processed asynchronously by the worker (`python -m app.worker`)."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import BigInteger, Identity, Index, String, Text, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

log = structlog.get_logger()

Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]
_handlers: dict[str, list[Handler]] = {}

MAX_ATTEMPTS = 10


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_events_pending", "available_at", postgresql_where=text("processed_at IS NULL")),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    available_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


def on_event(event_type: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        _handlers.setdefault(event_type, []).append(fn)
        return fn

    return register


def emit(session: AsyncSession, event_type: str, payload: dict[str, Any]) -> None:
    """Queue an event. It becomes visible to the worker only if the caller's transaction commits."""
    session.add(OutboxEvent(event_type=event_type, payload=payload))


async def process_batch(sessionmaker: async_sessionmaker[AsyncSession], batch_size: int = 50) -> int:
    """Process up to `batch_size` due events. Each event runs in its own transaction."""
    processed = 0
    for _ in range(batch_size):
        async with sessionmaker() as session, session.begin():
            event = (
                await session.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.processed_at.is_(None), OutboxEvent.available_at <= func.now())
                    .order_by(OutboxEvent.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if event is None:
                break
            try:
                async with session.begin_nested():
                    for handler in _handlers.get(event.event_type, []):
                        await handler(session, event.payload)
                event.processed_at = datetime.now().astimezone()
            except Exception as exc:  # retried with exponential backoff
                event.attempts += 1
                event.last_error = repr(exc)[:2000]
                delay = timedelta(seconds=min(2**event.attempts, 3600))
                event.available_at = datetime.now().astimezone() + delay
                if event.attempts >= MAX_ATTEMPTS:
                    event.processed_at = datetime.now().astimezone()
                log.warning("outbox.handler_failed", event_id=event.id, type=event.event_type, error=repr(exc))
            processed += 1
    return processed
