import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.attachments import service
from app.modules.attachments.storage import get_storage
from app.modules.auth.api import CurrentUser, current_user

router = APIRouter(prefix="/attachments", tags=["attachments"])


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_type: str
    entity_id: str
    category_id: uuid.UUID | None
    filename: str
    content_type: str
    size: int
    sha256: str
    uploaded_by: uuid.UUID
    created_at: datetime


@router.post("", response_model=AttachmentOut, status_code=201)
async def upload(
    entity_type: str = Form(...),
    entity_id: str = Form(...),
    category_id: uuid.UUID | None = Form(default=None),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AttachmentOut:
    row = await service.upload(
        session, user=user, entity_type=entity_type, entity_id=entity_id, category_id=category_id, file=file
    )
    await session.commit()
    return AttachmentOut.model_validate(row)


@router.get("", response_model=list[AttachmentOut])
async def list_attachments(
    entity_type: str = Query(),
    entity_id: str = Query(),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AttachmentOut]:
    rows = await service.list_for(session, user=user, entity_type=entity_type, entity_id=entity_id)
    return [AttachmentOut.model_validate(r) for r in rows]


@router.get("/{attachment_id}/download")
async def download(
    attachment_id: uuid.UUID, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> FileResponse:
    row = await service.get_for_download(session, user=user, attachment_id=attachment_id)
    return FileResponse(
        get_storage().path_for(row.object_key),
        media_type=row.content_type,
        filename=row.filename,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.delete("/{attachment_id}", status_code=204)
async def delete(
    attachment_id: uuid.UUID, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> Response:
    await service.soft_delete(session, user=user, attachment_id=attachment_id)
    await session.commit()
    return Response(status_code=204)
