"""The guard on hired managers: refused everything that isn't deliberately open to them."""

import re
import uuid

import httpx
import pytest

from app.main import app
from app.modules.auth.deps import restricted_may_call
from tests.conftest import ClientFactory
from tests.factories import category_id
from tests.test_hired_managers_flow import (
    API,
    Person,
    _hire,
    _hire_for,
    _hire_payment_body,
    _manager,
    _own_project,
    _receipt,
    create_and_submit,
)

# Public, or used to get signed in: never reach the guard.
NO_SESSION = {"/api/health", "/api/health/ready", "/api/v1/auth/login"}
# Would end the session the test depends on, or change its password.
LEAVE_ALONE = {"/api/v1/auth/logout", "/api/v1/auth/logout-all", "/api/v1/auth/change-password"}


def _routes() -> list[tuple[str, str]]:
    found = []
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            if method in ("get", "post", "put", "patch", "delete"):
                found.append((method.upper(), path))
    return found


def _concrete(path: str) -> str:
    return re.sub(r"{\w+(:\w+)?}", str(uuid.uuid4()), path)


async def test_everything_not_listed_is_refused(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    hire = await _hire(admin, client_as)
    checked = 0
    for method, path in _routes():
        if path in NO_SESSION or path in LEAVE_ALONE:
            continue
        url = _concrete(path)
        if restricted_may_call(method, url):
            continue
        res = await hire.client.request(method, url, json={}, headers={"Idempotency-Key": str(uuid.uuid4())})
        assert res.status_code == 403, f"{method} {path} answered {res.status_code}"
        checked += 1
    assert checked > 100
    assert (await hire.client.get(f"{API}/auth/me")).status_code == 200


def test_the_open_list_stays_short_and_has_no_money_or_people_routes() -> None:
    open_routes = [(m, p) for m, p in _routes() if p not in NO_SESSION and restricted_may_call(m, _concrete(p))]
    paths = {p for _, p in open_routes}
    for word in (
        "salary",
        "revenue",
        "reports",
        "bidding",
        "users",
        "roles",
        "backups",
        "accounts",
        "parties",
        "journal",
    ):
        assert not [p for p in paths if word in p], word
    assert not [p for p in paths if "/employees" in p and p != "/api/v1/employees/me"]
    assert not [(m, p) for m, p in open_routes if "payment-entries" in p and m != "GET"]
    # Tasks are the only work they can change.
    assert not [(m, p) for m, p in open_routes if ("/projects" in p or "/milestones" in p) and m != "GET"]


async def test_a_regular_employee_is_not_affected(client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    assert (await manager.client.get(f"{API}/salary-periods")).status_code == 200
    assert (await manager.client.get(f"{API}/departments")).status_code == 200


@pytest.mark.parametrize("role", ["employee", "project_manager", "finance_manager", "supervisor"])
async def test_the_guard_holds_whatever_role_the_sign_in_has(
    admin: httpx.AsyncClient, client_as: ClientFactory, role: str
) -> None:
    client = await client_as(role)
    await _hire_for(admin, client, "Jordan Hire")
    for path in (
        "/salary-periods",
        "/departments",
        "/exchange-rates",
        "/users",
        "/reports/hired-managers?from=2026-01-01&to=2026-12-31",
    ):
        assert (await client.get(f"{API}{path}")).status_code == 403, path


async def test_a_hire_who_has_left_loses_everything(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    url = f"{API}/projects/{created['id']}"
    assert (await hire.client.get(url)).status_code == 200

    current = (await admin.get(f"{API}/employees/{hire.id}")).json()
    res = await admin.patch(f"{API}/employees/{hire.id}", json={"version": current["version"], "status": "terminated"})
    assert res.status_code == 200, res.text

    assert (await hire.client.get(url)).status_code == 403
    assert (await hire.client.get(f"{API}/projects")).status_code == 403
    assert (await hire.client.get(f"{API}/payment-entries")).status_code == 403
    assert (await hire.client.post(f"{API}/tasks", json={"project_id": created["id"], "title": "x"})).status_code == 403
    assert (await hire.client.get(f"{API}/auth/me")).json()["permissions"] == {}


async def test_a_hire_cant_touch_a_project_they_arent_connected_to(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    """With valid requests, so the answer comes from the guard and not from a malformed body."""
    mine_owner = await _manager(client_as, "Avery Manager")
    other = await _manager(client_as, "Other Manager")
    hire = await _hire(admin, client_as)
    await _own_project(mine_owner, "Connected", hire=hire)
    project = await _own_project(other, "Not connected")
    task = (await other.client.post(f"{API}/tasks", json={"project_id": project["id"], "title": "Theirs"})).json()
    second = (await other.client.post(f"{API}/tasks", json={"project_id": project["id"], "title": "Also"})).json()
    milestone = (await other.client.post(f"{API}/projects/{project['id']}/milestones", json={"name": "M"})).json()
    c = hire.client
    attempts = [
        c.get(f"{API}/projects/{project['id']}"),
        c.get(f"{API}/projects/{project['id']}/milestones"),
        c.get(f"{API}/projects/{project['id']}/timeline"),
        c.patch(f"{API}/projects/{project['id']}", json={"version": project["version"], "name": "Hacked"}),
        c.put(f"{API}/projects/{project['id']}/members", json={"members": []}),
        c.post(f"{API}/projects/{project['id']}/milestones", json={"name": "Nope"}),
        c.patch(f"{API}/milestones/{milestone['id']}", json={"version": milestone["version"], "name": "Hacked"}),
        c.delete(f"{API}/milestones/{milestone['id']}"),
        c.post(f"{API}/tasks", json={"project_id": project["id"], "title": "Nope"}),
        c.get(f"{API}/tasks/{task['id']}"),
        c.patch(f"{API}/tasks/{task['id']}", json={"version": task["version"], "title": "Hacked"}),
        c.delete(f"{API}/tasks/{task['id']}"),
        c.post(f"{API}/tasks/{task['id']}/move", json={"version": task["version"], "status": "done"}),
        c.post(f"{API}/tasks/{task['id']}/dependencies", json={"depends_on_task_id": second["id"]}),
        c.get(f"{API}/tasks/{task['id']}/comments"),
        c.post(f"{API}/tasks/{task['id']}/comments", json={"body": "Nope"}),
        c.get(f"{API}/tasks/{task['id']}/time-entries"),
        c.post(f"{API}/tasks/{task['id']}/time-entries", json={"work_date": "2026-11-05", "hours": "1"}),
        c.get(f"{API}/attachments", params={"entity_type": "task", "entity_id": task["id"]}),
    ]
    for attempt in attempts:
        res = await attempt
        assert res.status_code in (403, 404), (
            f"{res.request.method} {res.request.url}: {res.status_code} {res.text[:100]}"
        )
    # Nothing changed.
    assert (await other.client.get(f"{API}/tasks/{task['id']}")).json()["title"] == "Theirs"
    assert (await other.client.get(f"{API}/projects/{project['id']}")).json()["name"] == "Not connected"
    assert (await admin.get(f"{API}/payment-entries", params={"project_id": project["id"]})).status_code == 200


async def test_a_hires_files_stop_at_tasks(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    task = (await hire.client.post(f"{API}/tasks", json={"project_id": created["id"], "title": "Mine"})).json()
    url = f"{API}/attachments"
    # Project files can hold contracts and prices.
    res = await hire.client.get(url, params={"entity_type": "project", "entity_id": created["id"]})
    assert res.status_code == 404
    files = {"file": ("note.txt", b"hello", "text/plain")}
    res = await hire.client.post(url, data={"entity_type": "project", "entity_id": created["id"]}, files=files)
    assert res.status_code == 403
    # Files on their own project's tasks work.
    res = await hire.client.post(url, data={"entity_type": "task", "entity_id": task["id"]}, files=files)
    assert res.status_code == 201, res.text
    res = await hire.client.get(url, params={"entity_type": "task", "entity_id": task["id"]})
    assert res.status_code == 200 and len(res.json()) == 1
    # No other kind of record.
    for entity_type, entity_id in (
        ("employee", manager.id),
        ("company_settings", str(uuid.uuid4())),
        ("payment_entry", str(uuid.uuid4())),
        ("party", str(uuid.uuid4())),
    ):
        res = await hire.client.get(url, params={"entity_type": entity_type, "entity_id": entity_id})
        assert res.status_code in (403, 404), entity_type


async def test_what_is_left_open_is_cut_down(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    hire = await _hire(admin, client_as)
    current = (await admin.get(f"{API}/settings/company")).json()
    res = await admin.patch(
        f"{API}/settings/company",
        json={"version": current["version"], "email": "billing@example.com", "legal_name": "Legal"},
    )
    assert res.status_code == 200, res.text

    company = (await hire.client.get(f"{API}/settings/company")).json()
    assert company["name"] and company["base_currency"]
    assert company["email"] is None and company["legal_name"] is None and company["policies"] == {}
    assert (await admin.get(f"{API}/settings/company")).json()["email"] == "billing@example.com"

    assert (await hire.client.get(f"{API}/categories", params={"group": "expense_category"})).json() == []
    assert (await hire.client.get(f"{API}/categories", params={"group": "income_category"})).json() == []
    types = (await hire.client.get(f"{API}/categories", params={"group": "project_type"})).json()
    assert types and all(c["config"] == {} for c in types)
    groups = {g["key"] for g in (await hire.client.get(f"{API}/categories/groups")).json()}
    assert "expense_category" not in groups and "project_type" in groups


async def test_a_hire_cant_search_their_way_to_hidden_notes(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    await _receipt(admin, created["id"], manager.id, "1000.00")
    await create_and_submit(
        admin, await _hire_payment_body(admin, created["id"], hire.id, "10.00", reference_no="REF-9")
    )
    url = f"{API}/payment-entries"
    assert (await hire.client.get(url, params={"q": "Internal note"})).json()["items"] == []
    assert (await hire.client.get(f"{url}/totals", params={"q": "Internal note"})).json()["count"] == 0
    assert len((await hire.client.get(url, params={"q": "REF-9"})).json()["items"]) == 1
    # Staff still search it.
    assert (await admin.get(url, params={"q": "Internal note"})).json()["items"]


async def test_categories_cant_be_changed_by_a_hire(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    hire: Person = await _hire(admin, client_as)
    res = await hire.client.post(f"{API}/categories", json={"group_key": "project_type", "name": "Nope"})
    assert res.status_code == 403
    cid = await category_id("project_type", "web_development")
    assert (await hire.client.patch(f"{API}/categories/{cid}", json={"version": 1, "name": "Nope"})).status_code == 403


async def _person(admin: httpx.AsyncClient, client: httpx.AsyncClient, name: str, employment: str) -> Person:
    res = await admin.post(
        f"{API}/employees",
        json={
            "full_name": name,
            "employment_type_category_id": await category_id("employment_type", employment),
            "start_date": "2026-01-01",
            "user_id": client.user_id,  # type: ignore[attr-defined]
        },
    )
    assert res.status_code == 201, res.text
    return Person(res.json()["id"], client)


@pytest.mark.parametrize("employment", ["contractor", "freelancer"])
@pytest.mark.parametrize("role", ["employee", "project_manager"])
async def test_contractors_and_freelancers_are_restricted_without_the_tick(
    admin: httpx.AsyncClient, client_as: ClientFactory, employment: str, role: str
) -> None:
    client = await client_as(role)
    person = await _person(admin, client, "Outside Person", employment)
    me = (await client.get(f"{API}/auth/me")).json()
    assert me["restricted_access"] is True and me["can_select_hire"] is False
    assert set(me["permissions"]) == {"projects.read", "tasks.manage", "tasks.update_own", "payments.read_own"}
    for path in ("/me/salary", f"/employees/{person.id}/salary", "/employees", "/bidding/stats", "/hires/options"):
        assert (await client.get(f"{API}{path}")).status_code == 403, path

    # Connected as a team member: they see the project and manage its tasks, and that's all.
    manager = await _manager(client_as, "Avery Manager")
    created = await _own_project(manager, "Shared")
    other = await _own_project(manager, "Not connected")
    res = await admin.patch(
        f"{API}/projects/{created['id']}",
        json={
            "version": created["version"],
            "members": [
                {"employee_id": manager.id, "default_allocation_pct": "100"},
                {"employee_id": person.id},
            ],
        },
    )
    assert res.status_code == 200, res.text
    seen = (await client.get(f"{API}/projects")).json()["items"]
    assert [p["id"] for p in seen] == [created["id"]] and seen[0]["edit_mode"] is None
    assert seen[0]["contract_value"] is None and seen[0]["members"][0]["default_allocation_pct"] is None
    assert (await client.get(f"{API}/projects/{other['id']}")).status_code == 404
    task = await client.post(f"{API}/tasks", json={"project_id": created["id"], "title": "Works"})
    assert task.status_code == 201 and task.json()["can_edit"] is True
    res = await client.patch(f"{API}/projects/{created['id']}", json={"version": seen[0]["version"], "name": "Nope"})
    assert res.status_code == 403
    assert (await client.post(f"{API}/projects", json={"name": "Nope"})).status_code == 403
    assert (await client.post(f"{API}/projects/{created['id']}/milestones", json={"name": "Nope"})).status_code == 403


async def test_a_restricted_person_on_a_formula_is_still_calculated_for_staff(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    from datetime import date

    from app.core.db import SessionLocal
    from app.modules.compensation import api as compensation

    client = await client_as("employee")
    person = await _person(admin, client, "Paid Contractor", "contractor")
    async with SessionLocal() as s:
        formula = await compensation.default_formula(s)
        await compensation.create_assignment(
            s,
            actor_id=None,
            employee_id=uuid.UUID(person.id),
            formula_id=formula.id,
            effective_from=date(2026, 1, 1),
        )
        await s.commit()
    assert (await admin.get(f"{API}/employees/{person.id}/salary")).status_code == 200
    assert (await client.get(f"{API}/employees/{person.id}/salary")).status_code == 403


async def test_changing_employment_type_changes_access_at_once(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    client = await client_as("employee")
    person = await _person(admin, client, "Changing Person", "full_time")
    assert (await client.get(f"{API}/me/salary")).status_code == 200
    current = (await admin.get(f"{API}/employees/{person.id}")).json()
    contractor = await category_id("employment_type", "contractor")
    res = await admin.patch(
        f"{API}/employees/{person.id}", json={"version": current["version"], "employment_type_category_id": contractor}
    )
    assert res.status_code == 200, res.text
    assert (await client.get(f"{API}/me/salary")).status_code == 403


async def test_an_administrator_cant_be_a_contractor(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    other_admin = await client_as("admin")
    res = await admin.post(
        f"{API}/employees",
        json={
            "full_name": "Admin Person",
            "employment_type_category_id": await category_id("employment_type", "freelancer"),
            "start_date": "2026-01-01",
            "user_id": other_admin.user_id,  # type: ignore[attr-defined]
        },
    )
    assert res.status_code == 422 and res.json()["errors"][0]["field"] == "employment_type_category_id"


@pytest.mark.parametrize("employment", ["part_time", "other"])
async def test_only_full_time_employees_can_select_a_hire(
    admin: httpx.AsyncClient, client_as: ClientFactory, employment: str
) -> None:
    hire = await _hire(admin, client_as)
    client = await client_as("employee")
    body = {
        "full_name": "Part Person",
        "employment_type_category_id": await category_id("employment_type", employment),
        "start_date": "2026-01-01",
        "user_id": client.user_id,  # type: ignore[attr-defined]
    }
    if employment == "other":
        body["employment_type_other_text"] = "Intern"
    res = await admin.post(f"{API}/employees", json=body)
    assert res.status_code == 201, res.text
    person = Person(res.json()["id"], client)

    me = (await client.get(f"{API}/auth/me")).json()
    assert me["restricted_access"] is False and me["can_select_hire"] is False
    assert (await client.get(f"{API}/hires/options")).status_code == 403
    assert (await client.get(f"{API}/me/salary")).status_code == 200

    ptype = await category_id("project_type", "web_development")
    res = await client.post(
        f"{API}/projects", json={"name": "With hire", "project_type_category_id": ptype, "hire_employee_id": hire.id}
    )
    assert res.status_code == 422 and res.json()["errors"][0]["field"] == "hire_employee_id"

    # They can still run a project of their own, just not select a hire on it.
    res = await client.post(f"{API}/projects", json={"name": "Solo", "project_type_category_id": ptype})
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["manager_employee_id"] == person.id
    res = await client.patch(
        f"{API}/projects/{created['id']}", json={"version": created["version"], "hire_employee_id": hire.id}
    )
    assert res.status_code == 422 and res.json()["errors"][0]["field"] == "hire_employee_id"
    res = await client.patch(f"{API}/projects/{created['id']}", json={"version": created["version"], "name": "Renamed"})
    assert res.status_code == 200, res.text

    # Staff can still set one for them; they can then edit the rest of the project or remove the hire.
    current = res.json()
    res = await admin.patch(
        f"{API}/projects/{created['id']}", json={"version": current["version"], "hire_employee_id": hire.id}
    )
    assert res.status_code == 200, res.text
    current = res.json()
    res = await client.patch(
        f"{API}/projects/{created['id']}",
        json={"version": current["version"], "name": "Again", "hire_employee_id": hire.id},
    )
    assert res.status_code == 200, res.text
    res = await client.patch(
        f"{API}/projects/{created['id']}", json={"version": res.json()["version"], "hire_employee_id": None}
    )
    assert res.status_code == 200, res.text


async def test_a_full_time_employee_can_select_a_hire(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    me = (await manager.client.get(f"{API}/auth/me")).json()
    assert me["can_select_hire"] is True
    assert [h["id"] for h in (await manager.client.get(f"{API}/hires/options")).json()] == [hire.id]
    assert (await _own_project(manager, hire=hire))["hire_employee_id"] == hire.id
