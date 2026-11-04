"""Bidding analytics endpoints: scopes, profile names, and the joined numbers. The two Google web apps are
replaced by an in-memory cache fed with rows shaped like their real responses (tests/bidding_fixtures.py)."""

import csv
import io
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest

from app.core import clock
from app.main import app
from app.modules.bidding.cache import SnapshotCache
from app.modules.bidding.deps import get_cache
from tests.bidding_fixtures import sample_bid_tabs, sample_job_tabs
from tests.conftest import ClientFactory
from tests.factories import employee

API = "/api/v1/bidding"


@pytest.fixture(autouse=True)
def sheets() -> Iterator[SnapshotCache]:
    clock.freeze(date(2026, 11, 3))
    cache = SnapshotCache(
        bids_reader=sample_bid_tabs,
        jobs_reader=sample_job_tabs,
        ttl_seconds=300,
        now=lambda: datetime(2026, 11, 3, 12, tzinfo=UTC),
    )
    app.dependency_overrides[get_cache] = lambda: cache
    yield cache
    app.dependency_overrides.pop(get_cache, None)
    clock.freeze(None)


async def bidder(client_as: ClientFactory, name: str, role: str = "employee"):  # type: ignore[no-untyped-def]
    client = await client_as(role)
    client.employee_id = await employee(name, user_id=client.user_id)  # type: ignore[attr-defined]
    return client


async def test_employee_sets_own_profile_and_sees_only_own_numbers(client_as: ClientFactory) -> None:
    alice = await bidder(client_as, "Alice Smith")
    bob = await bidder(client_as, "Bob Jones")

    p = (await alice.get(f"{API}/me/profile")).json()
    assert p["profile_names"] == [] and p["tabs"] == []
    assert set(p["available_tabs"]) == {"Alice Smith", "bob  jones", "Carol"}
    s = (await alice.get(f"{API}/stats")).json()
    assert s["profile_missing"] and s["applied"] == 0

    res = await alice.put(f"{API}/me/profile", json={"profile_names": ["  alice   smith "]})
    assert res.status_code == 200, res.text
    p = res.json()
    assert p["profile_names"] == ["alice smith"] and p["tabs"][0]["found"]
    assert p["applied"] == 3

    clash = await bob.put(f"{API}/me/profile", json={"profile_names": ["Bob Jones", "Alice Smith"]})
    assert clash.status_code == 422 and clash.json()["errors"][0]["field"] == "bidding_profile_names"
    assert (await bob.put(f"{API}/me/profile", json={"profile_names": ["Bob Jones"]})).status_code == 200

    s = (await alice.get(f"{API}/stats", params={"date_from": "2026-11-01", "date_to": "2026-11-03"})).json()
    assert s["applied"] == 3 and s["employee_name"] == "Alice Smith" and s["employees"] == []
    assert [d["applied"] for d in s["series"]] == [0, 1, 2]

    bids = (await alice.get(f"{API}/bids")).json()
    assert bids["total"] == 3 and {b["employee_name"] for b in bids["items"]} == {"Alice Smith"}
    other = await alice.get(f"{API}/stats", params={"employee_id": bob.employee_id})
    assert other.status_code == 404
    # an employee can narrow to one of their own tabs, and never reaches someone else's
    assert (await alice.get(f"{API}/bids", params={"tab": "ALICE SMITH"})).json()["total"] == 3
    assert (await alice.get(f"{API}/bids", params={"tab": "bob  jones"})).json()["total"] == 0
    assert (await alice.get(f"{API}/stats", params={"tab": "bob  jones"})).json()["applied"] == 0

    daily = (await alice.get(f"{API}/daily", params={"date_from": "2026-11-03", "date_to": "2026-11-03"})).json()
    assert [r["name"] for r in daily["rows"]] == ["Alice Smith"] and daily["applied"] == 2
    assert (await alice.get(f"{API}/daily")).json()["date_to"] == "2026-11-03"  # default: today
    span = (await alice.get(f"{API}/daily", params={"date_from": "2026-11-01", "date_to": "2026-11-03"})).json()
    assert span["applied"] == 3 and span["rows"][0]["tabs"] == ["alice smith"]

    # The job list is shared: everyone sees who bid on what.
    jobs = (await alice.get(f"{API}/jobs")).json()
    acme = next(j for j in jobs["items"] if j["company"] == "Acme")
    assert acme["status"] == "applied" and acme["duplicate"]
    assert {b["employee_name"] for b in acme["bids"]} == {"Alice Smith", "Bob Jones"}
    assert (jobs["not_bid"], jobs["applied"]) == (1, 2)
    mine = (await bob.get(f"{API}/jobs", params={"mine": True})).json()
    assert [j["company"] for j in mine["items"]] == ["Acme"]

    assert (await alice.get(f"{API}/sources")).status_code == 403
    assert (
        await alice.put(f"{API}/employees/{bob.employee_id}/profile", json={"profile_names": ["x"]})
    ).status_code == 403


async def test_manager_sees_everyone(client_as: ClientFactory, admin) -> None:  # type: ignore[no-untyped-def]
    alice = await bidder(client_as, "Alice Smith")
    await alice.put(f"{API}/me/profile", json={"profile_names": ["Alice Smith"]})
    pm = await bidder(client_as, "Peter PM", "project_manager")

    s = (await pm.get(f"{API}/stats", params={"date_from": "2026-11-01", "date_to": "2026-11-03"})).json()
    assert s["applied"] == 4 and s["scraped"] == 3 and s["coverage_pct"] == 66.7 and s["outside_job_list"] == 1
    rows = {r["name"]: r for r in s["employees"]}
    assert rows["Alice Smith"]["employee_id"] == alice.employee_id and rows["Alice Smith"]["by_day"] == [0, 1, 2]
    assert rows["bob  jones"]["employee_id"] is None  # tab nobody has claimed yet

    one = (await pm.get(f"{API}/stats", params={"employee_id": alice.employee_id})).json()
    assert one["applied"] == 3 and one["employee_name"] == "Alice Smith"
    # What My Bidding asks for: a manager's own numbers, not the company's.
    own = (await pm.get(f"{API}/stats", params={"employee_id": pm.employee_id})).json()
    assert own["applied"] == 0 and own["profile_missing"] and own["resumes"] == [] and own["employees"] == []
    assert (await pm.get(f"{API}/bids", params={"employee_id": pm.employee_id})).json()["total"] == 0
    tab = (await pm.get(f"{API}/bids", params={"tab": "Carol"})).json()
    assert tab["total"] == 1 and tab["items"][0]["employee_id"] is None

    filtered = (await pm.get(f"{API}/bids", params={"min_score": 85})).json()
    assert sorted(b["company"] for b in filtered["items"]) == ["Acme", "Gamma"]

    export = await pm.get(f"{API}/bids/export", params={"format": "csv", "employee_id": alice.employee_id})
    assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv")
    lines = list(csv.reader(io.StringIO(export.text.lstrip("﻿"))))
    assert lines[0][:4] == ["Date", "Employee", "Tab", "Title"] and len(lines) == 4

    assert (await pm.get(f"{API}/bids/export", params={"format": "pdf"})).status_code == 422
    assert (await pm.get(f"{API}/bids/export", params={"format": "xlsx"})).status_code == 200

    # Job filters take several values. The job list has no export: use the Google Sheet.
    one = (await pm.get(f"{API}/jobs", params={"role": "Data"})).json()["total"]
    two = (await pm.get(f"{API}/jobs", params={"role": ["Data", "Software"]})).json()["total"]
    assert one == 1 and two > one
    assert (await pm.get(f"{API}/jobs/export", params={"format": "csv"})).status_code == 404

    daily_csv = await pm.get(f"{API}/daily/export", params={"date_from": "2026-11-01", "date_to": "2026-11-03"})
    assert daily_csv.status_code == 200 and "Top resumes" in daily_csv.text

    # Admin (bidding.manage): sources, and setting someone else's profile name.
    src = (await admin.get(f"{API}/sources")).json()
    assert set(src["unclaimed_tabs"]) == {"bob  jones", "Carol"}
    assert [t["name"] for t in src["job_tabs"]] == ["US - Software", "US - Data", "EU - Software"]
    assert src["data"]["bids"]["configured"] and src["data"]["bids"]["error"] is None
    carol = await employee("Carol Diaz")
    res = await admin.put(f"{API}/employees/{carol}/profile", json={"profile_names": ["Carol"]})
    assert res.status_code == 200 and res.json()["applied"] == 1
    src = (await admin.get(f"{API}/sources")).json()
    assert src["unclaimed_tabs"] == ["bob  jones"]
    assert (await admin.post(f"{API}/refresh")).status_code == 200

    profile = (await admin.get(f"/api/v1/employees/{carol}")).json()
    assert profile["bidding_profile_names"] == ["Carol"]


async def test_a_manager_who_bids_can_get_only_their_own_numbers(client_as: ClientFactory) -> None:
    # What the dashboard asks for: real bidders hold both the Employee and Project Manager roles.
    pm = await bidder(client_as, "Peter PM", "project_manager")
    await pm.put(f"{API}/me/profile", json={"profile_names": ["Carol"]})
    dates = {"date_from": "2026-10-01", "date_to": "2026-11-03"}
    own = (await pm.get(f"{API}/stats", params={**dates, "employee_id": pm.employee_id})).json()
    team = (await pm.get(f"{API}/stats", params=dates)).json()
    assert own["applied"] == 1 and team["applied"] == 5
    assert own["employees"] == [] and len(team["employees"]) > 1
    assert [c["name"] for c in own["resumes"]] == ["3"] and len(team["resumes"]) > 1
    assert own["outside_job_list"] == 1


async def test_employee_with_several_profile_names(client_as: ClientFactory, admin) -> None:  # type: ignore[no-untyped-def]
    alice = await bidder(client_as, "Alice Smith")
    res = await alice.put(f"{API}/me/profile", json={"profile_names": ["Alice Smith", "carol", " CAROL ", ""]})
    assert res.status_code == 200, res.text
    p = res.json()
    assert p["profile_names"] == ["Alice Smith", "carol"]  # blanks and repeats dropped
    assert p["applied"] == 4 and [t["applied"] for t in p["tabs"]] == [3, 1] and all(t["found"] for t in p["tabs"])

    s = (await alice.get(f"{API}/stats", params={"date_from": "2026-10-01", "date_to": "2026-11-03"})).json()
    assert s["applied"] == 4 and s["profile_names"] == ["Alice Smith", "carol"]
    assert {c["name"]: c["count"] for c in s["profiles"]} == {"Alice Smith": 3, "carol": 1}
    one = (
        await alice.get(f"{API}/stats", params={"date_from": "2026-10-01", "date_to": "2026-11-03", "tab": "CAROL"})
    ).json()
    assert one["applied"] == 1
    assert (await alice.get(f"{API}/bids")).json()["total"] == 4

    # Managers see one row for the person, and the name change is audited.
    team = (await admin.get(f"{API}/stats", params={"date_from": "2026-10-01", "date_to": "2026-11-03"})).json()
    row = next(r for r in team["employees"] if r["name"] == "Alice Smith")
    assert row["applied"] == 4 and row["tabs"] == ["Alice Smith", "carol"]
    assert "carol" not in {r["name"] for r in team["employees"]}
    src = (await admin.get(f"{API}/sources")).json()
    assert src["unclaimed_tabs"] == ["bob  jones"]
    assert next(e for e in src["employees"] if e["name"] == "Alice Smith")["profile_names"] == ["Alice Smith", "carol"]
    audit = (await admin.get("/api/v1/audit-logs", params={"entity_type": "employee"})).text
    assert "employee.bidding_profiles_set" in audit

    # Same names again, with only the case changed: kept, and removing one frees the tab for someone else.
    p = (await alice.put(f"{API}/me/profile", json={"profile_names": ["alice smith", "Carol"]})).json()
    assert p["profile_names"] == ["alice smith", "Carol"]
    bob = await bidder(client_as, "Bob Jones")
    assert (await bob.put(f"{API}/me/profile", json={"profile_names": ["carol"]})).status_code == 422
    assert (await alice.put(f"{API}/me/profile", json={"profile_names": ["alice smith"]})).status_code == 200
    assert (await bob.put(f"{API}/me/profile", json={"profile_names": ["carol"]})).status_code == 200
    assert (await bob.put(f"{API}/me/profile", json={"profile_name": "old shape"})).status_code == 422


async def test_access_rules(client_as: ClientFactory) -> None:
    finance = await client_as("finance_manager")
    assert (await finance.get(f"{API}/stats")).status_code == 403
    assert (await finance.get(f"{API}/jobs")).status_code == 403
    unlinked = await client_as("employee")
    res = await unlinked.get(f"{API}/me/profile")
    assert res.status_code == 404 and "not linked" in res.json()["detail"]
    assert (await unlinked.get(f"{API}/jobs")).status_code == 200  # the job list needs no employee record
    # "Mine" with no employee record is just an empty list.
    mine = await unlinked.get(f"{API}/jobs", params={"mine": True})
    assert mine.status_code == 200 and mine.json()["total"] == 0


async def test_sorting_covers_every_page(client_as: ClientFactory) -> None:
    pm = await bidder(client_as, "Peter PM", "project_manager")

    async def companies(path: str, **params: object) -> list[str]:
        res = await pm.get(f"{API}/{path}", params={"page_size": 1, **params})
        assert res.status_code == 200, res.text
        return [row["company"] for row in res.json()["items"]]

    # The first page holds the top row of the whole list, not of whatever page was loaded.
    assert await companies("jobs", sort="job") == ["Acme"]
    assert await companies("jobs", sort="job", desc=True) == ["Omega"]
    assert await companies("jobs", sort="job", desc=True, page=3) == ["Acme"]
    assert await companies("jobs", sort="first_seen", desc=True) == ["Omega"]
    assert await companies("jobs", sort="ats") == ["Acme"]  # Greenhouse < Lever < Workday
    assert await companies("bids", sort="score", desc=True) == ["Gamma"]
    assert await companies("bids", sort="score") == ["Acme"]  # lowest score; blanks stay last both ways
    assert await companies("bids", sort="job", desc=True) == ["Zeta"]
    assert (await pm.get(f"{API}/jobs", params={"sort": "nonsense"})).status_code == 422
    export = await pm.get(f"{API}/bids/export", params={"sort": "score", "desc": True})
    assert "Gamma" in export.text.splitlines()[1]


async def test_a_job_in_two_tabs_shows_under_both(client_as: ClientFactory, admin) -> None:  # type: ignore[no-untyped-def]
    pm = await bidder(client_as, "Peter PM", "project_manager")

    async def jobs(**params: object) -> list[str]:
        return [j["company"] for j in (await pm.get(f"{API}/jobs", params=params)).json()["items"]]

    assert "Acme" in await jobs(region="US") and "Acme" in await jobs(region="EU")
    assert await jobs(region="EU", role="Software") == ["Acme"]
    assert await jobs(region="EU", role="Data") == []  # region and role must match the same tab
    acme = next(j for j in (await pm.get(f"{API}/jobs")).json()["items"] if j["company"] == "Acme")
    assert acme["listings"] == ["US · Software", "EU · Software"]
    assert (await pm.get(f"{API}/jobs")).json()["total"] == 3  # still one job

    stats = (await pm.get(f"{API}/stats", params={"date_from": "2026-11-01", "date_to": "2026-11-03"})).json()
    roles = {c["name"]: c["count"] for c in stats["roles"]}
    assert roles["US · Software"] == roles["EU · Software"] == 2

    src = (await admin.get(f"{API}/sources")).json()
    assert {t["name"]: t["rows"] for t in src["job_tabs"]} == {"US - Software": 2, "US - Data": 1, "EU - Software": 1}


async def test_sheet_errors_are_reported_not_raised(client_as: ClientFactory, admin, sheets) -> None:  # type: ignore[no-untyped-def]
    from app.modules.bidding.sheets import SheetsError

    def broken() -> list:  # type: ignore[type-arg]
        raise SheetsError("Invalid secret.")

    sheets.bids_reader = broken
    src = (await admin.get(f"{API}/sources")).json()
    assert src["data"]["bids"]["error"] == "Invalid secret." and src["tabs"] == []
    assert src["data"]["jobs"]["error"] is None and len(src["job_tabs"]) == 3


async def test_connection_settings_from_the_ui(client_as: ClientFactory, admin, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    url = "https://script.google.com/macros/s/AKfyBids/exec"
    s = (await admin.get(f"{API}/settings")).json()
    assert s["version"] == 0 and s["bids_webapp_url"] == "" and not s["bids_secret_set"]

    bad = await admin.put(f"{API}/settings", json={"version": 0, "bids_webapp_url": "https://example.com/hook"})
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "bids_webapp_url"

    res = await admin.put(
        f"{API}/settings",
        json={
            "version": 0,
            "bids_webapp_url": url,
            "bids_secret": "super-secret-9876",
            "jobs_tabs": ["US - Software", " "],
        },
    )
    assert res.status_code == 200, res.text
    s = res.json()
    assert s["bids_webapp_url"] == url and s["bids_secret_set"] and s["bids_secret_hint"] == "…9876"
    assert s["jobs_tabs"] == ["US - Software"] and s["version"] == 1
    assert "super-secret" not in res.text and "super-secret" not in (await admin.get(f"{API}/settings")).text

    # Omitting the secret keeps it; "" removes it; a stale version is refused.
    s = (await admin.put(f"{API}/settings", json={"version": 1, "cache_seconds": 120})).json()
    assert s["bids_secret_set"] and s["cache_seconds"] == 120
    assert (await admin.put(f"{API}/settings", json={"version": 1, "bids_secret": ""})).status_code == 412
    s = (await admin.put(f"{API}/settings", json={"version": 2, "bids_secret": ""})).json()
    assert not s["bids_secret_set"]

    audit = (await admin.get("/api/v1/audit-logs", params={"entity_type": "bidding_settings"})).text
    assert "super-secret" not in audit

    # Test a connection with typed values; the web app call is replaced here.
    from app.modules.bidding import router as bidding_router

    monkeypatch.setattr(bidding_router, "test_bids", lambda app, secret: [("Alice", 3), ("Bob", 0)])
    t = (await admin.post(f"{API}/settings/test", json={"target": "bids", "secret": "typed"})).json()
    assert t["ok"] and [x["name"] for x in t["tabs"]] == ["Alice", "Bob"]
    t = (await admin.post(f"{API}/settings/test", json={"target": "jobs"})).json()
    assert not t["ok"]  # no job-list URL saved yet

    # Removing the only secret above needs it saved again for what follows.
    s = (await admin.put(f"{API}/settings", json={"version": 3, "bids_secret": "super-secret-9876"})).json()
    assert s["version"] == 4
    other = "https://script.google.com/macros/s/AKfyOther/exec"
    sent: list[str] = []

    def record(app, secret):  # type: ignore[no-untyped-def]
        sent.append(secret)
        return []

    monkeypatch.setattr(bidding_router, "test_bids", record)
    # The saved secret goes to the saved URL, and never to a URL typed in the form.
    assert (await admin.post(f"{API}/settings/test", json={"target": "bids", "url": url})).json()["ok"]
    assert sent == ["super-secret-9876"]
    t = (await admin.post(f"{API}/settings/test", json={"target": "bids", "url": other})).json()
    assert not t["ok"] and "enter its secret" in t["message"] and len(sent) == 1
    t = (await admin.post(f"{API}/settings/test", json={"target": "bids", "url": other, "secret": "typed"})).json()
    assert t["ok"] and sent[-1] == "typed"

    # Same for saving: a new URL needs its secret, or the next read would send the old one there.
    res = await admin.put(f"{API}/settings", json={"version": 4, "bids_webapp_url": other})
    assert res.status_code == 422 and res.json()["errors"][0]["field"] == "bids_secret"
    res = await admin.put(
        f"{API}/settings", json={"version": 4, "bids_webapp_url": other, "bids_secret": "new-secret-1234"}
    )
    assert res.status_code == 200 and res.json()["bids_webapp_url"] == other

    employee = await client_as("employee")
    assert (await employee.get(f"{API}/settings")).status_code == 403
    assert (await employee.put(f"{API}/settings", json={"version": 5})).status_code == 403
