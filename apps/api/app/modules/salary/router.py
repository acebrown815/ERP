import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lookup
from app.core.csv_export import csv_response
from app.core.db import get_session
from app.core.errors import NotFound
from app.modules.attribution import api as attribution
from app.modules.auth.api import CurrentUser, current_user, require
from app.modules.compensation import api as compensation
from app.modules.employees import api as employees
from app.modules.projects import api as projects
from app.modules.rbac.api import Scope
from app.modules.salary import cycle, service
from app.modules.salary.models import SalaryAdjustment, SalaryPeriod
from app.modules.settings import api as settings

router = APIRouter(tags=["salary"])

Money = Annotated[Decimal, Field(max_digits=20, decimal_places=4)]
Format = Literal["json", "csv"]


# ---- schemas ---------------------------------------------------------------------------------------


class SalaryPeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    start_date: date
    end_date: date
    is_transition: bool
    status: str
    closed_at: datetime | None
    reopened_at: datetime | None
    reopen_reason: str | None
    is_current: bool = False
    is_future: bool = False


class SalaryComponent(BaseModel):
    component: str
    label: str
    amount: Decimal
    basis: Decimal | None = None
    rate: Decimal | None = None


class StatementOut(BaseModel):
    period_id: uuid.UUID
    period_label: str
    period_start: date
    period_end: date
    period_status: str
    employee_id: uuid.UUID
    employee_name: str
    revenue: Decimal
    formula_id: uuid.UUID | None
    formula_name: str | None
    formula_version_no: int | None
    rate: Decimal
    formula_amount: Decimal
    adjustments_total: Decimal
    calculated: Decimal
    paid: Decimal
    status: str
    frozen: bool
    components: list[SalaryComponent]


class BoardRow(StatementOut):
    balance: Decimal  # the employee's overall balance (all periods), not just this one


class BoardOut(BaseModel):
    period: SalaryPeriodOut
    rows: list[BoardRow]
    total_revenue: Decimal
    total_calculated: Decimal
    total_paid: Decimal
    can_close: bool
    close_blocker: str | None


class SalaryPaymentOut(BaseModel):
    payment_entry_id: uuid.UUID
    number: str | None
    paid_on: date
    amount: Decimal
    period_label: str | None


class FormulaRef(BaseModel):
    formula_id: uuid.UUID
    formula_name: str
    version_no: int
    definition: compensation.FormulaDefinition


class EmployeeSalaryOut(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    calculated_total: Decimal
    paid_total: Decimal
    balance: Decimal
    credit: Decimal
    formula: FormulaRef | None
    current: StatementOut | None
    statements: list[StatementOut]  # newest first
    payments: list[SalaryPaymentOut]


class RevenueAllocationOut(BaseModel):
    payment_entry_id: uuid.UUID
    payment_number: str | None
    date: date
    project_id: uuid.UUID | None
    project_name: str | None
    percent: Decimal | None
    amount: Decimal


class ProjectRevenue(BaseModel):
    project_id: uuid.UUID | None
    project_name: str | None
    revenue: Decimal
    payments: int


class EmployeeRevenueOut(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    period: SalaryPeriodOut
    total: Decimal
    by_project: list[ProjectRevenue]
    allocations: list[RevenueAllocationOut]


class AdjustmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    salary_period_id: uuid.UUID
    employee_id: uuid.UUID
    kind: str
    amount: Decimal
    reason: str
    created_at: datetime


class AdjustmentIn(BaseModel):
    employee_id: uuid.UUID
    kind: Literal["bonus", "deduction", "correction"]
    amount: Money
    reason: str = Field(min_length=1, max_length=2000)


class ReopenIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class SpanOut(BaseModel):
    label: str
    start_date: date
    end_date: date
    is_transition: bool


class CycleOut(BaseModel):
    salary_cycle_start_day: int
    current: SpanOut | None
    upcoming: list[SpanOut]
    replaces_all: bool
    blockers: list[str]


class CycleIn(BaseModel):
    salary_cycle_start_day: int = Field(ge=1, le=28)


class ReportPeriod(BaseModel):
    id: uuid.UUID
    label: str
    start_date: date
    end_date: date
    status: str


class RevenueReportRow(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    by_period: list[Decimal]
    total: Decimal


class RevenueReportOut(BaseModel):
    periods: list[ReportPeriod]
    rows: list[RevenueReportRow]
    totals: list[Decimal]
    total: Decimal


class SalaryReportCell(BaseModel):
    revenue: Decimal
    calculated: Decimal
    paid: Decimal
    status: str


class SalaryReportRow(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    by_period: list[SalaryReportCell | None]
    calculated: Decimal
    paid: Decimal
    balance: Decimal  # overall, as of today


class SalaryReportOut(BaseModel):
    periods: list[ReportPeriod]
    rows: list[SalaryReportRow]


# ---- helpers ---------------------------------------------------------------------------------------


async def _visible(session: AsyncSession, user: CurrentUser, permission: str) -> set[uuid.UUID] | None:
    """Employee ids the user may see under `permission` (None = everyone)."""
    scope = user.scope_for(permission)
    if scope == Scope.ALL:
        return None
    own = await employees.for_user(session, user.id)
    ids: set[uuid.UUID] = {own.id} if own else set()
    if scope == Scope.PROJECT:
        ids |= await projects.team_ids(session, await projects.visible_project_ids(session, user))
    return ids


async def _check_employee(session: AsyncSession, user: CurrentUser, permission: str, employee_id: uuid.UUID) -> None:
    visible = await _visible(session, user, permission)
    if visible is not None and employee_id not in visible:
        raise NotFound("Employee not found")
    await employees.get(session, employee_id)


def _period_out(p: SalaryPeriod, today: date) -> SalaryPeriodOut:
    out = SalaryPeriodOut.model_validate(p)
    out.is_current = p.start_date <= today <= p.end_date
    out.is_future = p.start_date > today
    return out


def _statement(line: service.Line, name: str) -> dict[str, Any]:
    p = line.period
    return {
        "period_id": p.id,
        "period_label": p.label,
        "period_start": p.start_date,
        "period_end": p.end_date,
        "period_status": p.status,
        "employee_id": line.employee_id,
        "employee_name": name,
        "revenue": line.revenue,
        "formula_id": line.formula_id,
        "formula_name": line.formula_name,
        "formula_version_no": line.formula_version_no,
        "rate": line.rate,
        "formula_amount": line.formula_amount,
        "adjustments_total": line.adjustments_total,
        "calculated": line.calculated,
        "paid": line.paid,
        "status": line.status,
        "frozen": line.frozen,
        "components": line.components,
    }


def _span(s: cycle.Span) -> SpanOut:
    return SpanOut(label=s.label, start_date=s.start, end_date=s.end, is_transition=s.is_transition)


# ---- periods and the board -------------------------------------------------------------------------


@router.get("/salary-periods", response_model=list[SalaryPeriodOut])
async def list_periods(_: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)) -> Any:
    periods = await service.list_periods(session)
    await session.commit()
    today = await settings.today(session)
    return [_period_out(p, today) for p in periods]


@router.get("/salary-periods/{period_id}/statements", response_model=BoardOut)
async def board(
    period_id: uuid.UUID,
    user: CurrentUser = Depends(require("salary.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """One row per employee: revenue, formula, calculated, paid (oldest-first matching) and balance."""
    period = await service.get_period(session, period_id)
    visible = await _visible(session, user, "salary.read")
    ids = list(visible) if visible is not None else None
    today = await settings.today(session)
    lines = await service.lines_for(session, period, ids)
    bal = await service.balances(session, list(lines), until=max(today, period.start_date)) if lines else {}
    for emp, line in lines.items():
        match = next(x for x in bal[emp].lines if x.period.id == period.id)
        line.paid = match.paid
    await session.commit()
    names = await employees.names(session, list(lines))
    rows = sorted(
        (BoardRow(**_statement(line, names.get(emp, "?")), balance=bal[emp].balance) for emp, line in lines.items()),
        key=lambda r: r.employee_name.lower(),
    )
    blocker = None
    if period.status == "closed":
        blocker = "Already closed"
    elif period.end_date >= today:
        blocker = f"Can be closed after {period.end_date.isoformat()}"
    return BoardOut(
        period=_period_out(period, today),
        rows=rows,
        total_revenue=sum((r.revenue for r in rows), Decimal(0)),
        total_calculated=sum((r.calculated for r in rows), Decimal(0)),
        total_paid=sum((r.paid for r in rows), Decimal(0)),
        can_close=blocker is None and user.can("salary.close_period"),
        close_blocker=blocker,
    )


@router.post("/salary-periods/{period_id}/close", response_model=SalaryPeriodOut)
async def close_period(
    period_id: uuid.UUID,
    actor: CurrentUser = Depends(require("salary.close_period")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    p = await service.close_period(session, actor_id=actor.id, period_id=period_id)
    await session.commit()
    return _period_out(p, await settings.today(session))


@router.post("/salary-periods/{period_id}/reopen", response_model=SalaryPeriodOut)
async def reopen_period(
    period_id: uuid.UUID,
    body: ReopenIn,
    actor: CurrentUser = Depends(require("salary.reopen_period")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    p = await service.reopen_period(session, actor_id=actor.id, period_id=period_id, reason=body.reason)
    await session.commit()
    return _period_out(p, await settings.today(session))


@router.get("/salary-periods/{period_id}/adjustments", response_model=list[AdjustmentOut])
async def list_adjustments(
    period_id: uuid.UUID,
    employee_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(require("salary.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    rows = await service.list_adjustments(session, period_id, employee_id)
    visible = await _visible(session, user, "salary.read")
    return [r for r in rows if visible is None or r.employee_id in visible]


@router.post("/salary-periods/{period_id}/adjustments", response_model=AdjustmentOut, status_code=201)
async def add_adjustment(
    period_id: uuid.UUID,
    body: AdjustmentIn,
    actor: CurrentUser = Depends(require("salary.adjust")),
    session: AsyncSession = Depends(get_session),
) -> SalaryAdjustment:
    adj = await service.add_adjustment(session, actor_id=actor.id, period_id=period_id, **body.model_dump())
    await session.commit()
    await session.refresh(adj)
    return adj


@router.delete("/salary-adjustments/{adjustment_id}", status_code=204)
async def delete_adjustment(
    adjustment_id: uuid.UUID,
    actor: CurrentUser = Depends(require("salary.adjust")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await service.delete_adjustment(session, actor_id=actor.id, adjustment_id=adjustment_id)
    await session.commit()
    return Response(status_code=204)


# ---- one employee ----------------------------------------------------------------------------------


async def _employee_salary(session: AsyncSession, employee_id: uuid.UUID) -> EmployeeSalaryOut:
    employee = await employees.get(session, employee_id)
    today = await settings.today(session)
    bal = (await service.balances(session, [employee_id], until=today)).get(employee_id) or service.Balance(employee_id)
    current_period = await service.period_for(session, today)
    resolved = (
        await compensation.resolve(
            session, start=current_period.start_date, end=current_period.end_date, employee_ids=[employee_id]
        )
    ).get(employee_id)
    pays = await service.payments_for(session, employee_id)
    numbers = await lookup.resolve(session, "payment_entry", [p.payment_entry_id for p in pays])
    labels = {line.period.id: line.period.label for line in bal.lines}
    await session.commit()
    statements = [StatementOut(**_statement(x, employee.full_name)) for x in reversed(bal.lines)]
    return EmployeeSalaryOut(
        employee_id=employee.id,
        employee_name=employee.full_name,
        calculated_total=bal.calculated,
        paid_total=bal.paid,
        balance=bal.balance,
        credit=bal.credit,
        formula=FormulaRef(
            formula_id=resolved.formula_id,
            formula_name=resolved.formula_name,
            version_no=resolved.version_no,
            definition=resolved.definition,
        )
        if resolved
        else None,
        current=next((s for s in statements if s.period_id == current_period.id), None),
        statements=statements,
        payments=[
            SalaryPaymentOut(
                payment_entry_id=p.payment_entry_id,
                number=numbers.get(p.payment_entry_id),
                paid_on=p.paid_on,
                amount=p.amount,
                period_label=labels.get(p.salary_period_id) if p.salary_period_id else None,
            )
            for p in pays
        ],
    )


@router.get("/employees/{employee_id}/salary", response_model=EmployeeSalaryOut)
async def employee_salary(
    employee_id: uuid.UUID,
    user: CurrentUser = Depends(require("salary.read")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeSalaryOut:
    await _check_employee(session, user, "salary.read", employee_id)
    return await _employee_salary(session, employee_id)


@router.get("/me/salary", response_model=EmployeeSalaryOut)
async def my_salary(
    user: CurrentUser = Depends(require("salary.read")), session: AsyncSession = Depends(get_session)
) -> EmployeeSalaryOut:
    own = await employees.for_user(session, user.id)
    if own is None:
        raise NotFound("Your user is not linked to an employee record")
    return await _employee_salary(session, own.id)


@router.get("/employees/{employee_id}/revenue", response_model=EmployeeRevenueOut)
async def employee_revenue(
    employee_id: uuid.UUID,
    salary_period_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(require("revenue.read")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeRevenueOut:
    """The payments behind an employee's revenue in one salary period (default: the current one)."""
    await _check_employee(session, user, "revenue.read", employee_id)
    today = await settings.today(session)
    period = (
        await service.get_period(session, salary_period_id)
        if salary_period_id
        else await service.period_for(session, today)
    )
    await session.commit()
    rows = await attribution.active_for_employee(
        session, employee_id=employee_id, date_from=period.start_date, date_to=period.end_date
    )
    numbers = await lookup.resolve(session, "payment_entry", [r.payment_entry_id for r in rows])
    project_names = await lookup.resolve(session, "project", [r.project_id for r in rows])
    by_project: dict[uuid.UUID | None, ProjectRevenue] = {}
    for r in rows:
        pr = by_project.setdefault(
            r.project_id,
            ProjectRevenue(
                project_id=r.project_id, project_name=project_names.get(r.project_id), revenue=Decimal(0), payments=0
            ),
        )
        pr.revenue += r.amount_base or Decimal(0)
        pr.payments += 1
    return EmployeeRevenueOut(
        employee_id=employee_id,
        employee_name=(await employees.names(session, [employee_id])).get(employee_id, "?"),
        period=_period_out(period, today),
        total=sum((r.amount_base or Decimal(0) for r in rows), Decimal(0)),
        by_project=sorted(by_project.values(), key=lambda x: -x.revenue),
        allocations=[
            RevenueAllocationOut(
                payment_entry_id=r.payment_entry_id,
                payment_number=numbers.get(r.payment_entry_id),
                date=r.attribution_date,  # type: ignore[arg-type]
                project_id=r.project_id,
                project_name=project_names.get(r.project_id),
                percent=r.percent,
                amount=r.amount_base or Decimal(0),
            )
            for r in rows
        ],
    )


# ---- cycle setting ---------------------------------------------------------------------------------


def _cycle_out(plan: service.CyclePlan, day: int) -> CycleOut:
    current = (
        SpanOut(
            label=plan.kept.label,
            start_date=plan.kept.start_date,
            end_date=plan.kept.end_date,
            is_transition=plan.kept.is_transition,
        )
        if plan.kept
        else None
    )
    return CycleOut(
        salary_cycle_start_day=day,
        current=current,
        upcoming=[_span(s) for s in plan.upcoming],
        replaces_all=plan.fresh,
        blockers=plan.blockers,
    )


@router.get("/settings/salary-cycle", response_model=CycleOut)
async def get_cycle(_: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)) -> CycleOut:
    day = (await settings.get_company(session)).salary_cycle_start_day
    plan = await service.plan_cycle(session, day)
    await session.commit()
    return _cycle_out(plan, day)


@router.post("/settings/salary-cycle/preview", response_model=CycleOut)
async def preview_cycle(
    body: CycleIn,
    _: CurrentUser = Depends(require("salary.configure_cycle")),
    session: AsyncSession = Depends(get_session),
) -> CycleOut:
    out = _cycle_out(await service.plan_cycle(session, body.salary_cycle_start_day), body.salary_cycle_start_day)
    await session.rollback()  # planning may have generated the current period; a preview changes nothing
    return out


@router.put("/settings/salary-cycle", response_model=CycleOut)
async def set_cycle(
    body: CycleIn,
    actor: CurrentUser = Depends(require("salary.configure_cycle")),
    session: AsyncSession = Depends(get_session),
) -> CycleOut:
    await service.set_cycle(session, actor_id=actor.id, day=body.salary_cycle_start_day)
    await session.commit()
    plan = await service.plan_cycle(session, body.salary_cycle_start_day)
    await session.commit()
    return _cycle_out(plan, body.salary_cycle_start_day)


# ---- reports ---------------------------------------------------------------------------------------


async def _report_periods(
    session: AsyncSession, from_id: uuid.UUID | None, to_id: uuid.UUID | None
) -> list[SalaryPeriod]:
    """Defaults to the last six periods up to the current one."""
    today = await settings.today(session)
    if from_id and to_id:
        return await service.periods_between(session, from_id, to_id)
    started = [p for p in reversed(await service.list_periods(session)) if p.start_date <= today]
    return started[-6:]


def _report_period(p: SalaryPeriod) -> ReportPeriod:
    return ReportPeriod(id=p.id, label=p.label, start_date=p.start_date, end_date=p.end_date, status=p.status)


@router.get("/reports/employee-revenue", response_model=RevenueReportOut)
async def revenue_report(
    from_period_id: uuid.UUID | None = None,
    to_period_id: uuid.UUID | None = None,
    format: Format = "json",
    user: CurrentUser = Depends(require("revenue.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Attributed revenue per employee per salary period."""
    periods = await _report_periods(session, from_period_id, to_period_id)
    await session.commit()
    visible = await _visible(session, user, "revenue.read")
    ids = list(visible) if visible is not None else None
    matrix: dict[uuid.UUID, list[Decimal]] = {}
    for i, p in enumerate(periods):
        totals = await attribution.employee_totals(
            session, date_from=p.start_date, date_to=p.end_date, employee_ids=ids
        )
        for emp, amount in totals.items():
            matrix.setdefault(emp, [Decimal(0)] * len(periods))[i] = amount
    names = await employees.names(session, list(matrix))
    rows = sorted(
        (
            RevenueReportRow(employee_id=e, employee_name=names.get(e, "?"), by_period=v, total=sum(v, Decimal(0)))
            for e, v in matrix.items()
        ),
        key=lambda r: -r.total,
    )
    totals = [sum((r.by_period[i] for r in rows), Decimal(0)) for i in range(len(periods))]
    if format == "csv":
        return csv_response(
            "employee-revenue.csv",
            ["employee", *(p.label for p in periods), "total"],
            [
                *([r.employee_name, *r.by_period, r.total] for r in rows),
                ["Total", *totals, sum(totals, Decimal(0))],
            ],
        )
    return RevenueReportOut(
        periods=[_report_period(p) for p in periods], rows=rows, totals=totals, total=sum(totals, Decimal(0))
    )


@router.get("/reports/employee-salary", response_model=SalaryReportOut)
async def salary_report(
    from_period_id: uuid.UUID | None = None,
    to_period_id: uuid.UUID | None = None,
    format: Format = "json",
    user: CurrentUser = Depends(require("salary.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Revenue, calculated and paid salary per employee per period, with today's balance."""
    periods = await _report_periods(session, from_period_id, to_period_id)
    visible = await _visible(session, user, "salary.read")
    today = await settings.today(session)
    bal = await service.balances(
        session, list(visible) if visible is not None else None, until=max([today, *(p.start_date for p in periods)])
    )
    await session.commit()
    index = {p.id: i for i, p in enumerate(periods)}
    names = await employees.names(session, list(bal))
    rows = []
    for emp, b in bal.items():
        cells: list[SalaryReportCell | None] = [None] * len(periods)
        for line in b.lines:
            if line.period.id in index:
                cells[index[line.period.id]] = SalaryReportCell(
                    revenue=line.revenue, calculated=line.calculated, paid=line.paid, status=line.status
                )
        if not any(cells) and not b.balance:
            continue
        rows.append(
            SalaryReportRow(
                employee_id=emp,
                employee_name=names.get(emp, "?"),
                by_period=cells,
                calculated=sum((c.calculated for c in cells if c), Decimal(0)),
                paid=sum((c.paid for c in cells if c), Decimal(0)),
                balance=b.balance,
            )
        )
    rows.sort(key=lambda r: r.employee_name.lower())
    if format == "csv":
        return csv_response(
            "employee-salary.csv",
            ["employee", "period", "start", "end", "revenue", "calculated", "paid", "status"],
            [
                (r.employee_name, p.label, p.start_date, p.end_date, c.revenue, c.calculated, c.paid, c.status)
                for r in rows
                for p, c in zip(periods, r.by_period, strict=True)
                if c
            ],
        )
    return SalaryReportOut(periods=[_report_period(p) for p in periods], rows=rows)
