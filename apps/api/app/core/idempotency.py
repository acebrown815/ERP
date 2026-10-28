"""Idempotency-Key support: a retried or double-submitted request returns the first response
instead of performing the action twice."""

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import ForeignKey, Integer, String, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.errors import Conflict, ValidationFailed, field_error

HEADER = "Idempotency-Key"


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(500))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


async def run_idempotent(
    request: Request,
    session: AsyncSession,
    user_id: uuid.UUID,
    body: Any,
    action: Callable[[], Awaitable[Any]],
    *,
    required: bool = False,
    status_code: int = 200,
) -> Any:
    """Run `action` once per (user, Idempotency-Key). `action` must not commit; this function commits.

    The key row is inserted in the same transaction as the action, so the action and the stored
    response commit together. A concurrent duplicate blocks on the key row and then replays.
    """
    key = request.headers.get(HEADER)
    if not key:
        if required:
            raise ValidationFailed(
                "Idempotency-Key header is required", errors=[field_error(HEADER, "required", "missing")]
            )
        result = await action()
        await session.commit()
        return result

    request_hash = hashlib.sha256(
        json.dumps([request.method, request.url.path, jsonable_encoder(body)], sort_keys=True).encode()
    ).hexdigest()

    inserted = (
        await session.execute(
            insert(IdempotencyKey)
            .values(user_id=user_id, key=key, method=request.method, path=request.url.path, request_hash=request_hash)
            .on_conflict_do_nothing()
            .returning(IdempotencyKey.key)
        )
    ).scalar_one_or_none()

    if inserted is None:
        await session.rollback()
        existing = (
            await session.execute(
                select(IdempotencyKey).where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
            )
        ).scalar_one()
        if existing.request_hash != request_hash:
            raise Conflict("Idempotency-Key was already used for a different request")
        if existing.status_code is None:
            raise Conflict("A request with this Idempotency-Key is still in progress")
        return JSONResponse(
            existing.response_body, status_code=existing.status_code, headers={"Idempotent-Replayed": "true"}
        )

    result = await action()
    encoded = jsonable_encoder(result)
    record = await session.get(IdempotencyKey, (user_id, key))
    assert record is not None
    record.status_code = status_code
    record.response_body = encoded
    await session.commit()
    return result
