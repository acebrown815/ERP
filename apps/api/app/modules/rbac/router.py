import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.auth.api import CurrentUser, require
from app.modules.rbac import service
from app.modules.rbac.permissions import PERMISSIONS

router = APIRouter(tags=["roles"])


class PermissionOut(BaseModel):
    key: str
    label: str
    group: str
    scopes: list[str]


class RoleOut(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    is_system: bool
    grants_all: bool
    grants: dict[str, str]
    user_count: int


class RoleCreateIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,49}$")
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    grants: dict[str, str] = {}


class RoleUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    grants: dict[str, str] | None = None


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(_: CurrentUser = Depends(require("roles.manage"))) -> list[PermissionOut]:
    return [
        PermissionOut(key=p.key, label=p.label, group=p.group, scopes=[s.value for s in p.scopes])
        for p in PERMISSIONS.values()
    ]


async def _role_out(session: AsyncSession, role_id: uuid.UUID) -> RoleOut:
    for role, grants, count in await service.list_roles(session):
        if role.id == role_id:
            return RoleOut(
                id=role.id,
                key=role.key,
                name=role.name,
                description=role.description,
                is_system=role.is_system,
                grants_all=role.grants_all,
                grants={k: v.value for k, v in grants.items()},
                user_count=count,
            )
    raise AssertionError("role vanished")


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    _: CurrentUser = Depends(require("roles.manage")), session: AsyncSession = Depends(get_session)
) -> list[RoleOut]:
    return [
        RoleOut(
            id=r.id,
            key=r.key,
            name=r.name,
            description=r.description,
            is_system=r.is_system,
            grants_all=r.grants_all,
            grants={k: v.value for k, v in g.items()},
            user_count=c,
        )
        for r, g, c in await service.list_roles(session)
    ]


@router.post("/roles", response_model=RoleOut, status_code=201)
async def create_role(
    body: RoleCreateIn,
    actor: CurrentUser = Depends(require("roles.manage")),
    session: AsyncSession = Depends(get_session),
) -> RoleOut:
    role = await service.create_role(
        session, actor_id=actor.id, key=body.key, name=body.name, description=body.description, grants=body.grants
    )
    await session.commit()
    return await _role_out(session, role.id)


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: uuid.UUID,
    body: RoleUpdateIn,
    actor: CurrentUser = Depends(require("roles.manage")),
    session: AsyncSession = Depends(get_session),
) -> RoleOut:
    await service.update_role(
        session, actor_id=actor.id, role_id=role_id, name=body.name, description=body.description, grants=body.grants
    )
    await session.commit()
    return await _role_out(session, role_id)


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(
    role_id: uuid.UUID,
    actor: CurrentUser = Depends(require("roles.manage")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await service.delete_role(session, actor_id=actor.id, role_id=role_id)
    await session.commit()
    return Response(status_code=204)
