"""Phase 4: milestones, tasks, Kanban order, dependencies, time, comments, timeline, project financials."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest

from app.core import clock
from app.modules.tasks import rank
from tests.conftest import ClientFactory
from tests.factories import category_id, customer, employee, payment_account_id, project, receipt_body
from tests.test_payments import create_and_submit

D = Decimal
API = "/api/v1"


@pytest.fixture(autouse=True)
def today() -> Iterator[None]:
    clock.freeze(date(2026, 11, 10))
    yield
    clock.freeze(None)


def test_rank_between_is_strictly_between() -> None:
    a = rank.first()
    b = rank.between(a, None)
    assert a < b
    mid = rank.between(a, b)
    assert a < mid < b
    # Repeated inserts at the same spot keep working (no collisions, no trailing zeros).
    lo, hi = a, b
    for _ in range(40):
        m = rank.between(lo, hi)
        assert lo < m < hi and not m.endswith("0")
        hi = m
    with pytest.raises(ValueError):
        rank.between(b, a)


@pytest.fixture
async def setup(admin, client_as: ClientFactory) -> dict:  # type: ignore[no-untyped-def]
    staff = await client_as("employee")
    abc = await customer("Customer ABC")
    a = await employee("Employee A", user_id=staff.user_id)
    b = await employee("Employee B")
    p = await project("ABC Web Platform", abc, [(a, D(60)), (b, D(40))])
    return {"staff": staff, "a": a, "b": b, "project": p, "customer": abc}


async def new_task(c, project_id: str, title: str, **extra) -> dict:  # type: ignore[no-untyped-def]
    res = await c.post(f"{API}/tasks", json={"project_id": project_id, "title": title, **extra})
    assert res.status_code == 201, res.text
    return res.json()


async def test_tasks_board_and_permissions(admin, setup) -> None:  # type: ignore[no-untyped-def]
    p, staff = setup["project"], setup["staff"]
    ms = await admin.post(f"{API}/projects/{p}/milestones", json={"name": "Beta", "due_date": "2026-11-30"})
    assert ms.status_code == 201
    t1 = await new_task(
        admin, p, "Design", assignee_ids=[setup["a"]], estimate_hours="10", milestone_id=ms.json()["id"]
    )
    t2 = await new_task(admin, p, "Build", estimate_hours="30")
    t3 = await new_task(admin, p, "Test")
    assert t1["number"].startswith("TSK-") and t1["assignees"][0]["name"] == "Employee A"
    board = (await admin.get(f"{API}/tasks", params={"project_id": p, "status": ["todo"]})).json()["items"]
    assert [t["title"] for t in board] == ["Design", "Build", "Test"]

    # Drag "Test" between "Design" and "Build".
    moved = await admin.post(
        f"{API}/tasks/{t3['id']}/move",
        json={"version": t3["version"], "status": "todo", "before_id": t1["id"], "after_id": t2["id"]},
    )
    assert moved.status_code == 200, moved.text
    board = (await admin.get(f"{API}/tasks", params={"project_id": p, "status": ["todo"]})).json()["items"]
    assert [t["title"] for t in board] == ["Design", "Test", "Build"]
    stale = await admin.post(f"{API}/tasks/{t3['id']}/move", json={"version": t3["version"], "status": "done"})
    assert stale.status_code == 412

    # An assignee (employee role) may move their own task but not edit it or touch others.
    mine = (await staff.get(f"{API}/tasks", params={"assignee": "me"})).json()["items"]
    assert [t["title"] for t in mine] == ["Design"] and mine[0]["can_move"] and not mine[0]["can_edit"]
    ok = await staff.post(f"{API}/tasks/{t1['id']}/move", json={"version": t1["version"], "status": "in_progress"})
    assert ok.status_code == 200
    assert (
        await staff.patch(f"{API}/tasks/{t1['id']}", json={"version": ok.json()["version"], "title": "x"})
    ).status_code == 403
    assert (
        await staff.post(f"{API}/tasks/{t2['id']}/move", json={"version": t2["version"], "status": "done"})
    ).status_code == 403
    assert (await staff.post(f"{API}/tasks", json={"project_id": p, "title": "x"})).status_code == 403
    done = await staff.patch(f"{API}/tasks/{t1['id']}", json={"version": ok.json()["version"], "status": "done"})
    assert done.status_code == 200 and done.json()["completed_at"]

    # Progress is estimate-weighted: 10 h of 41 h done (Test has no estimate and counts as 1 h).
    progress = (await admin.get(f"{API}/tasks/progress", params={"project_ids": [p]})).json()[0]
    assert (progress["total"], progress["done"], progress["percent"]) == (3, 1, "24.4")


async def test_subtasks_dependencies_time_comments_timeline(admin, setup) -> None:  # type: ignore[no-untyped-def]
    p, staff = setup["project"], setup["staff"]
    parent = await new_task(admin, p, "Release", start_date="2026-11-01", due_date="2026-11-20")
    child = await new_task(admin, p, "Write docs", parent_task_id=parent["id"], assignee_ids=[setup["a"]])
    under_child = await admin.patch(
        f"{API}/tasks/{parent['id']}", json={"version": parent["version"], "parent_task_id": child["id"]}
    )
    assert under_child.status_code == 422  # can't sit under its own subtask
    detail = (await admin.get(f"{API}/tasks/{parent['id']}")).json()
    assert [c["title"] for c in detail["children"]] == ["Write docs"] and detail["subtasks"] == 1

    a = await new_task(admin, p, "API", start_date="2026-11-01", due_date="2026-11-05", estimate_hours="8")
    b = await new_task(admin, p, "UI", start_date="2026-11-04", due_date="2026-11-12")
    assert (
        await admin.post(f"{API}/tasks/{b['id']}/dependencies", json={"depends_on_task_id": a["id"]})
    ).status_code == 200
    cycle = await admin.post(f"{API}/tasks/{a['id']}/dependencies", json={"depends_on_task_id": b["id"]})
    assert cycle.status_code == 422 and cycle.json()["errors"][0]["code"] == "cycle"
    assert (await admin.get(f"{API}/tasks/{a['id']}")).json()["blocking"][0]["title"] == "UI"

    # Time: assignees log their own; at most 24 h a day.
    assert (
        await staff.post(f"{API}/tasks/{a['id']}/time-entries", json={"work_date": "2026-11-03", "hours": "2"})
    ).status_code == 403
    logged = await staff.post(f"{API}/tasks/{child['id']}/time-entries", json={"work_date": "2026-11-03", "hours": "6"})
    assert logged.status_code == 201 and logged.json()["employee_name"] == "Employee A"
    too_much = await staff.post(
        f"{API}/tasks/{child['id']}/time-entries", json={"work_date": "2026-11-03", "hours": "19"}
    )
    assert too_much.status_code == 422
    await admin.post(
        f"{API}/tasks/{a['id']}/time-entries", json={"work_date": "2026-11-03", "hours": "4", "employee_id": setup["b"]}
    )
    assert (await admin.delete(f"{API}/tasks/{parent['id']}")).status_code == 409  # time logged on a subtask

    # Anyone on the project can comment; only the author (or a manager) deletes.
    c = await staff.post(f"{API}/tasks/{a['id']}/comments", json={"body": "Blocked on the API key"})
    assert c.status_code == 201 and c.json()["author_name"]
    comments = (await admin.get(f"{API}/tasks/{a['id']}/comments")).json()
    assert [x["body"] for x in comments] == ["Blocked on the API key"]

    # Timeline: "API" ends Nov 5, after "UI" (which waits for it) starts Nov 4: delayed.
    tl = (await admin.get(f"{API}/projects/{p}/timeline")).json()
    rows = {t["title"]: t for t in tl["tasks"]}
    assert rows["API"]["delayed"] is True and rows["API"]["progress"] == "50"
    assert rows["UI"]["depends_on"] == [a["id"]] and rows["UI"]["delayed"] is False
    assert tl["can_edit"] is True and tl["today"] == "2026-11-10"


async def test_outsiders_cannot_see_tasks(admin, client_as: ClientFactory, setup) -> None:  # type: ignore[no-untyped-def]
    t = await new_task(admin, setup["project"], "Secret")
    outsider = await client_as("employee")  # not linked to an employee on the project
    assert (await outsider.get(f"{API}/tasks/{t['id']}")).status_code == 404
    assert (await outsider.get(f"{API}/tasks")).json()["items"] == []


async def test_project_financials_and_salary_cost_per_project(admin, client_as: ClientFactory, setup) -> None:  # type: ignore[no-untyped-def]
    """Section 11.1 with the Section 16 numbers: A $626.67 paid, B $352.59 owed."""
    finance = await client_as("finance_manager")
    await admin.put(f"{API}/settings/salary-cycle", json={"salary_cycle_start_day": 25})
    formula = next(f for f in (await admin.get(f"{API}/comp-formulas")).json() if f["name"].startswith("Revenue Share"))
    for e in (setup["a"], setup["b"]):
        await admin.post(
            f"{API}/comp-assignments",
            json={"employee_id": e, "formula_id": formula["id"], "effective_from": "2026-01-01"},
        )
    p = setup["project"]
    version = (await admin.get(f"{API}/projects/{p}")).json()["version"]
    budget = await admin.patch(f"{API}/projects/{p}", json={"version": version, "budget": "2000"})
    assert budget.status_code == 200, budget.text
    await create_and_submit(finance, await receipt_body(party_id=setup["customer"], project_id=p))
    hosting = {
        "posting_date": "2026-11-12",
        "direction": "pay",
        "amount": "500",
        "method_category_id": await category_id("payment_method", "bank_transfer"),
        "purpose_category_id": await category_id("payment_purpose", "operating_expense"),
        "category_id": await category_id("expense_category", "cloud_infrastructure"),
        "paid_from_payment_account_id": await payment_account_id("Company Checking"),
        "project_id": p,
    }
    await create_and_submit(finance, hosting)
    party_a = (await admin.get(f"{API}/employees/{setup['a']}")).json()["party_id"]
    salary = await create_and_submit(
        finance,
        {
            "posting_date": "2026-11-20",
            "direction": "pay",
            "amount": "626.67",
            "method_category_id": await category_id("payment_method", "bank_transfer"),
            "purpose_category_id": await category_id("payment_purpose", "employee_salary"),
            "paid_from_payment_account_id": await payment_account_id("Company Checking"),
            "party_id": party_a,
        },
    )
    # The salary expense line is tagged with the project A earned on.
    je = (await finance.get(f"{API}/journal-entries/{salary['journal_entry_id']}")).json()
    salary_lines = [ln for ln in je["lines"] if ln["account_code"] == "5100"]
    assert [ln["project_id"] for ln in salary_lines] == [p]

    f = (await finance.get(f"{API}/projects/{p}/financials")).json()
    assert D(f["revenue"]) == 10000 and D(f["attributed_revenue"]) == 10000
    assert D(f["direct_expenses"]) == 500 and D(f["salary_paid"]) == D("626.67")
    assert D(f["salary_owed"]) == D("352.59")
    assert D(f["profit_cash"]) == D("8873.33") and D(f["profit_incl_owed"]) == D("8520.74")
    assert D(f["budget_remaining"]) == D("873.33") and D(f["contract_remaining"]) == 0
    report = (await finance.get(f"{API}/reports/project-profitability")).json()
    assert report[0]["number"] == f["number"]
    staff = setup["staff"]
    assert (await staff.get(f"{API}/projects/{p}/financials")).status_code == 403  # employees don't see financials


async def test_project_manager_sees_only_own_money(admin, client_as: ClientFactory) -> None:  # type: ignore[no-untyped-def]
    """A project manager sees their own revenue, never a teammate's, and no whole-project financials."""
    finance = await client_as("finance_manager")
    pm = await client_as("project_manager")
    abc = await customer("Customer PM")
    mine = await employee("Manager M", user_id=pm.user_id)
    other = await employee("Teammate T")
    p = await project("PM Project", abc, [(mine, D(50)), (other, D(50))], manager_id=mine)
    await create_and_submit(finance, await receipt_body(party_id=abc, project_id=p))

    report = (await pm.get(f"{API}/reports/employee-revenue")).json()
    assert [r["employee_name"] for r in report["rows"]] == ["Manager M"]
    assert (await pm.get(f"{API}/employees/{mine}/revenue")).status_code == 200
    assert (await pm.get(f"{API}/employees/{other}/revenue")).status_code == 404
    for path in (f"/projects/{p}/financials", f"/projects/{p}/financials/trend", "/reports/project-profitability"):
        assert (await pm.get(f"{API}{path}")).status_code == 403, path
    # Finance still sees everyone.
    names = {r["employee_name"] for r in (await finance.get(f"{API}/reports/employee-revenue")).json()["rows"]}
    assert {"Manager M", "Teammate T"} <= names
