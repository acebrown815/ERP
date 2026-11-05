import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import Forbidden
from app.core.idempotency import run_idempotent
from app.modules.auth.api import CurrentUser, current_user
from app.modules.categories import service
from app.modules.categories.groups import GROUPS
from app.modules.categories.models import Category

router = APIRouter(prefix="/categories", tags=["categories"])


class GroupOut(BaseModel):
    key: str
    label: str
    domain: str
    description: str
    permission: str
    can_manage: bool
    config_schema: dict[str, str]
    config_choices: dict[str, dict[str, str]]
    system_locked: list[str]


class CategoryOut(BaseModel):
    id: uuid.UUID
    group_key: str
    system_key: str | None
    parent_id: uuid.UUID | None
    name: str
    path: str
    description: str | None
    config: dict[str, Any]
    is_system: bool
    is_other: bool
    is_active: bool
    sort_order: int
    merged_into_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    version: int


class CategoryCreateIn(BaseModel):
    group_key: str
    name: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=2000)
    config: dict[str, Any] = {}
    sort_order: int | None = None


class CategoryUpdateIn(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=2000)
    config: dict[str, Any] | None = None
    sort_order: int | None = None


class MergeIn(BaseModel):
    target_id: uuid.UUID


def _ensure_can_manage(user: CurrentUser, group_key: str) -> None:
    group = service.get_group(group_key)
    if not user.can(group.permission):
        raise Forbidden(f"Requires permission {group.permission}")


async def _out(session: AsyncSession, categories: list[Category]) -> list[CategoryOut]:
    paths = await service.paths(session, categories)
    return [
        CategoryOut(
            id=c.id,
            group_key=c.group_key,
            system_key=c.system_key,
            parent_id=c.parent_id,
            name=c.name,
            path=paths.get(c.id, c.name),
            description=c.description,
            config=c.config,
            is_system=c.is_system,
            is_other=c.system_key == "other",
            is_active=c.is_active,
            sort_order=c.sort_order,
            merged_into_id=c.merged_into_id,
            created_at=c.created_at,
            updated_at=c.updated_at,
            version=c.version,
        )
        for c in categories
    ]


async def _one(session: AsyncSession, category: Category) -> CategoryOut:
    await session.refresh(category)
    return (await _out(session, [category]))[0]


# What a hired manager's screens need to label things. Finance groups and their ledger settings stay hidden.
HIRE_GROUPS = {"project_type", "task_category", "event_type", "payment_method", "payment_purpose"}


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(user: CurrentUser = Depends(current_user)) -> list[GroupOut]:
    return [
        GroupOut(
            key=g.key,
            label=g.label,
            domain=g.domain,
            description=g.description,
            permission=g.permission,
            can_manage=user.can(g.permission),
            config_schema=g.config_schema,
            config_choices=g.config_choices,
            system_locked=list(g.system_locked),
        )
        for g in GROUPS.values()
        if not user.restricted or g.key in HIRE_GROUPS
    ]


@router.get("", response_model=list[CategoryOut])
async def list_categories(
    group: Annotated[str | None, Query(alias="group")] = None,
    include_inactive: bool = False,
    q: Annotated[str | None, Query(max_length=100)] = None,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[CategoryOut]:
    rows = await service.list_categories(session, group_key=group, include_inactive=include_inactive, q=q)
    if user.restricted:
        rows = [r for r in rows if r.group_key in HIRE_GROUPS]
        return [c.model_copy(update={"config": {}}) for c in await _out(session, rows)]
    return await _out(session, rows)


@router.get("/{category_id}", response_model=CategoryOut)
async def get_category(
    category_id: uuid.UUID, _: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> CategoryOut:
    return (await _out(session, [await service.get(session, category_id)]))[0]


@router.post("", response_model=CategoryOut, status_code=201)
async def create_category(
    body: CategoryCreateIn,
    request: Request,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    _ensure_can_manage(user, body.group_key)

    async def action() -> CategoryOut:
        category = await service.create(session, actor_id=user.id, **body.model_dump())
        return (await _out(session, [category]))[0]

    return await run_idempotent(request, session, user.id, body.model_dump(mode="json"), action, status_code=201)


@router.patch("/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: uuid.UUID,
    body: CategoryUpdateIn,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> CategoryOut:
    _ensure_can_manage(user, (await service.get(session, category_id)).group_key)
    category = await service.update_category(
        session,
        actor_id=user.id,
        category_id=category_id,
        version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version"}),
    )
    await session.commit()
    return await _one(session, category)


@router.post("/{category_id}/deactivate", response_model=CategoryOut)
async def deactivate(
    category_id: uuid.UUID, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> CategoryOut:
    _ensure_can_manage(user, (await service.get(session, category_id)).group_key)
    category = await service.set_active(session, actor_id=user.id, category_id=category_id, active=False)
    await session.commit()
    return await _one(session, category)


@router.post("/{category_id}/activate", response_model=CategoryOut)
async def activate(
    category_id: uuid.UUID, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> CategoryOut:
    _ensure_can_manage(user, (await service.get(session, category_id)).group_key)
    category = await service.set_active(session, actor_id=user.id, category_id=category_id, active=True)
    await session.commit()
    return await _one(session, category)


@router.post("/{category_id}/merge", response_model=CategoryOut)
async def merge(
    category_id: uuid.UUID,
    body: MergeIn,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> CategoryOut:
    _ensure_can_manage(user, (await service.get(session, category_id)).group_key)
    category = await service.merge(session, actor_id=user.id, source_id=category_id, target_id=body.target_id)
    await session.commit()
    return await _one(session, category)


@router.post("/{category_id}/unmerge", response_model=CategoryOut)
async def unmerge(
    category_id: uuid.UUID, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> CategoryOut:
    _ensure_can_manage(user, (await service.get(session, category_id)).group_key)
    category = await service.unmerge(session, actor_id=user.id, category_id=category_id)
    await session.commit()
    return await _one(session, category)


@router.delete("/{category_id}", status_code=204)
async def delete_category(
    category_id: uuid.UUID, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> Response:
    _ensure_can_manage(user, (await service.get(session, category_id)).group_key)
    await service.delete(session, actor_id=user.id, category_id=category_id)
    await session.commit()
    return Response(status_code=204)
