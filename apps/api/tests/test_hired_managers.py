"""Hired managers (docs/hired-managers-plan.md): people an employee hires to help run a project."""

import uuid
from datetime import date

import httpx
import pytest

from app.core.db import SessionLocal
from app.modules.compensation import api as compensation
from app.modules.employees import api as employees
from app.modules.projects import service as project_service
from app.modules.rbac.defaults import DEFAULT_ROLES, RESTRICTED_GRANTS
from app.modules.rbac.permissions import PERMISSIONS
from app.modules.salary import service as salary_service
from tests.conftest import ClientFactory
from tests.factories import category_id, customer, employee, payment_account_id, project, receipt_body

API = "/api/v1"
START = "2026-01-01"


async def _hire_body(name: str, **extra: object) -> dict:
    return {
        "full_name": name,
        "employment_type_category_id": await category_id("employment_type", "contractor"),
        "start_date": START,
        "is_hired_manager": True,
        **extra,
    }


async def _create_hire(admin: httpx.AsyncClient, name: str = "Jordan Hire", **extra: object) -> dict:
    res = await admin.post(f"{API}/employees", json=await _hire_body(name, **extra))
    assert res.status_code == 201, res.text
    return res.json()


async def _set_flag(admin: httpx.AsyncClient, employee_id: str, value: bool) -> httpx.Response:
    current = (await admin.get(f"{API}/employees/{employee_id}")).json()
    return await admin.patch(
        f"{API}/employees/{employee_id}", json={"version": current["version"], "is_hired_manager": value}
    )


# ---- records and roles -----------------------------------------------------------------------------


async def test_a_hire_is_marked_and_can_be_filtered(admin: httpx.AsyncClient) -> None:
    hire = await _create_hire(admin)
    regular = await employee("Regular Person")
    assert hire["is_hired_manager"] is True
    assert (await admin.get(f"{API}/employees/{regular}")).json()["is_hired_manager"] is False

    hired = (await admin.get(f"{API}/employees", params={"hired": True})).json()["items"]
    others = (await admin.get(f"{API}/employees", params={"hired": False})).json()["items"]
    assert [e["id"] for e in hired] == [hire["id"]]
    assert regular in [e["id"] for e in others] and hire["id"] not in [e["id"] for e in others]


def test_default_role_grants_are_registered_with_allowed_scopes() -> None:
    supervisor = next(r for r in DEFAULT_ROLES if r["key"] == "supervisor")
    for grants in (supervisor["grants"], RESTRICTED_GRANTS):
        for permission, scope in grants.items():
            assert scope in PERMISSIONS[permission].scopes, permission


def test_a_hires_access_stays_narrow_and_the_role_grants_nothing() -> None:
    assert next(r for r in DEFAULT_ROLES if r["key"] == "hired_manager")["grants"] == {}
    assert set(RESTRICTED_GRANTS) == {
        "projects.read",
        "tasks.manage",
        "tasks.update_own",
        "payments.read_own",
    }


async def test_hire_options_give_names_only_and_skip_former_hires(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    hire = await _create_hire(admin, email="jordan@example.com", phone="555", notes="private")
    former = await _create_hire(admin, "Former Hire", status="terminated")
    await employee("Regular Person")

    staff_view = await client_as("employee")
    await employee("Full Timer", user_id=staff_view.user_id)  # type: ignore[attr-defined]
    res = await staff_view.get(f"{API}/hires/options")
    assert res.status_code == 200, res.text
    assert res.json() == [{"id": hire["id"], "full_name": "Jordan Hire"}]
    assert former["id"] not in [h["id"] for h in res.json()]


async def test_people_without_project_rights_cant_list_hires(client_as: ClientFactory) -> None:
    finance = await client_as("finance_manager")
    assert (await finance.get(f"{API}/hires/options")).status_code == 403


async def test_a_hire_cant_list_other_hires(admin: httpx.AsyncClient, client_as: ClientFactory) -> None:
    client = await client_as("hired_manager")
    await _create_hire(admin, user_id=client.user_id)  # type: ignore[attr-defined]
    assert (await client.get(f"{API}/hires/options")).status_code == 403


# ---- changing the flag -----------------------------------------------------------------------------


async def test_a_new_employee_can_become_a_hire_and_change_back(admin: httpx.AsyncClient) -> None:
    person = await employee("Fresh Person")
    res = await _set_flag(admin, person, True)
    assert res.status_code == 200 and res.json()["is_hired_manager"] is True
    res = await _set_flag(admin, person, False)
    assert res.status_code == 200 and res.json()["is_hired_manager"] is False


async def test_a_null_flag_on_update_leaves_a_regular_employee_regular(admin: httpx.AsyncClient) -> None:
    person = await employee("Fresh Person")
    current = (await admin.get(f"{API}/employees/{person}")).json()
    res = await admin.patch(f"{API}/employees/{person}", json={"version": current["version"], "is_hired_manager": None})
    assert res.status_code == 200 and res.json()["is_hired_manager"] is False


async def test_someone_with_a_formula_cant_become_a_hire(admin: httpx.AsyncClient) -> None:
    person = await employee("Salaried Person")
    async with SessionLocal() as s:
        formula = await compensation.default_formula(s)
        await compensation.create_assignment(
            s,
            actor_id=None,
            employee_id=uuid.UUID(person),
            formula_id=formula.id,
            effective_from=date(2026, 1, 1),
        )
        await s.commit()
    res = await _set_flag(admin, person, True)
    assert res.status_code == 422
    assert res.json()["errors"][0]["field"] == "is_hired_manager"
    assert "a salary formula" in res.json()["errors"][0]["message"]


async def test_someone_on_a_project_cant_change_type(admin: httpx.AsyncClient) -> None:
    person = await employee("Team Person")
    await project("Website", await customer(), [(person, None)])
    res = await _set_flag(admin, person, True)
    assert res.status_code == 422 and "projects" in res.json()["errors"][0]["message"]


async def test_a_hire_on_a_project_cant_change_back(admin: httpx.AsyncClient) -> None:
    hire = await _create_hire(admin)
    manager = await employee("Manager Person")
    project_id = await project("Website", await customer(), [(manager, None)], manager_id=manager)
    async with SessionLocal() as s:
        row = await project_service.get(s, uuid.UUID(project_id))
        row.hire_employee_id = uuid.UUID(hire["id"])
        await s.commit()
    res = await _set_flag(admin, hire["id"], False)
    assert res.status_code == 422 and "projects" in res.json()["errors"][0]["message"]


async def test_someone_with_payments_cant_change_type(admin: httpx.AsyncClient) -> None:
    person = await employee("Credited Person")
    body = await receipt_body(
        party_id=await customer(), amount="100", allocations=[{"employee_id": person, "percent": "100"}]
    )
    assert (await admin.post(f"{API}/payment-entries", json=body)).status_code == 201
    res = await _set_flag(admin, person, True)
    assert res.status_code == 422 and "splits" in res.json()["errors"][0]["message"]


# ---- keeping hires out of payroll ------------------------------------------------------------------


async def test_a_hire_cant_be_in_a_revenue_split(admin: httpx.AsyncClient) -> None:
    hire = await _create_hire(admin)
    body = await receipt_body(
        party_id=await customer(), amount="100", allocations=[{"employee_id": hire["id"], "percent": "100"}]
    )
    res = await admin.post(f"{API}/payment-entries", json=body)
    assert res.status_code == 422
    assert res.json()["errors"][0]["field"] == "allocations.0.employee_id"


async def test_a_hire_cant_get_a_formula(admin: httpx.AsyncClient) -> None:
    hire = await _create_hire(admin)
    async with SessionLocal() as s:
        formula = await compensation.default_formula(s)
    res = await admin.post(
        f"{API}/comp-assignments",
        json={"employee_id": hire["id"], "formula_id": str(formula.id), "effective_from": "2026-11-01"},
    )
    assert res.status_code == 422, res.text
    assert res.json()["errors"][0]["field"] == "employee_id"


async def test_a_hire_cant_get_a_salary_adjustment(admin: httpx.AsyncClient) -> None:
    hire = await _create_hire(admin)
    async with SessionLocal() as s:
        await salary_service.ensure_covering(s, date(2026, 11, 1))
        period = await salary_service.period_for(s, date(2026, 11, 1))
        await s.commit()
        period_id = period.id
    res = await admin.post(
        f"{API}/salary-periods/{period_id}/adjustments",
        json={"employee_id": hire["id"], "kind": "bonus", "amount": "50", "reason": "Nope"},
    )
    assert res.status_code == 422, res.text
    assert res.json()["errors"][0]["field"] == "employee_id"


async def test_a_hire_cant_be_paid_a_salary_or_tagged_on_an_expense(admin: httpx.AsyncClient) -> None:
    hire = await _create_hire(admin)
    base = {
        "direction": "pay",
        "posting_date": "2026-11-01",
        "amount": "100",
        "method_category_id": await category_id("payment_method", "bank_transfer"),
        "paid_from_payment_account_id": await payment_account_id("Company Checking"),
    }

    salary = await admin.post(
        f"{API}/payment-entries",
        json={
            **base,
            "purpose_category_id": await category_id("payment_purpose", "employee_salary"),
            "party_id": hire["party_id"],
        },
    )
    assert salary.status_code == 201, salary.text
    res = await admin.post(
        f"{API}/payment-entries/{salary.json()['id']}/submit", headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    assert res.status_code == 422 and "party_id" in [e["field"] for e in res.json()["errors"]]

    expense = await admin.post(
        f"{API}/payment-entries",
        json={
            **base,
            "purpose_category_id": await category_id("payment_purpose", "operating_expense"),
            "category_id": await category_id("expense_category", "cloud_infrastructure"),
            "employee_id": hire["id"],
        },
    )
    assert expense.status_code == 201, expense.text
    res = await admin.post(
        f"{API}/payment-entries/{expense.json()['id']}/submit", headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    assert res.status_code == 422 and "employee_id" in [e["field"] for e in res.json()["errors"]]


async def test_a_hire_cant_manage_a_project_or_join_its_team(admin: httpx.AsyncClient) -> None:
    hire = await _create_hire(admin)
    res = await admin.post(
        f"{API}/projects",
        json={
            "name": "Website",
            "project_type_category_id": await category_id("project_type", "web_development"),
            "manager_employee_id": hire["id"],
        },
    )
    assert res.status_code == 422 and res.json()["errors"][0]["field"] == "manager_employee_id"

    project_id = await project("Website", await customer(), [])
    res = await admin.put(f"{API}/projects/{project_id}/members", json={"members": [{"employee_id": hire["id"]}]})
    assert res.status_code == 422 and res.json()["errors"][0]["field"] == "members.0.employee_id"


# ---- what a hire sees about colleagues -------------------------------------------------------------


async def test_a_hire_cant_read_the_employee_list_or_records(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    client = await client_as("hired_manager")
    me = await _create_hire(admin, email="me@example.com", user_id=client.user_id)  # type: ignore[attr-defined]
    colleague = await employee("Colleague")
    assert (await client.get(f"{API}/employees")).status_code == 403
    assert (await client.get(f"{API}/employees/{colleague}")).status_code == 403
    assert (await client.get(f"{API}/employees/{me['id']}")).status_code == 403
    assert (await client.get(f"{API}/employees/me")).json()["email"] == "me@example.com"


async def test_a_regular_project_manager_still_sees_team_details(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    client = await client_as("project_manager")
    me = await employee("Regular PM", user_id=client.user_id)  # type: ignore[attr-defined]
    colleague = await employee("Colleague", email="colleague@example.com")
    await project("Website", await customer(), [(colleague, None)], manager_id=me)
    listed = {e["id"]: e for e in (await client.get(f"{API}/employees")).json()["items"]}
    assert listed[colleague]["email"] == "colleague@example.com"


@pytest.mark.parametrize("key", ["payments.read_own", "hired_managers.read", "projects.create_own"])
def test_new_permissions_are_registered(key: str) -> None:
    assert key in PERMISSIONS


async def test_the_employee_lookup_reports_hires_only(admin: httpx.AsyncClient) -> None:
    regular = uuid.UUID(await employee("Regular Person"))
    hire = uuid.UUID((await _create_hire(admin))["id"])
    async with SessionLocal() as s:
        assert await employees.hire_ids(s, [regular, hire]) == {hire}
        assert await employees.hire_ids(s, []) == set()
