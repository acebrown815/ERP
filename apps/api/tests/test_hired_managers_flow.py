"""Hired managers, end to end: projects, payment, what each person sees, monitoring (docs/hired-managers-plan.md)."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.core import clock
from app.core.db import SessionLocal
from app.modules.compensation import api as compensation
from app.modules.payments import checks
from app.modules.salary import service as salary_service
from tests.conftest import ClientFactory
from tests.factories import category_id, customer, employee, payment_account_id, project, receipt_body
from tests.test_payments import create_and_submit

API = "/api/v1"
D = Decimal
ON = date(2026, 11, 10)
RANGE = {"from": "2026-11-01", "to": "2026-11-30"}


@pytest.fixture(autouse=True)
def today() -> Iterator[None]:
    clock.freeze(ON)
    yield
    clock.freeze(None)


@dataclass
class Person:
    id: str
    client: httpx.AsyncClient


async def _ptype() -> str:
    return await category_id("project_type", "web_development")


async def _manager(client_as: ClientFactory, name: str) -> Person:
    client = await client_as("employee")
    return Person(await employee(name, user_id=client.user_id), client)  # type: ignore[attr-defined]


async def _hire(admin: httpx.AsyncClient, client_as: ClientFactory, name: str = "Jordan Hire") -> Person:
    return await _hire_for(admin, await client_as("hired_manager"), name)


async def _hire_for(admin: httpx.AsyncClient, client: httpx.AsyncClient, name: str) -> Person:
    res = await admin.post(
        f"{API}/employees",
        json={
            "full_name": name,
            "employment_type_category_id": await category_id("employment_type", "contractor"),
            "start_date": "2026-01-01",
            "is_hired_manager": True,
            "user_id": client.user_id,  # type: ignore[attr-defined]
        },
    )
    assert res.status_code == 201, res.text
    return Person(res.json()["id"], client)


async def _own_project(manager: Person, name: str = "Website", hire: Person | None = None) -> dict:
    res = await manager.client.post(
        f"{API}/projects",
        json={"name": name, "project_type_category_id": await _ptype(), "hire_employee_id": hire.id if hire else None},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _on_formula(employee_id: str) -> None:
    async with SessionLocal() as s:
        formula = await compensation.default_formula(s)
        await compensation.create_assignment(
            s,
            actor_id=None,
            employee_id=uuid.UUID(employee_id),
            formula_id=formula.id,
            effective_from=date(2026, 1, 1),
        )
        await s.commit()


async def _receipt(admin: httpx.AsyncClient, project_id: str, manager_id: str, amount: str) -> dict:
    return await create_and_submit(
        admin,
        await receipt_body(
            party_id=await customer(f"Customer {uuid.uuid4().hex[:6]}"),
            project_id=project_id,
            amount=amount,
            allocations=[{"employee_id": manager_id, "percent": "100"}],
        ),
    )


async def _party_of(admin: httpx.AsyncClient, employee_id: str) -> str:
    return (await admin.get(f"{API}/employees/{employee_id}")).json()["party_id"]


async def _hire_payment_body(
    admin: httpx.AsyncClient, project_id: str, hire_id: str, amount: str, **extra: object
) -> dict:
    return {
        "posting_date": ON.isoformat(),
        "direction": "pay",
        "purpose_category_id": await category_id("payment_purpose", "hire_payment"),
        "method_category_id": await category_id("payment_method", "bank_transfer"),
        "paid_from_payment_account_id": await payment_account_id("Company Checking"),
        "party_id": await _party_of(admin, hire_id),
        "project_id": project_id,
        "amount": amount,
        "description": "Internal note about this fee",
        **extra,
    }


async def _submit_errors(admin: httpx.AsyncClient, body: dict) -> set[str]:
    draft = await admin.post(f"{API}/payment-entries", json=body)
    assert draft.status_code == 201, draft.text
    res = await admin.post(
        f"{API}/payment-entries/{draft.json()['id']}/submit", headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    assert res.status_code == 422, res.text
    return {e["field"] for e in res.json()["errors"]}


async def _salary_line(employee_id: str) -> salary_service.Line:
    async with SessionLocal() as s:
        balances = await salary_service.balances(s, [uuid.UUID(employee_id)], until=date(2026, 11, 30))
    lines = balances[uuid.UUID(employee_id)].lines
    return next(x for x in lines if x.period.start_date <= ON <= x.period.end_date)


# ---- an employee creates a project and selects a hire ------------------------------------------------


async def test_an_employee_creates_a_project_and_selects_a_hire(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    assert created["manager_employee_id"] == manager.id and created["manager_name"] == "Avery Manager"
    assert created["hire_employee_id"] == hire.id and created["hire_name"] == "Jordan Hire"
    assert created["edit_mode"] == "own"
    assert [(m["employee_id"], D(m["default_allocation_pct"])) for m in created["members"]] == [(manager.id, D(100))]


async def test_an_employee_can_run_a_project_without_a_hire(client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    created = await _own_project(manager)
    assert created["manager_employee_id"] == manager.id and created["hire_employee_id"] is None


async def test_an_employee_cant_set_money_or_name_someone_else_as_manager(client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    colleague = await employee("Colleague")
    res = await manager.client.post(
        f"{API}/projects",
        json={
            "name": "Website",
            "project_type_category_id": await _ptype(),
            "manager_employee_id": colleague,
            "contract_value": "5000",
            "budget": "100",
            "customer_party_id": await customer(),
            "members": [{"employee_id": colleague, "default_allocation_pct": "100"}],
        },
    )
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["manager_employee_id"] == manager.id
    assert created["contract_value"] is None and created["budget"] is None and created["customer_party_id"] is None
    assert [m["employee_id"] for m in created["members"]] == [manager.id]


async def test_the_owner_edits_the_work_and_the_hire_but_not_the_money_or_team(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager)
    url = f"{API}/projects/{created['id']}"

    res = await manager.client.patch(
        url, json={"version": created["version"], "name": "Renamed", "hire_employee_id": hire.id}
    )
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Renamed" and res.json()["hire_employee_id"] == hire.id
    version = res.json()["version"]

    for change in ({"contract_value": "5000"}, {"budget": "1"}, {"manager_employee_id": await employee("Other")}):
        assert (await manager.client.patch(url, json={"version": version, **change})).status_code == 403
    assert (await manager.client.put(f"{url}/members", json={"members": []})).status_code == 403
    res = await manager.client.patch(url, json={"version": version, "members": []})
    assert res.status_code == 403


async def test_the_owner_can_remove_the_hire_who_then_loses_access(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    url = f"{API}/projects/{created['id']}"
    assert (await hire.client.get(url)).status_code == 200
    res = await manager.client.patch(url, json={"version": created["version"], "hire_employee_id": None})
    assert res.status_code == 200 and res.json()["hire_employee_id"] is None
    assert (await hire.client.get(url)).status_code == 404


async def test_the_manager_runs_tasks_and_another_team_member_cant(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    res = await manager.client.post(
        f"{API}/tasks", json={"project_id": created["id"], "title": "Kickoff", "assignee_ids": [hire.id]}
    )
    assert res.status_code == 201, res.text
    assert res.json()["assignees"][0]["name"] == "Jordan Hire" and res.json()["can_edit"] is True

    teammate = await _manager(client_as, "Teammate")
    current = (await admin.get(f"{API}/projects/{created['id']}")).json()
    res = await admin.patch(
        f"{API}/projects/{created['id']}",
        json={
            "version": current["version"],
            "members": [
                {"employee_id": manager.id, "default_allocation_pct": "100"},
                {"employee_id": teammate.id},
            ],
        },
    )
    assert res.status_code == 200, res.text
    res = await teammate.client.post(f"{API}/tasks", json={"project_id": created["id"], "title": "Nope"})
    assert res.status_code == 403
    assert (
        await teammate.client.patch(f"{API}/projects/{created['id']}", json={"version": 9, "name": "x"})
    ).status_code == 403


async def test_the_task_screens_can_load_their_page_size(admin: httpx.AsyncClient) -> None:
    """The Tasks tab, Tasks page and Kanban board all ask for 500 tasks at a time."""
    assert (await admin.get(f"{API}/tasks", params={"page_size": 500})).status_code == 200
    assert (await admin.get(f"{API}/tasks", params={"page_size": 501})).status_code == 422


async def test_tasks_can_only_go_to_the_project_team(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    outsider = await employee("Outsider")
    for person in (manager, hire):
        res = await person.client.post(
            f"{API}/tasks", json={"project_id": created["id"], "title": "Task", "assignee_ids": [outsider]}
        )
        assert res.status_code == 422, res.text
        assert res.json()["errors"][0]["field"] == "assignee_ids"


async def test_an_existing_manager_gains_only_the_limited_rights(client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    project_id = await project("Existing", await customer(), [(manager.id, D(100))], manager_id=manager.id)
    current = (await manager.client.get(f"{API}/projects/{project_id}")).json()
    assert current["edit_mode"] == "own"
    res = await manager.client.patch(
        f"{API}/projects/{project_id}", json={"version": current["version"], "budget": "1"}
    )
    assert res.status_code == 403


async def test_a_regular_project_manager_keeps_full_rights(client_as: ClientFactory) -> None:
    client = await client_as("project_manager")
    me = await employee("Regular PM", user_id=client.user_id)  # type: ignore[attr-defined]
    project_id = await project("Existing", await customer(), [(me, D(100))], manager_id=me)
    current = (await client.get(f"{API}/projects/{project_id}")).json()
    assert current["edit_mode"] == "full"
    res = await client.patch(f"{API}/projects/{project_id}", json={"version": current["version"], "budget": "100"})
    assert res.status_code == 200 and D(res.json()["budget"]) == 100
    assert (await client.put(f"{API}/projects/{project_id}/members", json={"members": []})).status_code == 200


async def test_a_project_manager_creating_for_someone_else_gets_no_error(client_as: ClientFactory) -> None:
    """The form now saves the team with the project, so there's no second call to fail after the save."""
    client = await client_as("project_manager")
    await employee("Regular PM", user_id=client.user_id)  # type: ignore[attr-defined]
    other = await employee("Other")
    res = await client.post(
        f"{API}/projects",
        json={
            "name": "For someone else",
            "project_type_category_id": await _ptype(),
            "manager_employee_id": other,
            "members": [{"employee_id": other, "default_allocation_pct": "100"}],
        },
    )
    assert res.status_code == 201, res.text


# ---- the rules that keep the money and the project together ------------------------------------------


async def test_staff_set_a_hire_and_a_split_in_one_save(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    hire = await _hire(admin, client_as)
    manager = await employee("Avery Manager")
    res = await admin.post(
        f"{API}/projects",
        json={
            "name": "Website",
            "project_type_category_id": await _ptype(),
            "manager_employee_id": manager,
            "hire_employee_id": hire.id,
            "members": [{"employee_id": manager, "default_allocation_pct": "100"}],
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["edit_mode"] == "full"


async def test_a_hire_needs_a_manager_who_earns_from_the_project(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    hire = await _hire(admin, client_as)
    pm = await employee("Staff PM")
    earner = await employee("Earner")
    base = {"name": "Website", "project_type_category_id": await _ptype(), "hire_employee_id": hire.id}

    res = await admin.post(f"{API}/projects", json=base)
    assert res.status_code == 422 and res.json()["errors"][0]["field"] == "hire_employee_id"

    res = await admin.post(
        f"{API}/projects",
        json={
            **base,
            "manager_employee_id": pm,
            "members": [{"employee_id": pm}, {"employee_id": earner, "default_allocation_pct": "100"}],
        },
    )
    assert res.status_code == 422 and res.json()["errors"][0]["field"] == "hire_employee_id"


async def test_the_manager_cant_lose_their_split_while_there_is_a_hire(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    url = f"{API}/projects/{created['id']}/members"
    assert (await admin.put(url, json={"members": []})).status_code == 422
    assert (await admin.put(url, json={"members": [{"employee_id": manager.id}]})).status_code == 422
    # Nothing was saved by the failed attempts.
    assert D((await admin.get(f"{API}/projects/{created['id']}")).json()["members"][0]["default_allocation_pct"]) == 100


async def test_only_an_active_hire_can_be_selected(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    regular = await employee("Regular Person")
    res = await manager.client.post(
        f"{API}/projects",
        json={"name": "Website", "project_type_category_id": await _ptype(), "hire_employee_id": regular},
    )
    assert res.status_code == 422 and res.json()["errors"][0]["field"] == "hire_employee_id"


# ---- what a hire can do on a project ---------------------------------------------------------------


async def test_a_hire_sees_the_work_and_the_customer_but_not_the_money(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    hire = await _hire(admin, client_as)
    manager = await employee("Avery Manager")
    client_party = await customer("Acme Corp")
    res = await admin.post(
        f"{API}/projects",
        json={
            "name": "Website",
            "project_type_category_id": await _ptype(),
            "manager_employee_id": manager,
            "hire_employee_id": hire.id,
            "customer_party_id": client_party,
            "contract_value": "10000",
            "budget": "2000",
            "members": [{"employee_id": manager, "default_allocation_pct": "100"}],
        },
    )
    assert res.status_code == 201, res.text
    seen = (await hire.client.get(f"{API}/projects/{res.json()['id']}")).json()
    assert seen["customer_name"] == "Acme Corp" and seen["manager_name"] == "Avery Manager"
    assert seen["edit_mode"] is None
    assert seen["contract_value"] is None and seen["budget"] is None and seen["customer_party_id"] is None
    assert seen["members"][0]["default_allocation_pct"] is None
    assert seen["members"][0]["employee_name"] == "Avery Manager"
    # Staff still see the money.
    assert D((await admin.get(f"{API}/projects/{res.json()['id']}")).json()["contract_value"]) == 10000


async def test_a_hire_manages_tasks_and_nothing_else_on_a_project(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    url = f"{API}/projects/{created['id']}"
    assert (await hire.client.get(url)).json()["edit_mode"] is None
    for change in (
        {"description": "Scope"},
        {"name": "Renamed"},
        {"status": "completed"},
        {"budget": "1"},
        {"hire_employee_id": None},
        {"members": []},
    ):
        assert (await hire.client.patch(url, json={"version": created["version"], **change})).status_code == 403
    assert (await hire.client.put(f"{url}/members", json={"members": []})).status_code == 403

    # Milestones are read-only: staff and the manager run them.
    milestone = (await manager.client.post(f"{url}/milestones", json={"name": "Launch"})).json()
    assert [m["id"] for m in (await hire.client.get(f"{url}/milestones")).json()] == [milestone["id"]]
    assert (await hire.client.post(f"{url}/milestones", json={"name": "Nope"})).status_code == 403
    edit = {"version": milestone["version"], "name": "Hacked"}
    assert (await hire.client.patch(f"{API}/milestones/{milestone['id']}", json=edit)).status_code == 403
    assert (await hire.client.delete(f"{API}/milestones/{milestone['id']}")).status_code == 403

    # Tasks are theirs to manage, from start to finish.
    task = await hire.client.post(
        f"{API}/tasks", json={"project_id": created["id"], "title": "Build", "assignee_ids": [hire.id]}
    )
    assert task.status_code == 201 and task.json()["can_edit"] is True
    tid, version = task.json()["id"], task.json()["version"]
    res = await hire.client.patch(f"{API}/tasks/{tid}", json={"version": version, "title": "Build it"})
    assert res.status_code == 200, res.text
    res = await hire.client.post(f"{API}/tasks/{tid}/comments", json={"body": "Started"})
    assert res.status_code in (200, 201), res.text
    res = await hire.client.post(f"{API}/tasks/{tid}/time-entries", json={"work_date": ON.isoformat(), "hours": "2"})
    assert res.status_code in (200, 201), res.text
    other = await hire.client.post(f"{API}/tasks", json={"project_id": created["id"], "title": "Spare"})
    assert (await hire.client.delete(f"{API}/tasks/{other.json()['id']}")).status_code == 204


async def test_a_hire_cant_create_a_project(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    await _own_project(manager, hire=hire)
    res = await hire.client.post(
        f"{API}/projects",
        json={"name": "Nope", "project_type_category_id": await _ptype(), "manager_employee_id": manager.id},
    )
    assert res.status_code == 403, res.text
    assert len((await admin.get(f"{API}/projects")).json()["items"]) == 1


async def test_a_hire_sees_only_the_projects_connected_to_them(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    a = await _manager(client_as, "Avery Manager")
    b = await _manager(client_as, "Blake Manager")
    hire = await _hire(admin, client_as)
    assert (await hire.client.get(f"{API}/projects")).json()["items"] == []
    assert (await hire.client.get(f"{API}/projects/my-managers")).json() == []

    connected = await _own_project(a, "Connected", hire=hire)
    other = await _own_project(b, "Not connected")
    listed = [p["id"] for p in (await hire.client.get(f"{API}/projects")).json()["items"]]
    assert listed == [connected["id"]]
    assert (await hire.client.get(f"{API}/projects/{other['id']}")).status_code == 404
    assert (await hire.client.get(f"{API}/projects/my-managers")).json() == [{"id": a.id, "full_name": "Avery Manager"}]

    # Connecting them later works the same way, and removing them takes the project away again.
    res = await b.client.patch(
        f"{API}/projects/{other['id']}", json={"version": other["version"], "hire_employee_id": hire.id}
    )
    assert res.status_code == 200, res.text
    assert (await hire.client.get(f"{API}/projects/{other['id']}")).status_code == 200
    res = await b.client.patch(
        f"{API}/projects/{other['id']}", json={"version": res.json()["version"], "hire_employee_id": None}
    )
    assert res.status_code == 200, res.text
    assert (await hire.client.get(f"{API}/projects/{other['id']}")).status_code == 404


@pytest.mark.parametrize(
    "role", ["hired_manager", "employee", "project_manager", "finance_manager", "supervisor", None]
)
async def test_the_role_on_a_hires_sign_in_changes_nothing(
    admin: httpx.AsyncClient, client_as: ClientFactory, role: str | None
) -> None:
    client = await client_as(role)
    hire = await _hire_for(admin, client, "Jordan Hire")
    manager = await _manager(client_as, "Avery Manager")
    connected = await _own_project(manager, "Connected", hire=hire)
    other = await _own_project(manager, "Not connected")

    me = (await client.get(f"{API}/auth/me")).json()
    assert me["restricted_access"] is True
    assert set(me["permissions"]) == {
        "projects.read",
        "tasks.manage",
        "tasks.update_own",
        "payments.read_own",
    }
    assert [p["id"] for p in (await client.get(f"{API}/projects")).json()["items"]] == [connected["id"]]
    assert (await client.get(f"{API}/projects/{other['id']}")).status_code == 404
    assert (await client.get(f"{API}/reports/project-profitability")).status_code == 403
    res = await client.post(f"{API}/projects", json={"name": "Nope", "project_type_category_id": await _ptype()})
    assert res.status_code == 403
    task = await client.post(f"{API}/tasks", json={"project_id": connected["id"], "title": "Works"})
    assert task.status_code == 201, task.text


async def test_the_role_alone_gives_a_sign_in_nothing_until_it_is_linked(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    """A sign-in with the Hired Manager role, and a hire record with no sign-in, aren't connected yet."""
    client = await client_as("hired_manager")
    res = await admin.post(
        f"{API}/employees",
        json={
            "full_name": "Donald Hire",
            "employment_type_category_id": await category_id("employment_type", "contractor"),
            "start_date": "2026-01-01",
            "is_hired_manager": True,
        },
    )
    hire = res.json()
    manager = await _manager(client_as, "Avery Manager")
    created = await _own_project(manager, hire=Person(hire["id"], client))

    me = (await client.get(f"{API}/auth/me")).json()
    assert me["restricted_access"] is False and me["permissions"] == {}
    assert (await client.get(f"{API}/projects")).status_code == 403
    res = await client.post(f"{API}/projects", json={"name": "Nope", "project_type_category_id": await _ptype()})
    assert res.status_code == 403

    # Linking the sign-in is all it takes.
    res = await admin.patch(
        f"{API}/employees/{hire['id']}", json={"version": hire["version"], "user_id": client.user_id}
    )  # type: ignore[attr-defined]
    assert res.status_code == 200, res.text
    me = (await client.get(f"{API}/auth/me")).json()
    assert me["restricted_access"] is True and "projects.read" in me["permissions"]
    assert [p["id"] for p in (await client.get(f"{API}/projects")).json()["items"]] == [created["id"]]


async def test_an_administrator_cant_be_marked_as_a_hire(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    other_admin = await client_as("admin")
    res = await admin.post(
        f"{API}/employees",
        json={
            "full_name": "Admin Person",
            "employment_type_category_id": await category_id("employment_type", "contractor"),
            "start_date": "2026-01-01",
            "is_hired_manager": True,
            "user_id": other_admin.user_id,  # type: ignore[attr-defined]
        },
    )
    assert res.status_code == 422 and res.json()["errors"][0]["field"] == "is_hired_manager"


# ---- paying the hire -------------------------------------------------------------------------------


async def test_the_payment_comes_off_the_managers_revenue_and_cancelling_restores_it(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    await _on_formula(manager.id)
    created = await _own_project(manager, hire=hire)
    await _receipt(admin, created["id"], manager.id, "6000.00")
    assert (await _salary_line(manager.id)).calculated == D("626.67")

    paid = await create_and_submit(admin, await _hire_payment_body(admin, created["id"], hire.id, "3000.00"))
    assert paid["status"] == "submitted"
    assert paid["employee_id"] == manager.id and paid["party_name"] == "Jordan Hire"

    line = await _salary_line(manager.id)
    assert line.calculated == D("240.00") and line.gross_revenue == 6000 and line.expenses == 3000

    financials = (await admin.get(f"{API}/projects/{created['id']}/financials")).json()
    assert D(financials["direct_expenses"]) == 3000 and D(financials["salary_paid"]) == 0

    async with SessionLocal() as s:
        ok, detail = await checks.salary_links(s)
    assert ok, detail

    res = await admin.post(
        f"{API}/payment-entries/{paid['id']}/cancel",
        json={"reason": "Wrong amount"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert res.status_code == 200, res.text
    assert (await _salary_line(manager.id)).calculated == D("626.67")
    async with SessionLocal() as s:
        ok, detail = await checks.salary_links(s)
    assert ok, detail


async def test_one_hire_paid_by_two_managers_charges_each_their_own(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    a = await _manager(client_as, "Avery Manager")
    b = await _manager(client_as, "Blake Manager")
    hire = await _hire(admin, client_as)
    await _on_formula(a.id)
    await _on_formula(b.id)
    project_a = await _own_project(a, "A's project", hire=hire)
    project_b = await _own_project(b, "B's project", hire=hire)
    await _receipt(admin, project_a["id"], a.id, "6000.00")
    await _receipt(admin, project_b["id"], b.id, "6000.00")

    paid = await create_and_submit(admin, await _hire_payment_body(admin, project_a["id"], hire.id, "3000.00"))
    assert paid["employee_id"] == a.id
    assert (await _salary_line(a.id)).calculated == D("240.00")
    assert (await _salary_line(b.id)).calculated == D("626.67")


async def test_a_draft_cant_charge_anyone_but_the_projects_manager(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    await _receipt(admin, created["id"], manager.id, "6000.00")
    someone_else = await employee("Someone Else")
    body = await _hire_payment_body(admin, created["id"], hire.id, "100.00", employee_id=someone_else)
    paid = await create_and_submit(admin, body)
    assert paid["employee_id"] == manager.id


async def test_payment_rules(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    other_hire = await _hire(admin, client_as, "Other Hire")
    with_hire = await _own_project(manager, "With hire", hire=hire)
    without_hire = await _own_project(manager, "Without hire")

    assert "project_id" in await _submit_errors(admin, await _hire_payment_body(admin, None, hire.id, "10.00"))
    wrong = await _hire_payment_body(admin, with_hire["id"], other_hire.id, "10.00")
    assert "party_id" in await _submit_errors(admin, wrong)
    assert "party_id" in await _submit_errors(
        admin, await _hire_payment_body(admin, without_hire["id"], hire.id, "10.00")
    )
    assert "party_id" in await _submit_errors(
        admin, await _hire_payment_body(admin, with_hire["id"], manager.id, "10.00")
    )
    missing = await _hire_payment_body(admin, with_hire["id"], hire.id, "10.00", party_id=None)
    assert "party_id" in await _submit_errors(admin, missing)


async def test_a_replaced_hire_cant_be_paid_on_that_project(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    first = await _hire(admin, client_as, "First Hire")
    second = await _hire(admin, client_as, "Second Hire")
    created = await _own_project(manager, hire=first)
    res = await manager.client.patch(
        f"{API}/projects/{created['id']}", json={"version": created["version"], "hire_employee_id": second.id}
    )
    assert res.status_code == 200, res.text
    assert "party_id" in await _submit_errors(admin, await _hire_payment_body(admin, created["id"], first.id, "10.00"))


async def test_past_payments_stay_with_the_original_manager(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    await _receipt(admin, created["id"], manager.id, "6000.00")
    paid = await create_and_submit(admin, await _hire_payment_body(admin, created["id"], hire.id, "100.00"))

    successor = await employee("Successor")
    current = (await admin.get(f"{API}/projects/{created['id']}")).json()
    res = await admin.patch(
        f"{API}/projects/{created['id']}",
        json={
            "version": current["version"],
            "manager_employee_id": successor,
            "members": [{"employee_id": successor, "default_allocation_pct": "100"}],
        },
    )
    assert res.status_code == 200, res.text
    assert (await admin.get(f"{API}/payment-entries/{paid['id']}")).json()["employee_id"] == manager.id


async def test_a_hire_payment_cant_be_split(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    body = await _hire_payment_body(
        admin, created["id"], hire.id, "10.00", allocations=[{"employee_id": manager.id, "percent": "100"}]
    )
    assert "allocations" in await _submit_errors(admin, body)


async def test_the_preview_warns_when_the_fee_is_more_than_the_managers_net_revenue(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    await _receipt(admin, created["id"], manager.id, "1000.00")
    within = await admin.post(
        f"{API}/payment-entries/preview", json=await _hire_payment_body(admin, created["id"], hire.id, "500.00")
    )
    assert within.status_code == 200, within.text
    assert within.json()["ok"] and not any("net revenue" in w for w in within.json()["warnings"])
    over = await admin.post(
        f"{API}/payment-entries/preview", json=await _hire_payment_body(admin, created["id"], hire.id, "1500.00")
    )
    assert over.json()["ok"] and any("net revenue" in w for w in over.json()["warnings"])


# ---- who sees which payments -----------------------------------------------------------------------


async def test_a_hire_sees_only_their_own_completed_payments_without_internal_details(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    receipt = await _receipt(admin, created["id"], manager.id, "6000.00")
    paid = await create_and_submit(
        admin, await _hire_payment_body(admin, created["id"], hire.id, "3000.00", reference_no="REF-1")
    )
    draft = await admin.post(
        f"{API}/payment-entries", json=await _hire_payment_body(admin, created["id"], hire.id, "50.00")
    )
    assert draft.status_code == 201
    cancelled = await create_and_submit(admin, await _hire_payment_body(admin, created["id"], hire.id, "25.00"))
    await admin.post(
        f"{API}/payment-entries/{cancelled['id']}/cancel",
        json={"reason": "Mistake"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )

    for params in ({}, {"status": "draft"}, {"status": "cancelled"}, {"employee_id": manager.id}):
        listed = (await hire.client.get(f"{API}/payment-entries", params=params)).json()["items"]
        assert [p["id"] for p in listed] == [paid["id"]], params

    entry = (await hire.client.get(f"{API}/payment-entries/{paid['id']}")).json()
    assert D(entry["amount"]) == 3000 and entry["project_name"] == "Website" and entry["reference_no"] == "REF-1"
    for field in ("description", "paid_from_payment_account_id", "employee_id", "employee_name", "journal_entry_id"):
        assert entry[field] is None, field

    for other in (receipt["id"], draft.json()["id"], cancelled["id"]):
        assert (await hire.client.get(f"{API}/payment-entries/{other}")).status_code == 404

    totals = (await hire.client.get(f"{API}/payment-entries/totals")).json()
    assert totals["count"] == 1 and D(totals["paid"]) == 3000

    export = await hire.client.get(f"{API}/payment-entries", params={"format": "csv"})
    assert export.status_code == 200, export.text
    assert "Internal note" not in export.text and "Avery Manager" not in export.text and "REF-1" in export.text


async def test_the_manager_sees_the_payment_as_their_expense(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    await _receipt(admin, created["id"], manager.id, "6000.00")
    paid = await create_and_submit(admin, await _hire_payment_body(admin, created["id"], hire.id, "3000.00"))
    listed = (await manager.client.get(f"{API}/payment-entries")).json()["items"]
    assert paid["id"] in [p["id"] for p in listed]


async def test_a_manager_filters_their_payments_by_their_hire(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    a = await _manager(client_as, "Avery Manager")
    b = await _manager(client_as, "Blake Manager")
    alone = await _manager(client_as, "No Hire")
    jordan = await _hire(admin, client_as, "Jordan Hire")
    other = await _hire(admin, client_as, "Other Hire")
    project_a = await _own_project(a, "A's project", hire=jordan)
    project_a2 = await _own_project(a, "A's second project", hire=jordan)
    project_b = await _own_project(b, "B's project", hire=jordan)
    await _receipt(admin, project_a["id"], a.id, "6000.00")
    paid_a = await create_and_submit(admin, await _hire_payment_body(admin, project_a["id"], jordan.id, "3000.00"))
    paid_a2 = await create_and_submit(admin, await _hire_payment_body(admin, project_a2["id"], jordan.id, "200.00"))
    paid_b = await create_and_submit(admin, await _hire_payment_body(admin, project_b["id"], jordan.id, "500.00"))
    jordan_party = await _party_of(admin, jordan.id)
    other_party = await _party_of(admin, other.id)

    # The list holds a manager's own hires only, with nothing beyond a name.
    url = f"{API}/payment-entries/my-hires"
    assert (await a.client.get(url)).json() == [{"party_id": jordan_party, "full_name": "Jordan Hire"}]
    assert (await alone.client.get(url)).json() == []
    assert (await jordan.client.get(url)).status_code == 403

    # Filtering shows just what this manager paid that hire, never another manager's payment to them.
    listed = (await a.client.get(f"{API}/payment-entries", params={"party_id": jordan_party})).json()["items"]
    assert {p["id"] for p in listed} == {paid_a["id"], paid_a2["id"]} and paid_b["id"] not in {p["id"] for p in listed}
    totals = (await a.client.get(f"{API}/payment-entries/totals", params={"party_id": jordan_party})).json()
    assert totals["count"] == 2 and D(totals["paid"]) == 3200 and D(totals["received"]) == 0
    assert (await b.client.get(f"{API}/payment-entries/totals", params={"party_id": jordan_party})).json()["count"] == 1

    # A hire they've never paid gives nothing, even asked for directly.
    assert (await a.client.get(f"{API}/payment-entries", params={"party_id": other_party})).json()["items"] == []
    assert (await alone.client.get(f"{API}/payment-entries", params={"party_id": jordan_party})).json()["items"] == []

    # A hire they replaced stays in the list while they have payments to look back on.
    for mine in (project_a, project_a2):
        current = (await a.client.get(f"{API}/projects/{mine['id']}")).json()
        res = await a.client.patch(
            f"{API}/projects/{mine['id']}", json={"version": current["version"], "hire_employee_id": other.id}
        )
        assert res.status_code == 200, res.text
    names = [h["full_name"] for h in (await a.client.get(url)).json()]
    assert names == ["Jordan Hire", "Other Hire"]


async def test_managers_sharing_a_hire_are_kept_apart(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    a = await _manager(client_as, "Avery Manager")
    b = await _manager(client_as, "Blake Manager")
    hire = await _hire(admin, client_as)
    project_a = await _own_project(a, "A's project", hire=hire)
    project_b = await _own_project(b, "B's project", hire=hire)
    await _receipt(admin, project_b["id"], b.id, "6000.00")
    task = await hire.client.post(f"{API}/tasks", json={"project_id": project_b["id"], "title": "B's task"})
    paid_b = await create_and_submit(admin, await _hire_payment_body(admin, project_b["id"], hire.id, "3000.00"))

    assert (await a.client.get(f"{API}/projects/{project_b['id']}")).status_code == 404
    assert (await a.client.get(f"{API}/tasks/{task.json()['id']}")).status_code == 404
    assert (await a.client.get(f"{API}/payment-entries/{paid_b['id']}")).status_code == 404
    assert [p["id"] for p in (await a.client.get(f"{API}/projects")).json()["items"]] == [project_a["id"]]
    assert paid_b["id"] not in [p["id"] for p in (await a.client.get(f"{API}/payment-entries")).json()["items"]]

    listed = {p["id"] for p in (await hire.client.get(f"{API}/projects")).json()["items"]}
    assert listed == {project_a["id"], project_b["id"]}


async def test_a_hire_cant_reach_salary_revenue_bidding_or_other_projects(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    other = await _own_project(await _manager(client_as, "Other Manager"), "Other project")
    assert (await hire.client.get(f"{API}/projects/{other['id']}")).status_code == 404
    for path in (
        f"/projects/{created['id']}/financials",
        "/me/salary",
        f"/employees/{manager.id}/salary",
        "/reports/my-project-contribution",
        "/reports/project-profitability",
        "/parties",
    ):
        res = await hire.client.get(f"{API}{path}")
        assert res.status_code in (403, 404), (path, res.status_code)
    me = await hire.client.get(f"{API}/auth/me")
    assert me.json()["restricted_access"] is True
    assert "bidding.read" not in me.json()["permissions"]


async def test_a_hire_only_has_their_own_calendar(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    url = f"{API}/calendar/feed"
    assert (await hire.client.get(url, params=RANGE)).status_code == 200
    assert (await hire.client.get(url, params={**RANGE, "view": "company"})).status_code == 403
    assert (
        await hire.client.get(url, params={**RANGE, "view": "team", "project_id": created["id"]})
    ).status_code == 403
    assert (await manager.client.get(url, params={**RANGE, "view": "company"})).status_code == 200


# ---- monitoring ------------------------------------------------------------------------------------


async def test_the_report_counts_work_and_pay_per_hire_and_manager(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    a = await _manager(client_as, "Avery Manager")
    b = await _manager(client_as, "Blake Manager")
    hire = await _hire(admin, client_as)
    project_a = await _own_project(a, "A's project", hire=hire)
    project_b = await _own_project(b, "B's project", hire=hire)
    await _receipt(admin, project_a["id"], a.id, "6000.00")
    await _receipt(admin, project_b["id"], b.id, "6000.00")
    for title, project_id, due in (
        ("One", project_a, "2026-11-01"),
        ("Two", project_a, None),
        ("Three", project_b, None),
    ):
        res = await hire.client.post(
            f"{API}/tasks", json={"project_id": project_id["id"], "title": title, "due_date": due}
        )
        assert res.status_code == 201, res.text
    await create_and_submit(admin, await _hire_payment_body(admin, project_a["id"], hire.id, "3000.00"))
    await create_and_submit(admin, await _hire_payment_body(admin, project_b["id"], hire.id, "500.00"))

    report = (await admin.get(f"{API}/reports/hired-managers", params=RANGE)).json()
    rows = {r["manager_name"]: r for r in report["rows"]}
    assert set(rows) == {"Avery Manager", "Blake Manager"}
    avery = rows["Avery Manager"]
    assert avery["projects"] == 1
    assert avery["tasks_created"] == 2 and avery["tasks_open"] == 2 and avery["tasks_overdue"] == 1
    assert D(avery["paid"]) == 3000
    assert D(avery["manager_gross_revenue"]) == 6000 and D(avery["manager_net_revenue"]) == 3000
    assert avery["last_activity"] is not None and avery["stale"] is False
    assert rows["Blake Manager"]["tasks_created"] == 1 and D(rows["Blake Manager"]["paid"]) == 500

    # A manager sees their own pair, with nothing from anyone else's.
    own = (await a.client.get(f"{API}/reports/hired-managers", params=RANGE)).json()["rows"]
    assert [r["manager_name"] for r in own] == ["Avery Manager"]
    assert D(own[0]["paid"]) == 3000 and own[0]["tasks_created"] == 2

    export = await admin.get(f"{API}/reports/hired-managers", params={**RANGE, "format": "csv"})
    assert export.status_code == 200 and "Blake Manager" in export.text

    # A past hire's pay still shows after they're replaced.
    replacement = await _hire(admin, client_as, "Replacement")
    current = (await b.client.get(f"{API}/projects/{project_b['id']}")).json()
    res = await b.client.patch(
        f"{API}/projects/{project_b['id']}", json={"version": current["version"], "hire_employee_id": replacement.id}
    )
    assert res.status_code == 200, res.text
    after = (await admin.get(f"{API}/reports/hired-managers", params=RANGE)).json()["rows"]
    past = next(r for r in after if r["hire_name"] == "Jordan Hire" and r["manager_name"] == "Blake Manager")
    assert D(past["paid"]) == 500 and past["projects"] == 0


async def test_the_report_lists_a_hire_with_no_work_yet_and_flags_inactivity(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    idle = await _hire(admin, client_as, "Idle Hire")
    report = (await admin.get(f"{API}/reports/hired-managers", params=RANGE)).json()
    row = next(r for r in report["rows"] if r["hire_id"] == idle.id)
    assert row["manager_id"] is None and row["projects"] == 0 and row["stale"] is False

    manager = await _manager(client_as, "Avery Manager")
    await _own_project(manager, hire=idle)
    clock.freeze(date(2026, 11, 30))
    report = (await admin.get(f"{API}/reports/hired-managers", params=RANGE)).json()
    row = next(r for r in report["rows"] if r["hire_id"] == idle.id)
    assert row["manager_id"] == manager.id and row["stale"] is True


async def test_the_monthly_report_shows_a_hires_pay_under_their_manager(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    a = await _manager(client_as, "Avery Manager")
    b = await _manager(client_as, "Blake Manager")
    hire = await _hire(admin, client_as)
    project_a = await _own_project(a, "A's project", hire=hire)
    project_b = await _own_project(b, "B's project", hire=hire)
    await _receipt(admin, project_a["id"], a.id, "6000.00")
    await _receipt(admin, project_b["id"], b.id, "6000.00")
    await create_and_submit(admin, await _hire_payment_body(admin, project_a["id"], hire.id, "3000.00"))
    await create_and_submit(admin, await _hire_payment_body(admin, project_b["id"], hire.id, "500.00"))

    async def november(client: httpx.AsyncClient, **params: str) -> dict:
        res = await client.get(f"{API}/reports/monthly-summary", params={"periods": 0, **params})
        assert res.status_code == 200, res.text
        return next(r for r in res.json()["rows"] if r["start_date"] <= ON.isoformat() <= r["end_date"])

    # Admin picks a manager: only that manager's payments to the hire, and they're part of the expenses.
    row = await november(admin, employee_ids=a.id)
    assert D(row["expenses"]) == 3000 and D(row["hired_manager_pay"]) == 3000
    assert [(p["hire_name"], D(p["amount"])) for p in row["hire_payments"]] == [("Jordan Hire", D(3000))]
    assert D((await november(admin, employee_ids=b.id))["hired_manager_pay"]) == 500

    # Both managers together add up, one line per hire.
    row = await november(admin, employee_ids=f"{a.id},{b.id}")
    assert [(p["hire_name"], D(p["amount"])) for p in row["hire_payments"]] == [("Jordan Hire", D(3500))]

    # A manager sees it on their own report, and nothing from the other manager.
    row = await november(a.client, employee_ids=a.id)
    assert D(row["hired_manager_pay"]) == 3000

    # The whole-company view doesn't break hires out: their pay is in company expenses.
    row = await november(admin)
    assert D(row["hired_manager_pay"]) == 0 and row["hire_payments"] == [] and D(row["expenses"]) == 3500

    # A hire can't open it.
    assert (
        await hire.client.get(f"{API}/reports/monthly-summary", params={"employee_ids": hire.id})
    ).status_code == 403


async def test_report_access(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    hire = await _hire(admin, client_as)
    assert (await hire.client.get(f"{API}/reports/hired-managers", params=RANGE)).status_code == 403
    pm = await client_as("project_manager")
    assert (await pm.get(f"{API}/reports/hired-managers", params=RANGE)).status_code == 403
    for role in ("supervisor", "finance_manager"):
        client = await client_as(role)
        assert (await client.get(f"{API}/reports/hired-managers", params=RANGE)).status_code == 200
