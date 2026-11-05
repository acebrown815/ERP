import uuid
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PreconditionFailed, ValidationFailed, field_error
from app.core.numbering import next_number
from app.modules.audit import api as audit
from app.modules.categories import api as categories
from app.modules.parties.models import NUMBER_PREFIX, Organization, Party
from app.modules.settings import api as settings

EDITABLE = (
    "name",
    "contact_name",
    "email",
    "phone",
    "website",
    "address",
    "default_currency",
    "payment_details",
    "notes",
    "subtype_category_id",
    "subtype_other_text",
    "organization_id",
)


def _snapshot(p: Party) -> dict[str, Any]:
    return {k: getattr(p, k) for k in (*EDITABLE, "kind", "is_active")}


async def get(session: AsyncSession, party_id: uuid.UUID, *, kinds: tuple[str, ...] | None = None) -> Party:
    party = await session.get(Party, party_id)
    if party is None or (kinds and party.kind not in kinds):
        raise NotFound("Party not found")
    return party


async def names(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    return dict((await session.execute(select(Party.id, Party.name).where(Party.id.in_(ids)))).all())


def list_stmt(
    *, kind: str | None, q: str | None, is_active: bool | None, only_ids: set[uuid.UUID] | None = None
) -> Select[Party]:
    stmt = select(Party).order_by(func.lower(Party.name))
    stmt = stmt.where(Party.kind == kind) if kind else stmt.where(Party.kind != "employee")
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Party.name.ilike(like), Party.number.ilike(like), Party.email.ilike(like)))
    if is_active is not None:
        stmt = stmt.where(Party.is_active.is_(is_active))
    if only_ids is not None:
        stmt = stmt.where(Party.id.in_(only_ids))
    return stmt


async def _validate(session: AsyncSession, kind: str, data: dict[str, Any]) -> None:
    if data.get("default_currency"):
        data["default_currency"] = data["default_currency"].upper()
        cur = await settings.get_currency(session, data["default_currency"])
        if not cur.is_active:
            raise ValidationFailed("Inactive currency", errors=[field_error("default_currency", "Currency inactive")])
    if kind == "other":
        if data.get("subtype_category_id"):
            await categories.validate_choice(
                session,
                group_key="party_subtype",
                category_id=data["subtype_category_id"],
                other_text=data.get("subtype_other_text"),
                field="subtype_category_id",
                other_field="subtype_other_text",
            )
    else:
        data["subtype_category_id"] = None
        data["subtype_other_text"] = None
    if data.get("organization_id") and await session.get(Organization, data["organization_id"]) is None:
        raise ValidationFailed("Unknown organization", errors=[field_error("organization_id", "Not found")])


async def create(session: AsyncSession, *, actor_id: uuid.UUID | None, kind: str, data: dict[str, Any]) -> Party:
    await _validate(session, kind, data)
    party = Party(
        kind=kind,
        number=await next_number(session, NUMBER_PREFIX[kind], None),
        created_by=actor_id,
        updated_by=actor_id,
        **{k: v for k, v in data.items() if k in EDITABLE},
    )
    session.add(party)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="party.created",
        entity_type="party",
        entity_id=party.id,
        after=_snapshot(party),
    )
    return party


async def update(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    party_id: uuid.UUID,
    version: int | None,
    changes: dict[str, Any],
    kinds: tuple[str, ...] | None = None,
) -> Party:
    party = await get(session, party_id, kinds=kinds)
    if version is not None and party.version != version:
        raise PreconditionFailed()
    before = _snapshot(party)
    merged = {**{k: getattr(party, k) for k in EDITABLE}, **changes}
    await _validate(session, party.kind, merged)
    for k in EDITABLE:
        setattr(party, k, merged[k])
    if "is_active" in changes:
        party.is_active = changes["is_active"]
    party.version += 1
    party.updated_by = actor_id
    await session.flush()
    b, a = audit.diff(before, _snapshot(party))
    if a:
        await audit.record(
            session,
            actor_id=actor_id,
            action="party.updated",
            entity_type="party",
            entity_id=party.id,
            before=b,
            after=a,
        )
    return party


async def find_by_name(session: AsyncSession, kind: str, name: str) -> Party | None:
    return (
        await session.execute(
            select(Party).where(Party.kind == kind, func.lower(Party.name) == name.strip().lower()).limit(1)
        )
    ).scalar_one_or_none()


# ---- organizations ---------------------------------------------------------------------------------


async def list_organizations(session: AsyncSession, q: str | None) -> list[Organization]:
    stmt = select(Organization).order_by(func.lower(Organization.legal_name)).limit(200)
    if q:
        stmt = stmt.where(Organization.legal_name.ilike(f"%{q.strip()}%"))
    return list((await session.execute(stmt)).scalars())


async def create_organization(
    session: AsyncSession, *, actor_id: uuid.UUID, legal_name: str, notes: str | None
) -> Organization:
    exists = (
        await session.execute(
            select(Organization.id).where(func.lower(Organization.legal_name) == legal_name.strip().lower())
        )
    ).first()
    if exists:
        raise Conflict("An organization with this name already exists")
    org = Organization(legal_name=legal_name.strip(), notes=notes, created_by=actor_id, updated_by=actor_id)
    session.add(org)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="organization.created",
        entity_type="organization",
        entity_id=org.id,
        after={"legal_name": org.legal_name},
    )
    return org


async def find_by_number(session: AsyncSession, number: str) -> Party | None:
    return (await session.execute(select(Party).where(Party.number == number.strip().upper()))).scalar_one_or_none()
