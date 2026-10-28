import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.pagination import Page, PageParams, page_params, paginate
from app.modules.audit.models import AuditLog
from app.modules.audit.service import verify_chain
from app.modules.auth.api import CurrentUser, require

router = APIRouter(prefix="/audit-logs", tags=["audit"])


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    actor_user_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_id: str | None
    ip: str | None

    @field_validator("ip", mode="before")
    @classmethod
    def _ip_to_str(cls, value: object) -> str | None:  # INET comes back as an ipaddress object
        return None if value is None else str(value)


class ChainStatus(BaseModel):
    ok: bool
    first_broken_id: int | None
    rows_checked: int


@router.get("", response_model=Page[AuditLogOut])
async def list_audit_logs(
    params: PageParams = Depends(page_params),
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    action: Annotated[str | None, Query(description="Exact action or prefix ending in '.', e.g. 'category.'")] = None,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    _: CurrentUser = Depends(require("audit.read")),
    session: AsyncSession = Depends(get_session),
) -> Page[AuditLogOut]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action) if action.endswith(".") else AuditLog.action == action)
    if date_from:
        stmt = stmt.where(AuditLog.at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.at < date_to)
    rows, total = await paginate(session, stmt, params)
    return Page(
        items=[AuditLogOut.model_validate(r) for r in rows], total=total, page=params.page, page_size=params.page_size
    )


@router.get("/verify", response_model=ChainStatus)
async def verify(
    _: CurrentUser = Depends(require("audit.read")), session: AsyncSession = Depends(get_session)
) -> ChainStatus:
    ok, broken, checked = await verify_chain(session)
    return ChainStatus(ok=ok, first_broken_id=broken, rows_checked=checked)
