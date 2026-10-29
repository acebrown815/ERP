import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, NotFound, PreconditionFailed, ValidationFailed, field_error
from app.core.numbering import next_number
from app.modules.audit import api as audit
from app.modules.auth.api import CurrentUser
from app.modules.categories import api as categories
from app.modules.employees import api as employees
from app.modules.parties import api as parties
from app.modules.projects.models import Milestone, Project, ProjectMember
from app.modules.rbac.api import Scope
from app.modules.settings import api as settings

EDITABLE = (
    "name",
    "customer_party_id",
    "manager_employee_id",
    "project_type_category_id",
    "project_type_other_text",
    "description",
    "start_date",
    "deadline",
    "contract_value",
    "budget",
    "priority",
    "completion_override",
    "currency",
    "status",
)


def _snapshot(p: Project) -> dict[str, Any]:
    return {k: getattr(p, k) for k in EDITABLE}


async def get(session: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFound("Project not found")
    return project


async def names(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    return dict((await session.execute(select(Project.id, Project.name).where(Project.id.in_(ids)))).all())


async def members(session: AsyncSession, project_id: uuid.UUID) -> list[ProjectMember]:
    return list((await session.execute(select(ProjectMember).where(ProjectMember.project_id == project_id))).scalars())


async def team_ids(session: AsyncSession, project_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Employees on these projects: members plus managers."""
    if not project_ids:
        return set()
    member = select(ProjectMember.employee_id).where(ProjectMember.project_id.in_(project_ids))
    manager = select(Project.manager_employee_id).where(
        Project.id.in_(project_ids), Project.manager_employee_id.is_not(None)
    )
    return set((await session.execute(member.union(manager))).scalars())


async def visible_project_ids(session: AsyncSession, user: CurrentUser) -> set[uuid.UUID]:
    """Projects the user manages or is a member of (the 'project' permission scope)."""
    employee = await employees.for_user(session, user.id)
    if employee is None:
        return set()
    managed = select(Project.id).where(Project.manager_employee_id == employee.id)
    member = select(ProjectMember.project_id).where(ProjectMember.employee_id == employee.id)
    return set((await session.execute(managed.union(member))).scalars())


async def customer_ids_for(session: AsyncSession, project_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    if not project_ids:
        return set()
    rows = await session.execute(
        select(Project.customer_party_id).where(Project.id.in_(project_ids), Project.customer_party_id.is_not(None))
    )
    return set(rows.scalars())


async def ensure_visible(session: AsyncSession, user: CurrentUser, permission: str, project: Project) -> None:
    scope = user.scope_for(permission)
    if scope == Scope.ALL:
        return
    if scope is None or project.id not in await visible_project_ids(session, user):
        raise NotFound("Project not found")


def list_stmt(
    *, q: str | None, status: str | None, customer_party_id: uuid.UUID | None, only_ids: set[uuid.UUID] | None
) -> Select[tuple[Project]]:
    stmt = select(Project).order_by(Project.number.desc())
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Project.name.ilike(like), Project.number.ilike(like)))
    if status:
        stmt = stmt.where(Project.status == status)
    if customer_party_id:
        stmt = stmt.where(Project.customer_party_id == customer_party_id)
    if only_ids is not None:
        stmt = stmt.where(Project.id.in_(only_ids))
    return stmt


async def _validate(session: AsyncSession, data: dict[str, Any]) -> None:
    await categories.validate_choice(
        session,
        group_key="project_type",
        category_id=data.get("project_type_category_id"),
        other_text=data.get("project_type_other_text"),
        field="project_type_category_id",
        other_field="project_type_other_text",
    )
    if data.get("customer_party_id"):
        try:
            await parties.get(session, data["customer_party_id"], kinds=("customer", "other"))
        except NotFound:
            raise ValidationFailed("Unknown customer", errors=[field_error("customer_party_id", "Not found")]) from None
    if data.get("manager_employee_id"):
        try:
            await employees.get(session, data["manager_employee_id"])
        except NotFound:
            raise ValidationFailed(
                "Unknown manager", errors=[field_error("manager_employee_id", "Not found")]
            ) from None
    data["currency"] = (data.get("currency") or (await settings.base_currency(session)).code).upper()
    await settings.get_currency(session, data["currency"])
    if data.get("start_date") and data.get("deadline") and data["deadline"] < data["start_date"]:
        raise ValidationFailed("Invalid dates", errors=[field_error("deadline", "Must be on or after the start date")])


async def create(session: AsyncSession, *, actor_id: uuid.UUID | None, data: dict[str, Any]) -> Project:
    await _validate(session, data)
    project = Project(
        number=await next_number(session, "PRJ", None),
        created_by=actor_id,
        updated_by=actor_id,
        **{k: v for k, v in data.items() if k in EDITABLE},
    )
    session.add(project)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="project.created",
        entity_type="project",
        entity_id=project.id,
        after=_snapshot(project),
    )
    return project


async def update(
    session: AsyncSession, *, actor_id: uuid.UUID, project_id: uuid.UUID, version: int, changes: dict[str, Any]
) -> Project:
    project = await get(session, project_id)
    if project.version != version:
        raise PreconditionFailed()
    before = _snapshot(project)
    merged = {**before, **changes}
    await _validate(session, merged)
    for k in EDITABLE:
        setattr(project, k, merged[k])
    project.version += 1
    project.updated_by = actor_id
    await session.flush()
    b, a = audit.diff(before, _snapshot(project))
    if a:
        await audit.record(
            session,
            actor_id=actor_id,
            action="project.updated",
            entity_type="project",
            entity_id=project.id,
            before=b,
            after=a,
        )
    return project


async def set_members(
    session: AsyncSession, *, actor_id: uuid.UUID, project_id: uuid.UUID, rows: list[dict[str, Any]]
) -> list[ProjectMember]:
    await get(session, project_id)
    ids = [r["employee_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValidationFailed("Duplicate member", errors=[field_error("members", "Each employee can appear once")])
    for i, eid in enumerate(ids):
        try:
            await employees.get(session, eid)
        except NotFound:
            raise ValidationFailed(
                "Unknown employee", errors=[field_error(f"members.{i}.employee_id", "Not found")]
            ) from None
    total = sum((r.get("default_allocation_pct") or Decimal(0) for r in rows), Decimal(0))
    if total > 100:
        raise ValidationFailed(
            "Split over 100%", errors=[field_error("members", f"Default splits add up to {total}%, max 100%")]
        )
    before = [
        {"employee_id": m.employee_id, "pct": m.default_allocation_pct} for m in await members(session, project_id)
    ]
    await session.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id))
    session.add_all(ProjectMember(project_id=project_id, **r) for r in rows)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="project.members_changed",
        entity_type="project",
        entity_id=project_id,
        before={"members": before},
        after={"members": [{"employee_id": r["employee_id"], "pct": r.get("default_allocation_pct")} for r in rows]},
    )
    return await members(session, project_id)


async def default_split(session: AsyncSession, project_id: uuid.UUID) -> list[tuple[uuid.UUID, Decimal]]:
    """Members with a default allocation percentage, used to pre-fill payment splits."""
    return [
        (m.employee_id, m.default_allocation_pct)
        for m in await members(session, project_id)
        if m.default_allocation_pct
    ]


async def can_manage(session: AsyncSession, user: CurrentUser, project: Project | None) -> None:
    scope = user.scope_for("projects.manage")
    if scope is None:
        raise Forbidden("Requires permission projects.manage")
    if scope == Scope.ALL or project is None:
        return
    employee = await employees.for_user(session, user.id)
    if employee is None or project.manager_employee_id != employee.id:
        raise Forbidden("Only the project manager can change this project")


async def find_by_name(session: AsyncSession, name: str) -> Project | None:
    return (
        await session.execute(select(Project).where(func.lower(Project.name) == name.strip().lower()).limit(1))
    ).scalar_one_or_none()


async def can_manage_id(session: AsyncSession, user: CurrentUser, project_id: uuid.UUID) -> Project:
    project = await get(session, project_id)
    await can_manage(session, user, project)
    return project


async def is_team_member(session: AsyncSession, user: CurrentUser, project_id: uuid.UUID) -> bool:
    return project_id in await visible_project_ids(session, user)


# ---- milestones ------------------------------------------------------------------------------------

MILESTONE_FIELDS = ("name", "description", "due_date", "status")


async def milestones(session: AsyncSession, project_id: uuid.UUID) -> list[Milestone]:
    return list(
        (
            await session.execute(
                select(Milestone)
                .where(Milestone.project_id == project_id)
                .order_by(Milestone.due_date.asc().nulls_last(), Milestone.name)
            )
        ).scalars()
    )


async def get_milestone(session: AsyncSession, milestone_id: uuid.UUID) -> Milestone:
    m = await session.get(Milestone, milestone_id)
    if m is None:
        raise NotFound("Milestone not found")
    return m


async def create_milestone(
    session: AsyncSession, *, actor_id: uuid.UUID, project_id: uuid.UUID, data: dict[str, Any]
) -> Milestone:
    await get(session, project_id)
    m = Milestone(project_id=project_id, created_by=actor_id, updated_by=actor_id, **data)
    session.add(m)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="milestone.created",
        entity_type="project",
        entity_id=project_id,
        after={k: getattr(m, k) for k in MILESTONE_FIELDS},
    )
    return m


async def update_milestone(
    session: AsyncSession, *, actor_id: uuid.UUID, milestone_id: uuid.UUID, version: int, changes: dict[str, Any]
) -> Milestone:
    m = await get_milestone(session, milestone_id)
    if m.version != version:
        raise PreconditionFailed()
    before = {k: getattr(m, k) for k in MILESTONE_FIELDS}
    for k, v in changes.items():
        setattr(m, k, v)
    m.version += 1
    m.updated_by = actor_id
    await session.flush()
    b, a = audit.diff(before, {k: getattr(m, k) for k in MILESTONE_FIELDS})
    if a:
        await audit.record(
            session,
            actor_id=actor_id,
            action="milestone.updated",
            entity_type="project",
            entity_id=m.project_id,
            before=b,
            after=a,
        )
    return m


async def delete_milestone(session: AsyncSession, *, actor_id: uuid.UUID, milestone_id: uuid.UUID) -> None:
    """Tasks keep existing; their milestone link is cleared (FK ON DELETE SET NULL)."""
    m = await get_milestone(session, milestone_id)
    await session.delete(m)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="milestone.deleted",
        entity_type="project",
        entity_id=m.project_id,
        before={"name": m.name, "due_date": m.due_date},
    )


async def milestones_between(
    session: AsyncSession, project_ids: set[uuid.UUID] | None, date_from: Any, date_to: Any
) -> list[Milestone]:
    stmt = select(Milestone).where(Milestone.due_date.between(date_from, date_to))
    if project_ids is not None:
        stmt = stmt.where(Milestone.project_id.in_(project_ids))
    return list((await session.execute(stmt)).scalars())


async def deadlines_between(
    session: AsyncSession, project_ids: set[uuid.UUID] | None, date_from: Any, date_to: Any
) -> list[Project]:
    stmt = select(Project).where(
        Project.deadline.between(date_from, date_to), Project.status.in_(("planned", "active", "on_hold"))
    )
    if project_ids is not None:
        stmt = stmt.where(Project.id.in_(project_ids))
    return list((await session.execute(stmt)).scalars())
