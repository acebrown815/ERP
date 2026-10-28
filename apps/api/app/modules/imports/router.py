from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ValidationFailed, field_error
from app.modules.auth.api import CurrentUser, require
from app.modules.imports import service

router = APIRouter(prefix="/imports", tags=["imports"])

Entity = Literal["parties", "employees", "projects"]
MAX_BYTES = 5 * 1024 * 1024


@router.get("/{entity}/template")
async def template(entity: Entity, _: CurrentUser = Depends(require("imports.manage"))) -> Response:
    return Response(
        service.template(entity),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{entity}-template.csv"'},
    )


@router.post("/{entity}")
async def run_import(
    entity: Entity,
    file: UploadFile = File(...),
    dry_run: bool = Form(default=True),
    user: CurrentUser = Depends(require("imports.manage")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValidationFailed("File too large", errors=[field_error("file", "Maximum 5 MB")])
    result = await service.run(session, actor_id=user.id, entity=entity, content=content, dry_run=dry_run)
    return asdict(result)
