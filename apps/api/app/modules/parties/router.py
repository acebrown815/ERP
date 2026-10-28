import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NotFound
from app.core.pagination import Page, PageParams, page_params, paginate
from app.modules.auth.api import CurrentUser, require
from app.modules.parties import service
from app.modules.projects import api as projects
from app.modules.rbac.api import Scope

router = APIRouter(tags=["parties"])

Kind = Literal["customer", "supplier", "other"]


class PartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    kind: str
    subtype_category_id: uuid.UUID | None
    subtype_other_text: str | None
    organization_id: uuid.UUID | None
    name: str
    contact_name: str | None
    email: str | None
    phone: str | None
    website: str | None
    address: dict[str, Any]
    default_currency: str | None
    payment_details: dict[str, Any]
    notes: str | None
    is_active: bool
    created_at: datetime
    version: int


class PartyFields(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact_name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    website: str | None = Field(default=None, max_length=200)
    address: dict[str, str] = {}
    default_currency: str | None = Field(default=None, max_length=10)
    payment_details: dict[str, str] = {}
    notes: str | None = Field(default=None, max_length=5000)
    subtype_category_id: uuid.UUID | None = None
    subtype_other_text: str | None = Field(default=None, max_length=120)
    organization_id: uuid.UUID | None = None


class PartyCreateIn(PartyFields):
    kind: Kind


class PartyUpdateIn(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    website: str | None = Field(default=None, max_length=200)
    address: dict[str, str] | None = None
    default_currency: str | None = Field(default=None, max_length=10)
    payment_details: dict[str, str] | None = None
    notes: str | None = Field(default=None, max_length=5000)
    subtype_category_id: uuid.UUID | None = None
    subtype_other_text: str | None = Field(default=None, max_length=120)
    organization_id: uuid.UUID | None = None
    is_active: bool | None = None


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    legal_name: str
    notes: str | None


class OrganizationIn(BaseModel):
    legal_name: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


async def _visible_ids(session: AsyncSession, user: CurrentUser) -> set[uuid.UUID] | None:
    """None = everything; otherwise customers of the user's projects."""
    if user.scope_for("parties.read") == Scope.ALL:
        return None
    return await projects.customer_ids_for(session, await projects.visible_project_ids(session, user))


@router.get("/parties", response_model=Page[PartyOut])
async def list_parties(
    params: PageParams = Depends(page_params),
    kind: Kind | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    is_active: bool | None = None,
    user: CurrentUser = Depends(require("parties.read", Scope.PROJECT)),
    session: AsyncSession = Depends(get_session),
) -> Page[PartyOut]:
    stmt = service.list_stmt(kind=kind, q=q, is_active=is_active, only_ids=await _visible_ids(session, user))
    rows, total = await paginate(session, stmt, params)
    return Page(
        items=[PartyOut.model_validate(r) for r in rows], total=total, page=params.page, page_size=params.page_size
    )


@router.get("/parties/{party_id}", response_model=PartyOut)
async def get_party(
    party_id: uuid.UUID,
    user: CurrentUser = Depends(require("parties.read", Scope.PROJECT)),
    session: AsyncSession = Depends(get_session),
) -> Any:
    party = await service.get(session, party_id, kinds=("customer", "supplier", "other"))
    visible = await _visible_ids(session, user)
    if visible is not None and party.id not in visible:
        raise NotFound("Party not found")
    return party


@router.post("/parties", response_model=PartyOut, status_code=201)
async def create_party(
    body: PartyCreateIn,
    actor: CurrentUser = Depends(require("parties.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    party = await service.create(session, actor_id=actor.id, kind=body.kind, data=body.model_dump(exclude={"kind"}))
    await session.commit()
    return party


@router.patch("/parties/{party_id}", response_model=PartyOut)
async def update_party(
    party_id: uuid.UUID,
    body: PartyUpdateIn,
    actor: CurrentUser = Depends(require("parties.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    party = await service.update(
        session,
        actor_id=actor.id,
        party_id=party_id,
        version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version"}),
        kinds=("customer", "supplier", "other"),
    )
    await session.commit()
    return party


@router.get("/organizations", response_model=list[OrganizationOut])
async def list_organizations(
    q: str | None = None,
    _: CurrentUser = Depends(require("parties.read", Scope.PROJECT)),
    session: AsyncSession = Depends(get_session),
) -> Any:
    return await service.list_organizations(session, q)


@router.post("/organizations", response_model=OrganizationOut, status_code=201)
async def create_organization(
    body: OrganizationIn,
    actor: CurrentUser = Depends(require("parties.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    org = await service.create_organization(session, actor_id=actor.id, legal_name=body.legal_name, notes=body.notes)
    await session.commit()
    return org
