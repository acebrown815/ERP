import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import Forbidden
from app.modules.auth.api import CurrentUser, require
from app.modules.compensation import engine, service
from app.modules.compensation.models import CompAssignment, CompFormula, CompFormulaVersion
from app.modules.employees import api as employees
from app.modules.rbac.api import Scope
from app.modules.settings import api as settings

router = APIRouter(tags=["salary formulas"])

ReadAll = Depends(require("comp_formulas.read", Scope.ALL))
Manage = Depends(require("comp_formulas.manage"))


class FormulaVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    formula_id: uuid.UUID
    version_no: int
    definition: engine.FormulaDefinition
    effective_from: date
    notes: str | None
    is_locked: bool
    created_at: datetime


class FormulaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    compensation_type_category_id: uuid.UUID | None
    compensation_type_other_text: str | None
    description: str | None
    is_active: bool
    version: int
    current: FormulaVersionOut | None = None
    employees_assigned: int = 0


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    formula_id: uuid.UUID
    effective_from: date
    effective_to: date | None
    notes: str | None
    version: int
    employee_name: str | None = None
    formula_name: str | None = None


class FormulaDetailOut(FormulaOut):
    versions: list[FormulaVersionOut]
    assignments: list[AssignmentOut]


class FormulaCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    compensation_type_category_id: uuid.UUID | None = None
    compensation_type_other_text: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    definition: dict[str, Any]
    effective_from: date


class FormulaUpdateIn(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=120)
    compensation_type_category_id: uuid.UUID | None = None
    compensation_type_other_text: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None


class VersionCreateIn(BaseModel):
    definition: dict[str, Any]
    effective_from: date
    notes: str | None = Field(default=None, max_length=2000)


class FormulaPreviewIn(BaseModel):
    definition: dict[str, Any]
    revenues: list[Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=4)]] = Field(
        default_factory=list, max_length=50
    )
    chart_max: Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=4)] | None = None


class FormulaPreviewRow(BaseModel):
    revenue: Decimal
    rate: Decimal
    amount: Decimal


class FormulaPreviewOut(BaseModel):
    rows: list[FormulaPreviewRow]
    chart: list[FormulaPreviewRow]


class AssignmentCreateIn(BaseModel):
    employee_id: uuid.UUID
    formula_id: uuid.UUID
    effective_from: date
    effective_to: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    end_previous: bool = True


class AssignmentUpdateIn(BaseModel):
    version: int
    effective_to: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


def _current(versions: list[CompFormulaVersion], on: date) -> CompFormulaVersion | None:
    started = [v for v in versions if v.effective_from <= on]
    return max(started, key=lambda v: v.effective_from) if started else (versions[-1] if versions else None)


async def _formula_out(session: AsyncSession, f: CompFormula, today: date, counts: dict[uuid.UUID, int]) -> FormulaOut:
    out = FormulaOut.model_validate(f)
    current = _current(await service.versions(session, f.id), today)
    out.current = FormulaVersionOut.model_validate(current) if current else None
    out.employees_assigned = counts.get(f.id, 0)
    return out


async def _assignments_out(session: AsyncSession, rows: list[CompAssignment]) -> list[AssignmentOut]:
    names = await employees.names(session, [a.employee_id for a in rows])
    formulas = {f.id: f.name for f in await service.list_formulas(session, include_inactive=True)}
    out = []
    for a in rows:
        item = AssignmentOut.model_validate(a)
        item.employee_name = names.get(a.employee_id)
        item.formula_name = formulas.get(a.formula_id)
        out.append(item)
    return out


@router.get("/comp-formulas", response_model=list[FormulaOut])
async def list_formulas(
    include_inactive: bool = False, _: CurrentUser = ReadAll, session: AsyncSession = Depends(get_session)
) -> Any:
    today = await settings.today(session)
    counts = await service.assignment_counts(session, today)
    return [
        await _formula_out(session, f, today, counts)
        for f in await service.list_formulas(session, include_inactive=include_inactive)
    ]


@router.get("/comp-formulas/{formula_id}", response_model=FormulaDetailOut)
async def get_formula(
    formula_id: uuid.UUID, _: CurrentUser = ReadAll, session: AsyncSession = Depends(get_session)
) -> Any:
    f = await service.get_formula(session, formula_id)
    today = await settings.today(session)
    base = await _formula_out(session, f, today, await service.assignment_counts(session, today))
    return FormulaDetailOut(
        **base.model_dump(),
        versions=[FormulaVersionOut.model_validate(v) for v in await service.versions(session, f.id)],
        assignments=await _assignments_out(session, await service.list_assignments(session, formula_id=f.id)),
    )


@router.post("/comp-formulas", response_model=FormulaOut, status_code=201)
async def create_formula(
    body: FormulaCreateIn, actor: CurrentUser = Manage, session: AsyncSession = Depends(get_session)
) -> Any:
    f = await service.create_formula(
        session,
        actor_id=actor.id,
        data=body.model_dump(exclude={"definition", "effective_from"}),
        definition=body.definition,
        effective_from=body.effective_from,
    )
    await session.commit()
    today = await settings.today(session)
    return await _formula_out(session, f, today, {})


@router.patch("/comp-formulas/{formula_id}", response_model=FormulaOut)
async def update_formula(
    formula_id: uuid.UUID,
    body: FormulaUpdateIn,
    actor: CurrentUser = Manage,
    session: AsyncSession = Depends(get_session),
) -> Any:
    f = await service.update_formula(
        session,
        actor_id=actor.id,
        formula_id=formula_id,
        version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version"}),
    )
    await session.commit()
    today = await settings.today(session)
    return await _formula_out(session, f, today, await service.assignment_counts(session, today))


@router.post("/comp-formulas/{formula_id}/versions", response_model=FormulaVersionOut, status_code=201)
async def add_version(
    formula_id: uuid.UUID,
    body: VersionCreateIn,
    actor: CurrentUser = Manage,
    session: AsyncSession = Depends(get_session),
) -> Any:
    v = await service.add_version(
        session,
        actor_id=actor.id,
        formula_id=formula_id,
        definition=body.definition,
        effective_from=body.effective_from,
        notes=body.notes,
    )
    await session.commit()
    return v


@router.delete("/comp-formula-versions/{version_id}", status_code=204)
async def delete_version(
    version_id: uuid.UUID, actor: CurrentUser = Manage, session: AsyncSession = Depends(get_session)
) -> Response:
    await service.delete_version(session, actor_id=actor.id, version_id=version_id)
    await session.commit()
    return Response(status_code=204)


@router.post("/comp-formulas/preview", response_model=FormulaPreviewOut)
async def preview(body: FormulaPreviewIn, _: CurrentUser = Depends(require("comp_formulas.read"))) -> FormulaPreviewOut:
    """Salary at sample revenues, plus evenly spaced points for the rate/salary chart."""
    d = service.parse_definition(body.definition)

    def row(revenue: Decimal) -> FormulaPreviewRow:
        r = engine.calculate(d, revenue)
        return FormulaPreviewRow(revenue=revenue, rate=r.rate, amount=r.formula_amount)

    marks = [p.revenue for p in d.rate_schedule.points] + [t.from_revenue for t in d.rate_schedule.tiers]
    top = body.chart_max or max([Decimal(10000), *(m * Decimal("1.33") for m in marks)])
    steps = 60
    chart = [row((top * i / steps).quantize(Decimal(1))) for i in range(steps + 1)]
    # Exact values just below and at each breakpoint so the chart shows jumps.
    for m in marks:
        if m > 0:
            chart += [row(m - Decimal("0.01")), row(m)]
    chart.sort(key=lambda r: r.revenue)
    return FormulaPreviewOut(rows=[row(r) for r in body.revenues], chart=chart)


# ---- assignments -----------------------------------------------------------------------------------


@router.get("/comp-assignments", response_model=list[AssignmentOut])
async def list_assignments(
    employee_id: Annotated[uuid.UUID | None, Query()] = None,
    formula_id: Annotated[uuid.UUID | None, Query()] = None,
    user: CurrentUser = Depends(require("comp_formulas.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    if user.scope_for("comp_formulas.read") != Scope.ALL:
        own = await employees.for_user(session, user.id)
        if own is None or employee_id != own.id:
            raise Forbidden("You can only see your own salary formula")
    rows = await service.list_assignments(session, employee_id=employee_id, formula_id=formula_id)
    return await _assignments_out(session, rows)


@router.post("/comp-assignments", response_model=AssignmentOut, status_code=201)
async def create_assignment(
    body: AssignmentCreateIn, actor: CurrentUser = Manage, session: AsyncSession = Depends(get_session)
) -> Any:
    a = await service.create_assignment(session, actor_id=actor.id, **body.model_dump())
    await session.commit()
    return (await _assignments_out(session, [a]))[0]


@router.patch("/comp-assignments/{assignment_id}", response_model=AssignmentOut)
async def update_assignment(
    assignment_id: uuid.UUID,
    body: AssignmentUpdateIn,
    actor: CurrentUser = Manage,
    session: AsyncSession = Depends(get_session),
) -> Any:
    a = await service.update_assignment(
        session,
        actor_id=actor.id,
        assignment_id=assignment_id,
        version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version"}),
    )
    await session.commit()
    return (await _assignments_out(session, [a]))[0]


@router.delete("/comp-assignments/{assignment_id}", status_code=204)
async def delete_assignment(
    assignment_id: uuid.UUID, actor: CurrentUser = Manage, session: AsyncSession = Depends(get_session)
) -> Response:
    await service.delete_assignment(session, actor_id=actor.id, assignment_id=assignment_id)
    await session.commit()
    return Response(status_code=204)
