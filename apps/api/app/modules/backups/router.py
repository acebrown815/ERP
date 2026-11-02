"""Settings → Backups: list, create, upload, download, delete and restore backup files (Administrators)."""

from dataclasses import asdict
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ValidationFailed, field_error
from app.core.security import verify_password
from app.modules.audit import api as audit
from app.modules.auth.api import CurrentUser, get_user, require
from app.modules.backups import service

router = APIRouter(prefix="/backups", tags=["backups"])


class BackupOut(BaseModel):
    name: str
    kind: Literal["auto", "manual", "upload", "pre-restore"]
    created_at: datetime
    size: int
    schema_version: str
    rows: int
    files: int


class JobOut(BaseModel):
    kind: Literal["backup", "restore"]
    state: Literal["running", "succeeded", "failed"]
    started_at: datetime
    finished_at: datetime | None
    by: str | None
    file: str | None
    message: str | None


class BackupsOut(BaseModel):
    items: list[BackupOut]
    job: JobOut | None
    keep_days: int


class RestoreIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _job_out(job: service.Job | None) -> JobOut | None:
    return JobOut(**asdict(job)) if job else None


@router.get("", response_model=BackupsOut)
async def list_backups(_: CurrentUser = Depends(require("backups.manage"))) -> BackupsOut:
    return BackupsOut(
        items=[BackupOut(**asdict(b)) for b in service.list_backups()],
        job=_job_out(service.read_job()),
        keep_days=get_settings().backups_keep_days,
    )


@router.get("/job", response_model=JobOut | None)
async def current_job(_: CurrentUser = Depends(require("backups.manage"))) -> JobOut | None:
    return _job_out(service.read_job())


@router.post("", response_model=JobOut, status_code=202)
async def create_backup(
    user: CurrentUser = Depends(require("backups.manage")), session: AsyncSession = Depends(get_session)
) -> JobOut:
    """Start a backup in the background; follow it with GET /backups/job."""
    job = service.start_backup(by=user.email)
    await audit.record(session, actor_id=user.id, action="backup.started", entity_type="backup")
    await session.commit()
    return JobOut(**asdict(job))


@router.post("/upload", response_model=BackupOut, status_code=201)
async def upload_backup(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require("backups.manage")),
    session: AsyncSession = Depends(get_session),
) -> BackupOut:
    info = await service.save_upload(file)
    await audit.record(
        session,
        actor_id=user.id,
        action="backup.uploaded",
        entity_type="backup",
        entity_id=info.name,
        after={"original_name": file.filename, "size": info.size, "created_at": info.created_at.isoformat()},
    )
    await session.commit()
    return BackupOut(**asdict(info))


@router.get("/{name}/download")
async def download_backup(
    name: str, user: CurrentUser = Depends(require("backups.manage")), session: AsyncSession = Depends(get_session)
) -> FileResponse:
    path = service.path_of(name)
    await audit.record(session, actor_id=user.id, action="backup.downloaded", entity_type="backup", entity_id=name)
    await session.commit()
    return FileResponse(path, media_type="application/zip", filename=name)


@router.delete("/{name}", status_code=204)
async def delete_backup(
    name: str, user: CurrentUser = Depends(require("backups.manage")), session: AsyncSession = Depends(get_session)
) -> Response:
    service.delete(name)
    await audit.record(session, actor_id=user.id, action="backup.deleted", entity_type="backup", entity_id=name)
    await session.commit()
    return Response(status_code=204)


@router.post("/{name}/restore", response_model=JobOut, status_code=202)
async def restore_backup(
    name: str,
    body: RestoreIn,
    user: CurrentUser = Depends(require("backups.manage")),
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    """Replace all data with the backup. Needs the caller's password. Runs in the background and signs
    everyone out when it finishes; the data before the restore is kept as a "pre-restore" backup."""
    account = await get_user(session, user.id)
    if not verify_password(account.password_hash, body.password):
        message = "Password is wrong"
        raise ValidationFailed(message, errors=[field_error("password", message, "wrong_password")])
    job = service.start_restore(name, user_id=user.id, by=user.email)
    return JobOut(**asdict(job))
