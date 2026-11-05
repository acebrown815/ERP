import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PreconditionFailed, ValidationFailed, field_error
from app.modules.audit import api as audit
from app.modules.categories import api as categories
from app.modules.compensation.engine import DEFAULT_DEFINITION, FormulaDefinition
from app.modules.compensation.models import CompAssignment, CompFormula, CompFormulaVersion
from app.modules.employees import api as employees

DEFAULT_FORMULA_NAME = "Revenue Share (provisional)"
SEED_EFFECTIVE_FROM = date(2000, 1, 1)

# Salary owns closed periods and registers this at startup (salary depends on us, not the reverse).
ClosedThrough = Callable[[AsyncSession], Awaitable[date | None]]
_closed_through: ClosedThrough | None = None


def register_closed_through(provider: ClosedThrough) -> None:
    global _closed_through
    _closed_through = provider


async def closed_through(session: AsyncSession) -> date | None:
    """Last day covered by a closed salary period; rules on or before it can't change."""
    return await _closed_through(session) if _closed_through else None


async def _guard_date(session: AsyncSession, field: str, value: date) -> None:
    locked = await closed_through(session)
    if locked and value <= locked:
        raise ValidationFailed(
            "Inside a closed salary period",
            errors=[
                field_error(field, f"Salary periods up to {locked.isoformat()} are closed; pick a later date", "closed")
            ],
        )


def parse_definition(raw: dict[str, Any], field: str = "definition") -> FormulaDefinition:
    try:
        return FormulaDefinition.model_validate(raw)
    except ValidationError as exc:
        errors = [
            field_error(".".join([field, *(str(p) for p in e["loc"])]), e["msg"].removeprefix("Value error, "))
            for e in exc.errors()
        ]
        raise ValidationFailed("Invalid formula", errors=errors) from None


def dump_definition(d: FormulaDefinition) -> dict[str, Any]:
    return d.model_dump(mode="json")


# ---- formulas --------------------------------------------------------------------------------------


async def get_formula(session: AsyncSession, formula_id: uuid.UUID) -> CompFormula:
    f = await session.get(CompFormula, formula_id)
    if f is None:
        raise NotFound("Salary formula not found")
    return f


async def list_formulas(session: AsyncSession, *, include_inactive: bool) -> list[CompFormula]:
    stmt = select(CompFormula).order_by(func.lower(CompFormula.name))
    if not include_inactive:
        stmt = stmt.where(CompFormula.is_active.is_(True))
    return list((await session.execute(stmt)).scalars())


async def versions(session: AsyncSession, formula_id: uuid.UUID) -> list[CompFormulaVersion]:
    return list(
        (
            await session.execute(
                select(CompFormulaVersion)
                .where(CompFormulaVersion.formula_id == formula_id)
                .order_by(CompFormulaVersion.effective_from.desc())
            )
        ).scalars()
    )


async def assignment_counts(session: AsyncSession, on: date) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(CompAssignment.formula_id, func.count())
        .where(
            CompAssignment.effective_from <= on,
            or_(CompAssignment.effective_to.is_(None), CompAssignment.effective_to >= on),
        )
        .group_by(CompAssignment.formula_id)
    )
    return dict(rows.all())  # type: ignore[arg-type]


async def _check_name(session: AsyncSession, name: str, exclude: uuid.UUID | None) -> None:
    stmt = select(CompFormula.id).where(func.lower(CompFormula.name) == name.strip().lower())
    if exclude:
        stmt = stmt.where(CompFormula.id != exclude)
    if (await session.execute(stmt)).first():
        raise ValidationFailed("Name in use", errors=[field_error("name", "A formula has this name")])


async def _check_type(session: AsyncSession, category_id: uuid.UUID | None, other: str | None) -> None:
    if category_id is not None:
        await categories.validate_choice(
            session,
            group_key="compensation_type",
            category_id=category_id,
            other_text=other,
            field="compensation_type_category_id",
            other_field="compensation_type_other_text",
        )


def _snapshot(f: CompFormula) -> dict[str, Any]:
    return {
        "name": f.name,
        "compensation_type_category_id": f.compensation_type_category_id,
        "compensation_type_other_text": f.compensation_type_other_text,
        "description": f.description,
        "is_active": f.is_active,
    }


async def create_formula(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    data: dict[str, Any],
    definition: dict[str, Any],
    effective_from: date,
) -> CompFormula:
    await _check_name(session, data["name"], None)
    await _check_type(session, data.get("compensation_type_category_id"), data.get("compensation_type_other_text"))
    parsed = parse_definition(definition)
    f = CompFormula(
        name=data["name"].strip(),
        compensation_type_category_id=data.get("compensation_type_category_id"),
        compensation_type_other_text=data.get("compensation_type_other_text"),
        description=data.get("description"),
        created_by=actor_id,
        updated_by=actor_id,
    )
    session.add(f)
    await session.flush()
    v = CompFormulaVersion(
        formula_id=f.id,
        version_no=1,
        definition=dump_definition(parsed),
        effective_from=effective_from,
        created_by=actor_id,
    )
    session.add(v)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="comp_formula.created",
        entity_type="comp_formula",
        entity_id=f.id,
        after={**_snapshot(f), "definition": v.definition, "effective_from": effective_from},
    )
    return f


async def update_formula(
    session: AsyncSession, *, actor_id: uuid.UUID, formula_id: uuid.UUID, version: int, changes: dict[str, Any]
) -> CompFormula:
    f = await get_formula(session, formula_id)
    if f.version != version:
        raise PreconditionFailed()
    before = _snapshot(f)
    if "name" in changes:
        await _check_name(session, changes["name"], f.id)
        changes["name"] = changes["name"].strip()
    if "compensation_type_category_id" in changes or "compensation_type_other_text" in changes:
        await _check_type(
            session,
            changes.get("compensation_type_category_id", f.compensation_type_category_id),
            changes.get("compensation_type_other_text", f.compensation_type_other_text),
        )
    if changes.get("is_active") is False:
        active = (await assignment_counts(session, date.today())).get(f.id, 0)
        if active:
            raise Conflict(f"{active} employee(s) are on this formula; end their assignments first")
    for k, v in changes.items():
        setattr(f, k, v)
    f.version += 1
    f.updated_by = actor_id
    await session.flush()
    b, a = audit.diff(before, _snapshot(f))
    if a:
        await audit.record(
            session,
            actor_id=actor_id,
            action="comp_formula.updated",
            entity_type="comp_formula",
            entity_id=f.id,
            before=b,
            after=a,
        )
    return f


async def add_version(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    formula_id: uuid.UUID,
    definition: dict[str, Any],
    effective_from: date,
    notes: str | None,
) -> CompFormulaVersion:
    f = await get_formula(session, formula_id)
    await _guard_date(session, "effective_from", effective_from)
    parsed = parse_definition(definition)
    existing = await versions(session, f.id)
    if any(v.effective_from == effective_from for v in existing):
        raise ValidationFailed(
            "Date taken",
            errors=[field_error("effective_from", "Another version starts on this date; delete it or pick another")],
        )
    v = CompFormulaVersion(
        formula_id=f.id,
        version_no=max((x.version_no for x in existing), default=0) + 1,
        definition=dump_definition(parsed),
        effective_from=effective_from,
        notes=notes,
        created_by=actor_id,
    )
    session.add(v)
    f.version += 1
    f.updated_by = actor_id
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="comp_formula.version_added",
        entity_type="comp_formula",
        entity_id=f.id,
        after={"version_no": v.version_no, "effective_from": effective_from, "definition": v.definition},
    )
    return v


async def delete_version(session: AsyncSession, *, actor_id: uuid.UUID, version_id: uuid.UUID) -> None:
    v = await session.get(CompFormulaVersion, version_id)
    if v is None:
        raise NotFound("Formula version not found")
    if v.is_locked:
        raise Conflict("This version was used by a closed salary period and can't be deleted")
    await _guard_date(session, "effective_from", v.effective_from)
    if len(await versions(session, v.formula_id)) == 1:
        raise Conflict("A formula needs at least one version")
    f = await get_formula(session, v.formula_id)
    await session.delete(v)
    f.version += 1
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="comp_formula.version_deleted",
        entity_type="comp_formula",
        entity_id=f.id,
        before={"version_no": v.version_no, "effective_from": v.effective_from},
    )


async def lock_versions(session: AsyncSession, version_ids: list[uuid.UUID]) -> None:
    if version_ids:
        for v in (
            await session.execute(select(CompFormulaVersion).where(CompFormulaVersion.id.in_(version_ids)))
        ).scalars():
            v.is_locked = True
        await session.flush()


# ---- assignments -----------------------------------------------------------------------------------


async def get_assignment(session: AsyncSession, assignment_id: uuid.UUID) -> CompAssignment:
    a = await session.get(CompAssignment, assignment_id)
    if a is None:
        raise NotFound("Assignment not found")
    return a


async def list_assignments(
    session: AsyncSession, *, employee_id: uuid.UUID | None = None, formula_id: uuid.UUID | None = None
) -> list[CompAssignment]:
    stmt = select(CompAssignment).order_by(CompAssignment.effective_from.desc())
    if employee_id:
        stmt = stmt.where(CompAssignment.employee_id == employee_id)
    if formula_id:
        stmt = stmt.where(CompAssignment.formula_id == formula_id)
    return list((await session.execute(stmt)).scalars())


async def _check_overlap(
    session: AsyncSession, employee_id: uuid.UUID, start: date, end: date | None, exclude: uuid.UUID | None
) -> None:
    stmt = select(CompAssignment).where(
        CompAssignment.employee_id == employee_id,
        or_(CompAssignment.effective_to.is_(None), CompAssignment.effective_to >= start),
    )
    if end is not None:
        stmt = stmt.where(CompAssignment.effective_from <= end)
    if exclude:
        stmt = stmt.where(CompAssignment.id != exclude)
    clash = (await session.execute(stmt)).scalars().first()
    if clash:
        until = clash.effective_to.isoformat() if clash.effective_to else "open-ended"
        raise ValidationFailed(
            "Overlapping assignment",
            errors=[
                field_error(
                    "effective_from",
                    f"Overlaps the assignment from {clash.effective_from.isoformat()} ({until}). End that one first.",
                    "overlap",
                )
            ],
        )


def _assignment_snapshot(a: CompAssignment) -> dict[str, Any]:
    return {
        "employee_id": a.employee_id,
        "formula_id": a.formula_id,
        "effective_from": a.effective_from,
        "effective_to": a.effective_to,
        "notes": a.notes,
    }


async def has_assignments(session: AsyncSession, employee_id: uuid.UUID) -> bool:
    stmt = select(CompAssignment.id).where(CompAssignment.employee_id == employee_id).limit(1)
    return (await session.execute(stmt)).first() is not None


async def create_assignment(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    employee_id: uuid.UUID,
    formula_id: uuid.UUID,
    effective_from: date,
    effective_to: date | None = None,
    notes: str | None = None,
    end_previous: bool = False,
) -> CompAssignment:
    """`end_previous` closes an open-ended assignment the day before, which is what "switch formula" means."""
    await employees.get(session, employee_id)
    await employees.assert_not_hire(session, employee_id)
    f = await get_formula(session, formula_id)
    if not f.is_active:
        raise ValidationFailed("Inactive formula", errors=[field_error("formula_id", "This formula is inactive")])
    if effective_to is not None and effective_to < effective_from:
        raise ValidationFailed("Dates", errors=[field_error("effective_to", "Must be on or after the start")])
    await _guard_date(session, "effective_from", effective_from)
    if end_previous:
        previous = (
            await session.execute(
                select(CompAssignment).where(
                    CompAssignment.employee_id == employee_id,
                    CompAssignment.effective_to.is_(None),
                    CompAssignment.effective_from < effective_from,
                )
            )
        ).scalar_one_or_none()
        if previous:
            await update_assignment(
                session,
                actor_id=actor_id,
                assignment_id=previous.id,
                version=previous.version,
                changes={"effective_to": date.fromordinal(effective_from.toordinal() - 1)},
            )
    await _check_overlap(session, employee_id, effective_from, effective_to, None)
    a = CompAssignment(
        employee_id=employee_id,
        formula_id=formula_id,
        effective_from=effective_from,
        effective_to=effective_to,
        notes=notes,
        created_by=actor_id,
        updated_by=actor_id,
    )
    session.add(a)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="comp_assignment.created",
        entity_type="employee",
        entity_id=employee_id,
        after=_assignment_snapshot(a),
    )
    return a


async def update_assignment(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    assignment_id: uuid.UUID,
    version: int,
    changes: dict[str, Any],
) -> CompAssignment:
    """Only the end date and notes change; a different formula or start is a new assignment."""
    a = await get_assignment(session, assignment_id)
    if a.version != version:
        raise PreconditionFailed()
    before = _assignment_snapshot(a)
    if "effective_to" in changes and changes["effective_to"] != a.effective_to:
        new_end = changes["effective_to"]
        if new_end is not None and new_end < a.effective_from:
            raise ValidationFailed("Dates", errors=[field_error("effective_to", "Must be on or after the start")])
        # Coverage of closed periods must stay as it was.
        await _guard_date(session, "effective_to", min(d or date.max for d in (a.effective_to, new_end)))
        await _check_overlap(session, a.employee_id, a.effective_from, new_end, a.id)
        a.effective_to = new_end
    if "notes" in changes:
        a.notes = changes["notes"]
    a.version += 1
    a.updated_by = actor_id
    await session.flush()
    b, after = audit.diff(before, _assignment_snapshot(a))
    if after:
        await audit.record(
            session,
            actor_id=actor_id,
            action="comp_assignment.updated",
            entity_type="employee",
            entity_id=a.employee_id,
            before=b,
            after=after,
        )
    return a


async def delete_assignment(session: AsyncSession, *, actor_id: uuid.UUID, assignment_id: uuid.UUID) -> None:
    a = await get_assignment(session, assignment_id)
    await _guard_date(session, "effective_from", a.effective_from)
    snapshot = _assignment_snapshot(a)
    await session.execute(delete(CompAssignment).where(CompAssignment.id == a.id))
    await audit.record(
        session,
        actor_id=actor_id,
        action="comp_assignment.deleted",
        entity_type="employee",
        entity_id=a.employee_id,
        before=snapshot,
    )


# ---- resolution for salary -------------------------------------------------------------------------


@dataclass
class Resolved:
    formula_id: uuid.UUID
    formula_name: str
    version_id: uuid.UUID
    version_no: int
    definition: FormulaDefinition


async def resolve(
    session: AsyncSession, *, start: date, end: date, employee_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, Resolved]:
    """Formula per employee for a salary period: the latest assignment overlapping the period, at the
    version in effect on the last day it covers (period end, or the assignment end if earlier)."""
    stmt = (
        select(CompAssignment, CompFormula)
        .join(CompFormula, CompFormula.id == CompAssignment.formula_id)
        .where(
            CompAssignment.effective_from <= end,
            or_(CompAssignment.effective_to.is_(None), CompAssignment.effective_to >= start),
        )
        .order_by(CompAssignment.employee_id, CompAssignment.effective_from)
    )
    if employee_ids is not None:
        stmt = stmt.where(CompAssignment.employee_id.in_(employee_ids))
    latest: dict[uuid.UUID, tuple[CompAssignment, CompFormula]] = {}
    for a, f in (await session.execute(stmt)).all():
        latest[a.employee_id] = (a, f)
    if not latest:
        return {}
    formula_ids = {f.id for _, f in latest.values()}
    all_versions: dict[uuid.UUID, list[CompFormulaVersion]] = {}
    for v in (
        await session.execute(
            select(CompFormulaVersion)
            .where(CompFormulaVersion.formula_id.in_(formula_ids))
            .order_by(CompFormulaVersion.effective_from)
        )
    ).scalars():
        all_versions.setdefault(v.formula_id, []).append(v)
    out = {}
    for employee_id, (a, f) in latest.items():
        on = min(end, a.effective_to) if a.effective_to else end
        candidates = [v for v in all_versions.get(f.id, []) if v.effective_from <= on]
        if not candidates:
            continue
        v = candidates[-1]
        out[employee_id] = Resolved(f.id, f.name, v.id, v.version_no, FormulaDefinition.model_validate(v.definition))
    return out


async def seed(session: AsyncSession) -> None:
    """The provisional default formula (Section 9.3), if no formula exists yet."""
    if (await session.execute(select(func.count()).select_from(CompFormula))).scalar_one():
        return
    rev = await categories.by_system_key(session, "compensation_type", "revenue_percentage")
    await create_formula(
        session,
        actor_id=None,
        data={
            "name": DEFAULT_FORMULA_NAME,
            "compensation_type_category_id": rev.id,
            "description": "No salary below $3,000 of monthly revenue. 8% at $3,000 rising evenly to 30% at "
            "$30,000, then 30%. The rate applies to the whole revenue.",
        },
        definition=dump_definition(DEFAULT_DEFINITION),
        effective_from=SEED_EFFECTIVE_FROM,
    )


async def default_formula(session: AsyncSession) -> CompFormula | None:
    return (
        await session.execute(select(CompFormula).where(CompFormula.name == DEFAULT_FORMULA_NAME))
    ).scalar_one_or_none()
