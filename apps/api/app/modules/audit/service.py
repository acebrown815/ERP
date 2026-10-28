import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import client_ip_var, request_id_var
from app.modules.audit.models import AuditLog

# Serializes audit writes so the hash chain stays linear; released at commit/rollback.
_CHAIN_LOCK_KEY = 0x41554449  # "AUDI"


def _encode(value: dict[str, Any] | None) -> dict[str, Any] | None:
    # Money must stay exact: Decimal -> str, never float.
    return None if value is None else jsonable_encoder(value, custom_encoder={Decimal: str})


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


def _row_hash(prev_hash: str | None, fields: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash or "").encode() + _canonical(fields)).hexdigest()


def _hashed_fields(row: AuditLog) -> dict[str, Any]:
    return {
        "at": row.at.astimezone(UTC).isoformat(),
        "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "before": row.before,
        "after": row.after,
    }


def diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> tuple[dict | None, dict | None]:
    """Reduce two snapshots to the fields that changed."""
    if before is None or after is None:
        return before, after
    keys = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


async def record(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """Write an audit row in the caller's transaction."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_KEY})
    prev_hash = (
        await session.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))
    ).scalar_one_or_none()

    row = AuditLog(
        at=datetime.now(UTC),
        actor_user_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=_encode(before),
        after=_encode(after),
        request_id=request_id_var.get(),
        ip=client_ip_var.get(),
        prev_hash=prev_hash,
    )
    row.hash = _row_hash(prev_hash, _hashed_fields(row))
    session.add(row)
    await session.flush()
    return row


async def verify_chain(session: AsyncSession) -> tuple[bool, int | None, int]:
    """Recompute the chain. Returns (ok, first_broken_id, rows_checked)."""
    prev: str | None = None
    checked = 0
    result = await session.stream_scalars(select(AuditLog).order_by(AuditLog.id))
    async for row in result:
        checked += 1
        if row.prev_hash != prev or row.hash != _row_hash(prev, _hashed_fields(row)):
            return False, row.id, checked
        prev = row.hash
    return True, None, checked
