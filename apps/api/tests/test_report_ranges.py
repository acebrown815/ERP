"""The employee reports follow the dates asked for, and projects without recent income show as lapsed."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.core import clock
from tests.conftest import ClientFactory
from tests.factories import customer, employee, project, receipt_body
from tests.test_hired_managers_flow import _hire, _manager, _own_project
from tests.test_payments import PE, create_and_submit, idem

API = "/api/v1"
REPORTS = ("employee-revenue", "employee-salary", "employee-performance")


@pytest.fixture(autouse=True)
def today() -> Iterator[None]:
    clock.freeze(date(2026, 11, 10))
    yield
    clock.freeze(None)


async def _project(name: str = "Website") -> tuple[str, str, str]:
    client = await customer(f"{name} Customer")
    person = await employee(f"{name} Manager")
    return await project(name, client, [(person, Decimal(100))]), client, person


async def _receipt(c: httpx.AsyncClient, project_id: str, party_id: str, person: str, on: str) -> dict:
    allocations = [{"employee_id": person, "percent": "100"}]
    body = await receipt_body(party_id=party_id, project_id=project_id, posting_date=on, allocations=allocations)
    return await create_and_submit(c, body)


async def _labels(c: httpx.AsyncClient, report: str, **params: str) -> list[str]:
    res = await c.get(f"{API}/reports/{report}", params=params)
    assert res.status_code == 200, res.text
    return [p["label"] for p in res.json()["periods"]]


async def test_employee_reports_show_the_periods_the_dates_touch(admin: httpx.AsyncClient) -> None:
    res = await admin.put(f"{API}/settings/salary-cycle", json={"salary_cycle_start_day": 25})
    assert res.status_code == 200, res.text
    pid, party, person = await _project()
    await _receipt(admin, pid, party, person, "2026-08-10")
    await _receipt(admin, pid, party, person, "2026-11-05")

    for report in REPORTS:
        # Inside one period (Jul 25 - Aug 24), across two, and either end left open.
        assert await _labels(admin, report, **{"from": "2026-08-01", "to": "2026-08-20"}) == ["Aug 2026"]
        assert await _labels(admin, report, **{"from": "2026-08-20", "to": "2026-09-01"}) == ["Aug 2026", "Sep 2026"]
        assert await _labels(admin, report, **{"from": "2026-10-01"}) == ["Oct 2026", "Nov 2026"]
        assert (await _labels(admin, report, **{"to": "2026-08-20"}))[-1] == "Aug 2026"
        # All time stops at the current period, however far "to" goes.
        everything = await _labels(admin, report, **{"from": "2000-01-01", "to": "2030-12-31"})
        assert everything[-1] == "Nov 2026" and "Aug 2026" in everything
        # Nothing in range is an empty report, not an error.
        assert await _labels(admin, report, **{"from": "2030-01-01", "to": "2030-12-31"}) == []
        assert await _labels(admin, report, **{"from": "2026-11-01", "to": "2026-08-01"}) == []

    async def revenue(**params: str) -> str:
        return (await admin.get(f"{API}/reports/employee-revenue", params=params)).json()["total"]

    assert Decimal(await revenue(**{"from": "2026-08-01", "to": "2026-08-20"})) == 10000
    assert Decimal(await revenue(**{"from": "2026-09-01", "to": "2026-10-01"})) == 0
    assert Decimal(await revenue(**{"from": "2026-08-01", "to": "2026-11-10"})) == 20000


async def test_employee_reports_default_to_six_periods_and_export_the_range(admin: httpx.AsyncClient) -> None:
    pid, party, person = await _project()
    await _receipt(admin, pid, party, person, "2026-03-10")
    for report in REPORTS:
        assert len(await _labels(admin, report)) == 6

    res = await admin.get(
        f"{API}/reports/employee-revenue", params={"format": "csv", "from": "2026-03-01", "to": "2026-03-31"}
    )
    assert res.status_code == 200 and "10000" in res.text
    res = await admin.get(
        f"{API}/reports/employee-revenue", params={"format": "csv", "from": "2026-05-01", "to": "2026-05-31"}
    )
    assert res.status_code == 200 and "10000" not in res.text


async def _lapsed(c: httpx.AsyncClient, project_id: str) -> bool:
    res = await c.get(f"{API}/projects/{project_id}")
    assert res.status_code == 200, res.text
    return res.json()["lapsed"]


async def test_a_project_lapses_three_months_after_its_last_income(admin: httpx.AsyncClient) -> None:
    pid, party, person = await _project()
    assert await _lapsed(admin, pid) is False  # new: it has time to earn its first

    await _receipt(admin, pid, party, person, "2026-07-01")
    assert await _lapsed(admin, pid) is True
    listed = (await admin.get(f"{API}/projects")).json()["items"]
    assert [p["lapsed"] for p in listed if p["id"] == pid] == [True]
    report = (await admin.get(f"{API}/reports/project-profitability")).json()
    assert [r["lapsed"] for r in report if r["project_id"] == pid] == [True]

    # Exactly three months ago still counts; a receipt that was cancelled doesn't.
    recent = await _receipt(admin, pid, party, person, "2026-08-10")
    assert await _lapsed(admin, pid) is False
    res = await admin.post(f"{PE}/{recent['id']}/cancel", json={"reason": "wrong client"}, headers=idem())
    assert res.status_code == 200, res.text
    assert await _lapsed(admin, pid) is True

    # Only active projects lapse, and their real status isn't touched.
    version = (await admin.get(f"{API}/projects/{pid}")).json()["version"]
    res = await admin.patch(f"{API}/projects/{pid}", json={"version": version, "status": "on_hold"})
    assert res.status_code == 200 and res.json()["status"] == "on_hold" and res.json()["lapsed"] is False


async def test_a_project_without_income_lapses_from_its_start_and_a_hire_never_sees_it(
    admin: httpx.AsyncClient, client_as: ClientFactory
) -> None:
    manager = await _manager(client_as, "Avery Manager")
    hire = await _hire(admin, client_as)
    created = await _own_project(manager, hire=hire)
    pid = created["id"]
    assert await _lapsed(manager.client, pid) is False

    clock.freeze(date(2027, 12, 1))
    assert await _lapsed(manager.client, pid) is True
    assert await _lapsed(hire.client, pid) is False  # money isn't theirs to see

    # A later start date gives it a fresh three months.
    res = await admin.patch(f"{API}/projects/{pid}", json={"version": created["version"], "start_date": "2027-11-01"})
    assert res.status_code == 200, res.text
    assert res.json()["lapsed"] is False
