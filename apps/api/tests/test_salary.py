"""Salary periods, statements, payments and balances through the API (docs/architecture.md, Sections 10 and 16)."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest

from app.core import clock
from tests.conftest import ClientFactory
from tests.factories import category_id, customer, employee, payment_account_id, project, receipt_body
from tests.test_payments import PE, create_and_submit, idem

D = Decimal
API = "/api/v1"


@pytest.fixture(autouse=True)
def today() -> Iterator[None]:
    """The reference scenario happens in November 2026."""
    clock.freeze(date(2026, 11, 10))
    yield
    clock.freeze(None)


@pytest.fixture
async def finance(client_as: ClientFactory):  # type: ignore[no-untyped-def]
    return await client_as("finance_manager")


async def default_formula(c) -> dict:  # type: ignore[no-untyped-def]
    formulas = (await c.get(f"{API}/comp-formulas")).json()
    return next(f for f in formulas if f["name"] == "Revenue Share (provisional)")


async def assign(c, employee_id: str, formula_id: str, start: str = "2026-01-01") -> dict:  # type: ignore[no-untyped-def]
    res = await c.post(
        f"{API}/comp-assignments", json={"employee_id": employee_id, "formula_id": formula_id, "effective_from": start}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def salary_body(c, employee_id: str, amount: str, on: str = "2026-11-20", **extra: str) -> dict:  # type: ignore[no-untyped-def]
    emp = (await c.get(f"{API}/employees/{employee_id}")).json()
    return {
        "posting_date": on,
        "direction": "pay",
        "amount": amount,
        "method_category_id": await category_id("payment_method", "bank_transfer"),
        "purpose_category_id": await category_id("payment_purpose", "employee_salary"),
        "paid_from_payment_account_id": await payment_account_id("Company Checking"),
        "party_id": emp["party_id"],
        **extra,
    }


async def period(c, label: str) -> dict:  # type: ignore[no-untyped-def]
    return next(p for p in (await c.get(f"{API}/salary-periods")).json() if p["label"] == label)


async def board(c, period_id: str) -> dict[str, dict]:  # type: ignore[no-untyped-def]
    res = await c.get(f"{API}/salary-periods/{period_id}/statements")
    assert res.status_code == 200, res.text
    return {r["employee_name"]: r for r in res.json()["rows"]}


@pytest.fixture
async def scenario(admin) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """25th cycle, Employees A and B on the provisional formula, project 60/40 for Customer ABC."""
    res = await admin.put(f"{API}/settings/salary-cycle", json={"salary_cycle_start_day": 25})
    assert res.status_code == 200, res.text
    abc = await customer("Customer ABC")
    a, b = await employee("Employee A"), await employee("Employee B")
    p = await project("ABC Web Platform", abc, [(a, D(60)), (b, D(40))])
    formula = await default_formula(admin)
    await assign(admin, a, formula["id"])
    await assign(admin, b, formula["id"])
    return {"customer": abc, "a": a, "b": b, "project": p, "formula": formula["id"]}


async def test_reference_scenario_end_to_end(admin, finance, scenario) -> None:  # type: ignore[no-untyped-def]
    """Section 16, the golden test."""
    receipt = await create_and_submit(
        finance, await receipt_body(party_id=scenario["customer"], project_id=scenario["project"])
    )
    nov = await period(finance, "Nov 2026")
    assert (nov["start_date"], nov["end_date"], nov["is_current"]) == ("2026-10-25", "2026-11-24", True)

    rows = await board(finance, nov["id"])
    assert {k: (v["revenue"], v["calculated"], v["status"]) for k, v in rows.items()} == {
        "Employee A": ("6000.00", "626.67", "unpaid"),
        "Employee B": ("4000.00", "352.59", "unpaid"),
    }
    assert rows["Employee A"]["formula_name"] == "Revenue Share (provisional)"
    assert [c["component"] for c in rows["Employee A"]["components"]] == ["revenue_share"]

    pay_a = await create_and_submit(finance, await salary_body(finance, scenario["a"], "626.67"))
    await create_and_submit(finance, await salary_body(finance, scenario["b"], "200.00"))
    rows = await board(finance, nov["id"])
    assert (rows["Employee A"]["paid"], rows["Employee A"]["status"], rows["Employee A"]["balance"]) == (
        "626.67",
        "paid",
        "0.00",
    )
    assert (rows["Employee B"]["paid"], rows["Employee B"]["status"], rows["Employee B"]["balance"]) == (
        "200.00",
        "partially_paid",
        "152.59",
    )

    # Ledger figures from the scenario table.
    accounts = {a["code"]: D(a["balance"]) for a in (await finance.get(f"{API}/accounts")).json()}
    assert accounts["1110"] == D("9173.33") and accounts["5100"] == D("826.67") and accounts["4100"] == D(10000)
    pl = (await finance.get(f"{API}/reports/profit-and-loss", params={"from": "2026-11-01", "to": "2026-11-30"})).json()
    assert D(pl["net_profit"]) == D("9173.33")
    tb = (await finance.get(f"{API}/reports/trial-balance", params={"from": "2026-11-01", "to": "2026-11-30"})).json()
    assert D(tb["totals"]["debit"]) == D(tb["totals"]["credit"]) == D("10826.67")
    bs = (await finance.get(f"{API}/reports/balance-sheet", params={"as_of": "2026-11-30"})).json()
    assert bs["balanced"] is True

    # Closing: only after the period ends; then the period is frozen.
    early = await finance.post(f"{API}/salary-periods/{nov['id']}/close")
    assert early.status_code == 422
    clock.freeze(date(2026, 11, 25))
    closed = await finance.post(f"{API}/salary-periods/{nov['id']}/close")
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    frozen = await board(finance, nov["id"])
    assert all(r["frozen"] for r in frozen.values())
    assert frozen["Employee B"]["calculated"] == "352.59" and frozen["Employee B"]["balance"] == "152.59"

    # Cancelling a receipt dated in a closed period is blocked until an admin reopens it.
    blocked = await finance.post(f"{PE}/{receipt['id']}/cancel", json={"reason": "wrong client"}, headers=idem())
    assert blocked.status_code == 409 and "reopen" in blocked.json()["detail"]
    assert (await finance.post(f"{API}/salary-periods/{nov['id']}/reopen", json={"reason": "x"})).status_code == 403
    reopened = await admin.post(f"{API}/salary-periods/{nov['id']}/reopen", json={"reason": "Client paid twice"})
    assert reopened.status_code == 200 and reopened.json()["reopen_reason"] == "Client paid twice"
    cancelled = await finance.post(f"{PE}/{receipt['id']}/cancel", json={"reason": "wrong client"}, headers=idem())
    assert cancelled.status_code == 200, cancelled.text

    # Revenue and projected salary drop to zero; payments made become money paid ahead.
    rows = await board(finance, nov["id"])
    assert {k: (v["revenue"], v["calculated"], v["balance"]) for k, v in rows.items()} == {
        "Employee A": ("0.00", "0.00", "-626.67"),
        "Employee B": ("0.00", "0.00", "-200.00"),
    }
    me = (await finance.get(f"{API}/employees/{scenario['a']}/salary")).json()
    assert me["balance"] == "-626.67" and me["credit"] == "626.67"
    assert me["payments"][0]["number"] == pay_a["number"]

    audit = (await admin.get(f"{API}/audit-logs", params={"entity_type": "salary_period"})).json()["items"]
    assert {e["action"] for e in audit} >= {"salary_period.closed", "salary_period.reopened"}


async def test_period_boundaries_on_the_24th_and_25th(finance, scenario) -> None:  # type: ignore[no-untyped-def]
    for on, amount in (("2026-11-24", "3000.00"), ("2026-11-25", "2999.99")):
        await create_and_submit(
            finance,
            await receipt_body(
                party_id=scenario["customer"],
                posting_date=on,
                amount=amount,
                allocations=[{"employee_id": scenario["a"], "percent": "100"}],
            ),
        )
    nov, dec = await period(finance, "Nov 2026"), await period(finance, "Dec 2026")
    assert (dec["start_date"], dec["is_future"]) == ("2026-11-25", True)
    assert (await board(finance, nov["id"]))["Employee A"]["calculated"] == "240.00"  # exactly $3,000 -> 8%
    assert (await board(finance, dec["id"]))["Employee A"]["calculated"] == "0.00"  # $2,999.99 -> nothing


async def test_payments_pay_the_oldest_period_first_unless_targeted(finance, scenario) -> None:  # type: ignore[no-untyped-def]
    clock.freeze(date(2026, 12, 30))
    for on in ("2026-11-10", "2026-12-10"):
        await create_and_submit(
            finance,
            await receipt_body(party_id=scenario["customer"], project_id=scenario["project"], posting_date=on),
        )
    nov, dec = await period(finance, "Nov 2026"), await period(finance, "Dec 2026")
    # Targeted at December: pays December even though November is older.
    await create_and_submit(
        finance, await salary_body(finance, scenario["a"], "626.67", on="2026-12-28", salary_period_id=dec["id"])
    )
    assert (await board(finance, nov["id"]))["Employee A"]["status"] == "unpaid"
    assert (await board(finance, dec["id"]))["Employee A"]["status"] == "paid"
    # Untargeted, more than November needs: November is paid, the rest is credit.
    await create_and_submit(finance, await salary_body(finance, scenario["a"], "700.00", on="2026-12-29"))
    assert (await board(finance, nov["id"]))["Employee A"]["status"] == "paid"
    summary = (await finance.get(f"{API}/employees/{scenario['a']}/salary")).json()
    assert (summary["balance"], summary["credit"]) == ("-73.33", "73.33")
    assert [s["period_label"] for s in summary["statements"]][:2] == ["Jan 2027", "Dec 2026"]
    assert summary["current"]["period_label"] == "Jan 2027"

    # Fees, partial months and other employees don't leak into the report.
    report = (await finance.get(f"{API}/reports/employee-salary")).json()
    a_row = next(r for r in report["rows"] if r["employee_name"] == "Employee A")
    assert a_row["balance"] == "-73.33"


async def test_adjustments(admin, finance, scenario) -> None:  # type: ignore[no-untyped-def]
    nov = await period(finance, "Nov 2026")
    url = f"{API}/salary-periods/{nov['id']}/adjustments"
    bonus = await finance.post(
        url, json={"employee_id": scenario["b"], "kind": "bonus", "amount": "150", "reason": "Launch"}
    )
    assert bonus.status_code == 201, bonus.text
    deduction = await finance.post(
        url, json={"employee_id": scenario["b"], "kind": "deduction", "amount": "50", "reason": "Advance"}
    )
    assert deduction.json()["amount"] == "-50.0000"
    bad = await finance.post(url, json={"employee_id": scenario["b"], "kind": "bonus", "amount": "-5", "reason": "x"})
    assert bad.status_code == 422
    row = (await board(finance, nov["id"]))["Employee B"]
    # No revenue: formula gives 0, adjustments still count.
    assert (row["formula_amount"], row["adjustments_total"], row["calculated"]) == ("0.00", "100.00", "100.00")
    assert [c["label"] for c in row["components"]][-2:] == ["Bonus: Launch", "Deduction: Advance"]
    assert (await finance.delete(f"{API}/salary-adjustments/{deduction.json()['id']}")).status_code == 204
    assert (await board(finance, nov["id"]))["Employee B"]["calculated"] == "150.00"


async def test_formula_versions_and_closed_periods(admin, finance, scenario) -> None:  # type: ignore[no-untyped-def]
    await create_and_submit(finance, await receipt_body(party_id=scenario["customer"], project_id=scenario["project"]))
    formula_id = scenario["formula"]
    nov = await period(finance, "Nov 2026")
    clock.freeze(date(2026, 11, 26))
    assert (await finance.post(f"{API}/salary-periods/{nov['id']}/close")).status_code == 200

    flat_10 = {"rate_schedule": {"mode": "flat_tiers", "tiers": [{"from_revenue": "0", "rate": "0.10"}]}}
    inside = await admin.post(
        f"{API}/comp-formulas/{formula_id}/versions", json={"definition": flat_10, "effective_from": "2026-11-01"}
    )
    assert inside.status_code == 422 and inside.json()["errors"][0]["code"] == "closed"
    later = await admin.post(
        f"{API}/comp-formulas/{formula_id}/versions", json={"definition": flat_10, "effective_from": "2026-11-25"}
    )
    assert later.status_code == 201, later.text
    detail = (await admin.get(f"{API}/comp-formulas/{formula_id}")).json()
    assert [(v["version_no"], v["is_locked"]) for v in detail["versions"]] == [(2, False), (1, True)]
    assert detail["current"]["version_no"] == 2
    assert {a["employee_name"] for a in detail["assignments"]} == {"Employee A", "Employee B"}

    # The closed period keeps its numbers; a December receipt uses version 2.
    assert (await board(finance, nov["id"]))["Employee A"]["calculated"] == "626.67"
    await create_and_submit(
        finance,
        await receipt_body(party_id=scenario["customer"], project_id=scenario["project"], posting_date="2026-11-26"),
    )
    dec = await period(finance, "Dec 2026")
    assert (await board(finance, dec["id"]))["Employee A"]["calculated"] == "600.00"
    locked = detail["versions"][1]["id"]
    assert (await admin.delete(f"{API}/comp-formula-versions/{locked}")).status_code == 409

    # Assignments can't be moved into the closed range or overlap.
    other = (
        await admin.post(
            f"{API}/comp-formulas",
            json={
                "name": "Fixed 2,000",
                "definition": {"rate_schedule": {"mode": "none"}, "fixed_amount": "2000"},
                "effective_from": "2026-01-01",
            },
        )
    ).json()
    overlap = await admin.post(
        f"{API}/comp-assignments",
        json={
            "employee_id": scenario["a"],
            "formula_id": other["id"],
            "effective_from": "2026-12-01",
            "end_previous": False,
        },
    )
    assert overlap.status_code == 422 and overlap.json()["errors"][0]["code"] == "overlap"
    switched = await admin.post(
        f"{API}/comp-assignments",
        json={"employee_id": scenario["a"], "formula_id": other["id"], "effective_from": "2026-12-01"},
    )
    assert switched.status_code == 201, switched.text
    history = (await admin.get(f"{API}/comp-assignments", params={"employee_id": scenario["a"]})).json()
    assert [(h["formula_name"], h["effective_to"]) for h in history] == [
        ("Fixed 2,000", None),
        ("Revenue Share (provisional)", "2026-11-30"),
    ]
    # Latest assignment overlapping the period wins.
    assert (await board(finance, dec["id"]))["Employee A"]["calculated"] == "2000.00"


async def test_formula_preview_and_permissions(admin, finance, client_as) -> None:  # type: ignore[no-untyped-def]
    body = {"definition": (await default_formula(admin))["current"]["definition"], "revenues": ["2999.99", "6000"]}
    res = (await finance.post(f"{API}/comp-formulas/preview", json=body)).json()
    assert [(r["revenue"], r["amount"]) for r in res["rows"]] == [("2999.99", "0.00"), ("6000", "626.67")]
    assert any(r["revenue"] == "2999.99" for r in res["chart"])  # the jump at $3k is drawn
    created = await finance.post(
        f"{API}/comp-formulas",
        json={"name": "X", "definition": body["definition"], "effective_from": "2026-01-01"},
    )
    assert created.status_code == 403  # Finance reads formulas; only admins change them by default
    bad = await admin.post(
        f"{API}/comp-formulas/preview", json={"definition": {"rate_schedule": {"mode": "linear_curve"}}}
    )
    assert bad.status_code == 422


async def test_employee_sees_only_their_own_salary(admin, finance, client_as, scenario) -> None:  # type: ignore[no-untyped-def]
    staff = await client_as("employee")
    mine = await employee("Employee C", user_id=staff.user_id)
    await assign(admin, mine, scenario["formula"])
    await create_and_submit(
        finance,
        await receipt_body(
            party_id=scenario["customer"],
            allocations=[
                {"employee_id": mine, "percent": "50"},
                {"employee_id": scenario["a"], "percent": "50"},
            ],
        ),
    )
    me = (await staff.get(f"{API}/me/salary")).json()
    assert me["employee_name"] == "Employee C" and me["current"]["revenue"] == "5000.00"
    assert me["current"]["calculated"] == "481.48"  # 5,000 x (8% + 22% x 2,000 / 27,000)
    assert me["formula"]["formula_name"] == "Revenue Share (provisional)"
    nov = await period(staff, "Nov 2026")
    assert set(await board(staff, nov["id"])) == {"Employee C"}
    assert (await staff.get(f"{API}/employees/{scenario['a']}/salary")).status_code == 404
    assert (await staff.get(f"{API}/employees/{scenario['a']}/revenue")).status_code == 404
    revenue = (await staff.get(f"{API}/employees/{mine}/revenue")).json()
    assert revenue["total"] == "5000.0000" and revenue["allocations"][0]["payment_number"].startswith("PE-")
    assert (await staff.get(f"{API}/comp-formulas")).status_code == 403
    assert (await staff.get(f"{API}/comp-assignments", params={"employee_id": mine})).status_code == 200
    assert (await staff.get(f"{API}/comp-assignments", params={"employee_id": scenario["a"]})).status_code == 403
    # Monthly summary: their own months only; not the company, not unassigned, not a colleague.
    monthly = f"{API}/reports/monthly-summary"
    own = await staff.get(monthly, params={"employee_ids": mine})
    assert own.status_code == 200 and D(own.json()["totals"]["income"]) == 5000
    assert (await staff.get(monthly)).status_code == 403
    assert (await staff.get(monthly, params={"employee_ids": mine, "unassigned": "true"})).status_code == 403
    assert (await staff.get(monthly, params={"employee_ids": scenario["a"]})).status_code == 404
    # Payment entries: read-only, only the ones about them, without colleagues' shares.
    others = await create_and_submit(
        finance, await receipt_body(party_id=scenario["customer"], project_id=scenario["project"])
    )
    listed = (await staff.get(PE, params={"employee_id": scenario["a"]})).json()[
        "items"
    ]  # their own, whatever is asked
    assert len(listed) == 1 and [a["employee_id"] for a in listed[0]["allocations"]] == [mine]
    assert (await staff.get(f"{PE}/{listed[0]['id']}")).status_code == 200
    assert (await staff.get(f"{PE}/{others['id']}")).status_code == 404
    totals = (await staff.get(f"{PE}/totals")).json()
    assert totals["count"] == 1
    # Shared payments show and count with their share only: 50% of the receipt, 30% of a shared bill.
    assert D(listed[0]["my_share"]) == 5000 and D(totals["received"]) == 5000
    bill = {**await expense_body(scenario["a"], "1000"), "employee_id": None}
    shared = await create_and_submit(
        finance,
        {
            **bill,
            "allocations": [{"employee_id": mine, "percent": "30"}, {"employee_id": scenario["a"], "percent": "70"}],
        },
    )
    seen = (await staff.get(f"{PE}/{shared['id']}")).json()
    assert D(seen["my_share"]) == 300 and [a["employee_id"] for a in seen["allocations"]] == [mine]
    totals = (await staff.get(f"{PE}/totals")).json()
    assert totals["count"] == 2 and D(totals["paid"]) == 300
    assert (await finance.get(f"{PE}/{shared['id']}")).json()["my_share"] is None  # finance sees whole amounts
    # Projects: their own payments per project, never the project's totals.
    await create_and_submit(
        finance,
        await receipt_body(
            party_id=scenario["customer"],
            project_id=scenario["project"],
            allocations=[{"employee_id": mine, "percent": "100"}],
        ),
    )
    rows = (await staff.get(f"{API}/reports/my-project-contribution")).json()
    row = next(r for r in rows if r["project_id"] == scenario["project"])
    # The sum of their payment entries on the project, as listed for them: the receipt credited 100% to them.
    assert (D(row["received"]), D(row["paid"]), D(row["net"]), row["payments"]) == (10000, 0, 10000, 1)
    # A 1,000 bill on the project shared 30% to them: 300 paid, not 1,000.
    await create_and_submit(
        finance,
        {
            **bill,
            "project_id": scenario["project"],
            "allocations": [{"employee_id": mine, "percent": "30"}, {"employee_id": scenario["a"], "percent": "70"}],
        },
    )
    rows = (await staff.get(f"{API}/reports/my-project-contribution")).json()
    row = next(r for r in rows if r["project_id"] == scenario["project"])
    assert (D(row["paid"]), D(row["net"]), row["payments"]) == (300, 9700, 2)
    assert (await staff.get(f"{API}/reports/project-profitability")).status_code == 403
    assert (await staff.post(PE, json={})).status_code == 403
    assert (await staff.post(f"{API}/salary-periods/{nov['id']}/close")).status_code == 403
    report = (await staff.get(f"{API}/reports/employee-revenue")).json()
    assert [r["employee_name"] for r in report["rows"]] == ["Employee C"]


async def test_salary_cycle_change(admin, finance) -> None:  # type: ignore[no-untyped-def]
    # Nothing depends on periods yet: switching regenerates them all, no transition.
    fresh = (await admin.post(f"{API}/settings/salary-cycle/preview", json={"salary_cycle_start_day": 25})).json()
    assert fresh["replaces_all"] is True and fresh["upcoming"][0]["start_date"] == "2026-10-25"
    await admin.put(f"{API}/settings/salary-cycle", json={"salary_cycle_start_day": 25})
    nov = await period(admin, "Nov 2026")
    await admin.post(
        f"{API}/salary-periods/{nov['id']}/adjustments",
        json={"employee_id": await employee("Employee A"), "kind": "bonus", "amount": "10", "reason": "x"},
    )
    # Now the current period is kept and a transition bridges to the new day.
    plan = (await admin.post(f"{API}/settings/salary-cycle/preview", json={"salary_cycle_start_day": 1})).json()
    assert plan["replaces_all"] is False and plan["current"]["label"] == "Nov 2026"
    assert [(s["start_date"], s["end_date"], s["is_transition"]) for s in plan["upcoming"][:2]] == [
        ("2026-11-25", "2026-11-30", True),
        ("2026-12-01", "2026-12-31", False),
    ]
    assert (await finance.put(f"{API}/settings/salary-cycle", json={"salary_cycle_start_day": 1})).status_code == 403
    assert (await admin.put(f"{API}/settings/salary-cycle", json={"salary_cycle_start_day": 1})).status_code == 200
    clock.freeze(date(2027, 1, 5))
    periods = (await admin.get(f"{API}/salary-periods")).json()
    spans = sorted((p["start_date"], p["end_date"]) for p in periods)
    assert spans == [
        ("2026-10-25", "2026-11-24"),
        ("2026-11-25", "2026-11-30"),
        ("2026-12-01", "2026-12-31"),
        ("2027-01-01", "2027-01-31"),
    ]
    company = (await admin.get(f"{API}/settings/company")).json()
    assert company["salary_cycle_start_day"] == 1


async def expense_body(employee_id: str, amount: str, on: str = "2026-11-12") -> dict:
    return {
        "posting_date": on,
        "direction": "pay",
        "amount": amount,
        "method_category_id": await category_id("payment_method", "bank_transfer"),
        "purpose_category_id": await category_id("payment_purpose", "operating_expense"),
        "category_id": await category_id("expense_category", "software_subscriptions"),
        "paid_from_payment_account_id": await payment_account_id("Company Checking"),
        "employee_id": employee_id,
    }


async def test_split_expense_is_reports_only(finance, scenario) -> None:  # type: ignore[no-untyped-def]
    await create_and_submit(finance, await receipt_body(party_id=scenario["customer"], project_id=scenario["project"]))
    nov = await period(finance, "Nov 2026")
    before = await board(finance, nov["id"])
    # $1,000 software bill: 50% A, 30% B, the rest stays with the company.
    body = {**await expense_body(scenario["a"], "1000"), "employee_id": None}
    split = [{"employee_id": scenario["a"], "percent": "50"}, {"employee_id": scenario["b"], "percent": "30"}]
    preview = (await finance.post(f"{PE}/preview", json={**body, "allocations": split})).json()
    assert preview["ok"] and [D(a["amount"]) for a in preview["allocations"]] == [500, 300]
    expense = await create_and_submit(finance, {**body, "allocations": split})
    assert [(a["status"], D(a["amount"])) for a in expense["allocations"]] == [("active", 500), ("active", 300)]

    # Salary is untouched: no expense against anyone's revenue.
    after = await board(finance, nov["id"])
    assert {k: (v["expenses"], v["calculated"]) for k, v in after.items()} == {
        k: (v["expenses"], v["calculated"]) for k, v in before.items()
    }
    # Reports carry each share.
    perf = (await finance.get(f"{API}/reports/employee-performance")).json()
    a = next(r for r in perf["rows"] if r["employee_id"] == scenario["a"])
    assert D(a["shared_expenses"]) == 500
    assert D(a["contribution"]) == D(a["net_revenue"]) - D(a["salary"]) - 500
    m = (await finance.get(f"{API}/reports/monthly-summary", params={"employee_ids": scenario["a"]})).json()
    assert D(m["totals"]["shared_expenses"]) == 500 and D(m["totals"]["profit"]) == D(a["contribution"])
    # The employee filter on payments finds the shared bill.
    found = (await finance.get(PE, params={"employee_id": scenario["b"]})).json()
    assert expense["id"] in [p["id"] for p in found["items"]]

    # Cancelling removes the shares.
    cancelled = await finance.post(f"{PE}/{expense['id']}/cancel", json={"reason": "wrong bill"}, headers=idem())
    assert cancelled.status_code == 200
    perf = (await finance.get(f"{API}/reports/employee-performance")).json()
    assert all(D(r["shared_expenses"]) == 0 for r in perf["rows"])

    # Tagged to one employee and split at once: refused.
    both = await finance.post(PE, json={**body, "employee_id": scenario["a"], "allocations": split})
    submit = await finance.post(f"{PE}/{both.json()['id']}/submit", headers=idem())
    assert submit.status_code == 422


async def test_employee_expenses_reduce_revenue_and_salary(admin, finance, scenario) -> None:  # type: ignore[no-untyped-def]
    await create_and_submit(finance, await receipt_body(party_id=scenario["customer"], project_id=scenario["project"]))
    nov = await period(finance, "Nov 2026")
    # A's $6,000 less a $1,000 expense tagged to A: the formula runs on $5,000.
    expense = await create_and_submit(finance, await expense_body(scenario["a"], "1000"))
    rows = await board(finance, nov["id"])
    a = rows["Employee A"]
    assert (a["gross_revenue"], a["expenses"], a["revenue"], a["calculated"]) == (
        "6000.00",
        "1000.00",
        "5000.00",
        "481.48",
    )
    assert rows["Employee B"]["calculated"] == "352.59"  # untouched

    # A salary payment is tagged to the employee too, but it is not an expense against their revenue.
    await create_and_submit(finance, await salary_body(finance, scenario["b"], "100.00"))
    assert (await board(finance, nov["id"]))["Employee B"]["expenses"] == "0.00"

    # Expenses above revenue: negative net, no revenue share (never a negative salary).
    await create_and_submit(finance, await expense_body(scenario["b"], "4500"))
    b = (await board(finance, nov["id"]))["Employee B"]
    assert (b["revenue"], b["calculated"]) == ("-500.00", "0.00")

    detail = (await finance.get(f"{API}/employees/{scenario['a']}/revenue")).json()
    assert (detail["total"], detail["expenses_total"], detail["net"]) == ("6000.0000", "1000.0000", "5000.0000")
    assert detail["expenses"][0]["payment_number"] == expense["number"]
    report = (await finance.get(f"{API}/reports/employee-revenue")).json()
    row = next(r for r in report["rows"] if r["employee_name"] == "Employee A")
    assert D(row["total"]) == 5000 and D(sum(D(x) for x in row["expenses_by_period"])) == 1000

    # Cancelling the expense restores the revenue; in a closed period it is blocked like a receipt.
    cancelled = await finance.post(f"{PE}/{expense['id']}/cancel", json={"reason": "wrong employee"}, headers=idem())
    assert cancelled.status_code == 200
    assert (await board(finance, nov["id"]))["Employee A"]["calculated"] == "626.67"
    again = await create_and_submit(finance, await expense_body(scenario["a"], "1000"))
    clock.freeze(date(2026, 11, 25))
    assert (await finance.post(f"{API}/salary-periods/{nov['id']}/close")).status_code == 200
    frozen = (await board(finance, nov["id"]))["Employee A"]
    assert (frozen["gross_revenue"], frozen["expenses"], frozen["calculated"]) == ("6000.00", "1000.00", "481.48")
    blocked = await finance.post(f"{PE}/{again['id']}/cancel", json={"reason": "x" * 5}, headers=idem())
    assert blocked.status_code == 409
    late = await finance.post(PE, json=await expense_body(scenario["a"], "50", on="2026-11-20"))
    submit = await finance.post(f"{PE}/{late.json()['id']}/submit", headers=idem())
    assert submit.status_code == 409  # dated in the closed period
