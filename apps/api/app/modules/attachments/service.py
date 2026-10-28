import mimetypes
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Forbidden, NotFound, ValidationFailed, field_error
from app.modules.attachments.models import Attachment
from app.modules.attachments.storage import get_storage
from app.modules.audit import api as audit
from app.modules.auth.api import CurrentUser

ALLOWED_TYPES: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".webp": {"image/webp"},
    ".gif": {"image/gif"},
    ".txt": {"text/plain"},
    ".csv": {"text/csv", "application/vnd.ms-excel", "text/plain"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
}

# entity_type -> (can_read, can_write). Modules register the record types that accept attachments.
Check = Callable[[AsyncSession, CurrentUser, str], Awaitable[bool]]


@dataclass(frozen=True)
class EntityRule:
    can_read: Check
    can_write: Check


_entities: dict[str, EntityRule] = {}


def register_entity(entity_type: str, *, can_read: Check, can_write: Check) -> None:
    _entities[entity_type] = EntityRule(can_read, can_write)


def _rule(entity_type: str) -> EntityRule:
    rule = _entities.get(entity_type)
    if rule is None:
        raise ValidationFailed(
            "Attachments are not supported here",
            errors=[field_error("entity_type", f"Unknown entity type {entity_type!r}")],
        )
    return rule


def _safe_filename(name: str) -> str:
    base = PurePath(name.replace("\\", "/")).name.strip() or "file"
    return "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"/\\|?*')[:255] or "file"


async def upload(
    session: AsyncSession,
    *,
    user: CurrentUser,
    entity_type: str,
    entity_id: str,
    category_id: uuid.UUID | None,
    file: UploadFile,
) -> Attachment:
    rule = _rule(entity_type)
    if not await rule.can_write(session, user, entity_id):
        raise Forbidden("You cannot attach files to this record")

    filename = _safe_filename(file.filename or "file")
    ext = PurePath(filename).suffix.lower()
    declared = (file.content_type or "").split(";")[0].strip().lower()
    allowed = ALLOWED_TYPES.get(ext)
    if allowed is None or declared not in allowed:
        raise ValidationFailed(
            "File type not allowed",
            errors=[field_error("file", f"Allowed types: {', '.join(sorted(ALLOWED_TYPES))}", "type_not_allowed")],
        )

    attachment_id = uuid.uuid4()
    now = datetime.now(UTC)
    key = f"{now:%Y/%m}/{attachment_id.hex}{ext}"
    size, sha256 = await get_storage().save(key, file, get_settings().attachments_max_bytes)

    row = Attachment(
        id=attachment_id,
        entity_type=entity_type,
        entity_id=entity_id,
        category_id=category_id,
        filename=filename,
        content_type=declared or mimetypes.guess_type(filename)[0] or "",
        size=size,
        sha256=sha256,
        object_key=key,
        uploaded_by=user.id,
    )
    session.add(row)
    await session.flush()
    await audit.record(
        session,
        actor_id=user.id,
        action="attachment.uploaded",
        entity_type=entity_type,
        entity_id=entity_id,
        after={"attachment_id": row.id, "filename": filename, "size": size, "sha256": sha256},
    )
    return row


async def list_for(session: AsyncSession, *, user: CurrentUser, entity_type: str, entity_id: str) -> list[Attachment]:
    if not await _rule(entity_type).can_read(session, user, entity_id):
        raise NotFound("Record not found")
    return list(
        (
            await session.execute(
                select(Attachment)
                .where(
                    Attachment.entity_type == entity_type,
                    Attachment.entity_id == entity_id,
                    Attachment.deleted_at.is_(None),
                )
                .order_by(Attachment.created_at)
            )
        ).scalars()
    )


async def get_for_download(session: AsyncSession, *, user: CurrentUser, attachment_id: uuid.UUID) -> Attachment:
    row = await session.get(Attachment, attachment_id)
    if (
        row is None
        or row.deleted_at is not None
        or not await _rule(row.entity_type).can_read(session, user, row.entity_id)
    ):
        raise NotFound("Attachment not found")
    return row


async def soft_delete(session: AsyncSession, *, user: CurrentUser, attachment_id: uuid.UUID) -> None:
    row = await session.get(Attachment, attachment_id)
    if row is None or row.deleted_at is not None:
        raise NotFound("Attachment not found")
    if not await _rule(row.entity_type).can_write(session, user, row.entity_id):
        raise Forbidden("You cannot remove files from this record")
    row.deleted_at = datetime.now(UTC)
    row.deleted_by = user.id
    await audit.record(
        session,
        actor_id=user.id,
        action="attachment.deleted",
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        before={"attachment_id": row.id, "filename": row.filename},
    )
