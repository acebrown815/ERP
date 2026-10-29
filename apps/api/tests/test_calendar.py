"""Phase 5/6: calendar, leave, workload, reminders, reports, exports, dashboard, consistency checks, readiness."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.core import clock
from app.core.db import SessionLocal
from app.modules.calendar import recurrence
from app.modules.calendar import service as calendar
from tests.conftest import ClientFactory
from tests.factories import category_id, customer, employee, project, receipt_body
from tests.test_payments import create_and_submit

D = Decimal
API = "/api/v1"


@pytest.fixture(autouse=True)
def today() -> Iterator[None]:
    clock.freeze(date(2026, 11, 10))
    yield
    clock.freeze(None)


def test_weekly_meeting_keeps_local_time_across_dst() -> None:
    rule = recurrence.normalize("FREQ=WEEKLY;BYDAY=MO;UNTIL=20261102", tz="Europe/Berlin", all_day=False)
    start = datetime(2026, 10, 19, 7, 0, tzinfo=UTC)  # 09:00 CEST
    occ = recurrence.expand_timed(
        start,
        start.replace(hour=8),
        "Europe/Berlin",
        rule,
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 12, 1, tzinfo=UTC),
    )
    assert [o.start_at.hour for o in occ] == [7, 8, 8]  # 09:00 local before and after the switch (Oct 25)
    yearly = recurrence.expand_all_day(
        date(2026, 12, 24), date(2026, 12, 26), "FREQ=YEARLY;COUNT=2", date(2026, 1, 1), date(2030, 1, 1)
    )
    assert [o.key for o in yearly] == ["2026-12-24", "2027-12-24"]
    with pytest.raises(recurrence.RecurrenceError):
        recurrence.normalize("FREQ=HOURLY", tz="UTC", all_day=False)


@pytest.fixture
async def team(admin, client_as: ClientFactory) -> dict:  # type: ignore[no-untyped-def]
    staff = await client_as("employee")
    other = await client_as("employee")
    dept = (await admin.post(f"{API}/departments", json={"name": "Delivery"})).json()
    a = await employee("Employee A", user_id=staff.user_id)
    b = await employee("Employee B", user_id=other.user_id)
    for e in (a, b):
        v = (await admin.get(f"{API}/employees/{e}")).json()["version"]
        await admin.patch(f"{API}/employees/{e}", json={"version": v, "department_id": dept["id"]})
    abc = await customer("Customer ABC")
    p = await project("ABC Web Platform", abc, [(a, D(60)), (b, D(40))])
    return {"staff": staff, "other": other, "a": a, "b": b, "dept": dept["id"], "project": p, "customer": abc}


async def test_events_feed_privacy_and_occurrences(admin, team) -> None:  # type: ignore[no-untyped-def]
    staff, other = team["staff"], team["other"]
    meeting = await staff.post(
        f"{API}/calendar/events",
        json={
            "title": "1:1 with B",
            "start_at": "2026-11-02T09:00:00Z",
            "end_at": "2026-11-02T09:30:00Z",
            "timezone": "UTC",
            "rrule": "FREQ=WEEKLY;COUNT=4",
            "attendee_ids": [team["b"]],
            "reminders": [15],
        },
    )
    assert meeting.status_code == 201, meeting.text
    m = meeting.json()
    private = (
        await staff.post(
            f"{API}/calendar/events",
            json={"title": "Dentist", "all_day": True, "start_date": "2026-11-12", "end_date": "2026-11-12"},
        )
    ).json()
    feed = (await staff.get(f"{API}/calendar/feed", params={"from": "2026-11-01", "to": "2026-11-30"})).json()
    starts = [i["start"] for i in feed["items"] if i["id"] == m["id"]]
    assert starts == [
        "2026-11-02T09:00:00+00:00",
        "2026-11-09T09:00:00+00:00",
        "2026-11-16T09:00:00+00:00",
        "2026-11-23T09:00:00+00:00",
    ]
    # The invitee sees the meeting; nobody else sees the private appointment.
    theirs = (await other.get(f"{API}/calendar/feed", params={"from": "2026-11-01", "to": "2026-11-30"})).json()
    assert any(i["id"] == m["id"] for i in theirs["items"]) and not any(
        i["id"] == private["id"] for i in theirs["items"]
    )
    assert (await other.get(f"{API}/calendar/events/{private['id']}")).status_code == 404
    # Skip one occurrence.
    skip = await staff.post(
        f"{API}/calendar/events/{m['id']}/cancel-occurrence", json={"occurrence": "2026-11-09T09:00:00+00:00"}
    )
    assert skip.status_code == 204
    feed = (await staff.get(f"{API}/calendar/feed", params={"from": "2026-11-01", "to": "2026-11-30"})).json()
    assert len([i for i in feed["items"] if i["id"] == m["id"]]) == 3
    # Employees can't post company events.
    company = await staff.post(
        f"{API}/calendar/events",
        json={
            "scope": "company",
            "title": "Party",
            "all_day": True,
            "start_date": "2026-12-18",
            "end_date": "2026-12-18",
        },
    )
    assert company.status_code == 403
    ok = await admin.post(
        f"{API}/calendar/events",
        json={
            "scope": "company",
            "title": "Party",
            "all_day": True,
            "start_date": "2026-12-18",
            "end_date": "2026-12-18",
        },
    )
    assert ok.status_code == 201
    # Reminders: due 15 minutes before; sent once.
    async with SessionLocal() as s:
        now = datetime(2026, 11, 2, 8, 50, tzinfo=UTC)
        assert await calendar.send_reminders(s, now) >= 2  # owner and invitee
        await calendar.send_reminders(s, now)
        await s.commit()
    notes = (await other.get(f"{API}/notifications")).json()
    assert notes["unread"] == 1 and notes["items"][0]["title"] == "Reminder: 1:1 with B"
    await other.post(f"{API}/notifications/read", json={})
    assert (await other.get(f"{API}/notifications")).json()["unread"] == 0


async def test_leave_approval_workload_and_derived_items(admin, client_as: ClientFactory, team) -> None:  # type: ignore[no-untyped-def]
    staff = team["staff"]
    leave_type = await category_id("event_type", "leave")
    req = await staff.post(
        f"{API}/calendar/events",
        json={
            "title": "Holiday",
            "event_type_category_id": leave_type,
            "all_day": True,
            "start_date": "2026-11-16",
            "end_date": "2026-11-17",
        },
    )
    assert req.status_code == 201 and req.json()["status"] == "requested"
    pending = (await admin.get(f"{API}/calendar/leave/pending")).json()
    assert [p["title"] for p in pending] == ["Holiday"]
    assert (
        await staff.post(f"{API}/calendar/events/{req.json()['id']}/decision", json={"approve": True})
    ).status_code == 403
    decided = await admin.post(
        f"{API}/calendar/events/{req.json()['id']}/decision", json={"approve": True, "note": "Enjoy"}
    )
    assert decided.status_code == 200 and decided.json()["status"] == "approved"
    notes = (await staff.get(f"{API}/notifications")).json()["items"]
    assert notes[0]["title"] == "Leave approved: Holiday"

    # A task assigned to A appears in A's calendar, the team calendar and the workload.
    task = await admin.post(
        f"{API}/tasks",
        json={
            "project_id": team["project"],
            "title": "Build API",
            "start_date": "2026-11-16",
            "due_date": "2026-11-20",
            "estimate_hours": "15",
            "assignee_ids": [team["a"]],
        },
    )
    assert task.status_code == 201
    mine = (await staff.get(f"{API}/calendar/feed", params={"from": "2026-11-15", "to": "2026-11-21"})).json()
    kinds = {(i["kind"], i["title"]) for i in mine["items"]}
    assert ("task", f"{task.json()['number']} Build API") in kinds and ("leave", "Holiday") in kinds
    company = (
        await admin.get(f"{API}/calendar/feed", params={"from": "2026-11-15", "to": "2026-11-21", "view": "company"})
    ).json()
    assert any(i["kind"] == "leave" for i in company["items"])  # approved leave is visible company-wide
    teamview = (
        await staff.get(f"{API}/calendar/feed", params={"from": "2026-11-15", "to": "2026-11-21", "view": "team"})
    ).json()
    assert any(i["kind"] == "leave" for i in teamview["items"])

    load = (
        await admin.get(
            f"{API}/calendar/workload", params={"from": "2026-11-16", "to": "2026-11-20", "department_id": team["dept"]}
        )
    ).json()
    a = next(r for r in load if r["employee_name"] == "Employee A")
    caps = [d["capacity"] for d in a["days"]]
    assert caps == ["0", "0", "8", "8", "8"]  # leave Mon-Tue
    assert [d["tasks"] for d in a["days"]] == ["3.00"] * 5  # 15 h over 5 working days
    assert (
        await team["other"].get(
            f"{API}/calendar/workload", params={"from": "2026-11-16", "to": "2026-11-20", "department_id": team["dept"]}
        )
    ).status_code == 200


async def test_reports_exports_dashboard_and_checks(admin, client_as: ClientFactory, team) -> None:  # type: ignore[no-untyped-def]
    finance = await client_as("finance_manager")
    await create_and_submit(finance, await receipt_body(party_id=team["customer"], project_id=team["project"]))
    cat = (
        await finance.get(
            f"{API}/reports/by-category", params={"kind": "income", "from": "2026-11-01", "to": "2026-11-30"}
        )
    ).json()
    assert D(cat["total"]) == 10000 and cat["rows"][0]["share_pct"] == "100.0"
    parties = (
        await finance.get(
            f"{API}/reports/party-payments", params={"direction": "receive", "from": "2026-11-01", "to": "2026-11-30"}
        )
    ).json()
    assert parties["rows"][0]["party_name"] == "Customer ABC" and D(parties["total"]) == 10000
    monthly = (await finance.get(f"{API}/reports/monthly-summary", params={"periods": 3})).json()
    assert D(monthly["totals"]["income"]) == 10000

    xlsx = await finance.get(
        f"{API}/reports/by-category",
        params={"kind": "income", "from": "2026-11-01", "to": "2026-11-30", "format": "xlsx"},
    )
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"  # zip container
    pdf = await finance.get(
        f"{API}/reports/trial-balance", params={"from": "2026-11-01", "to": "2026-11-30", "format": "pdf"}
    )
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    csv = await finance.get(f"{API}/reports/monthly-summary", params={"format": "csv"})
    assert "salary calculated" in csv.text

    dash = (await finance.get(f"{API}/dashboard/company")).json()
    assert dash["period_label"] == "Nov 2026" and D(dash["income"]) == 10000 and dash["projects_active"] == 1
    assert (await team["staff"].get(f"{API}/dashboard/company")).status_code == 403

    checks = (await admin.get(f"{API}/system/checks")).json()
    assert checks["ok"] is True, checks
    assert {c["key"] for c in checks["checks"]} >= {
        "ledger_balanced",
        "balance_sheet",
        "revenue_splits",
        "salary_links",
        "audit_chain",
    }
    assert (await team["staff"].get(f"{API}/system/checks")).status_code == 403


async def test_health_ready_and_security_headers(admin) -> None:  # type: ignore[no-untyped-def]
    ready = await admin.get("/api/health/ready")
    assert ready.status_code == 200 and ready.json()["status"] == "ok"
    me = await admin.get(f"{API}/auth/me")
    assert me.headers["X-Content-Type-Options"] == "nosniff" and me.headers["X-Frame-Options"] == "DENY"
    assert me.headers["Cache-Control"] == "no-store"
