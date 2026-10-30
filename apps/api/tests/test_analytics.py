"""Trend and analysis reports: monthly summary extras, cash flow and runway, customers, trends, performance."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest

from app.core import clock
from tests.conftest import ClientFactory
from tests.factories import category_id, customer, employee, payment_account_id, project, receipt_body
from tests.test_payments import create_and_submit

API = "/api/v1"
D = Decimal


@pytest.fixture(autouse=True)
def frozen() -> Iterator[None]:
    clock.freeze(date(2026, 11, 10))
    yield
    clock.freeze(None)


@pytest.fixture
async def books(admin, client_as: ClientFactory) -> dict:  # type: ignore[no-untyped-def]
    """October: 4,000 from Old Co. November: 10,000 from ABC (company pays a 50 fee) and a 1,200 supplier bill."""
    finance = await client_as("finance_manager")
    a = await employee("Employee A")
    abc = await customer("Customer ABC")
    old = await customer("Old Co")
    p = await project("ABC Web Platform", abc, [(a, D(100))])
    await create_and_submit(finance, await receipt_body(party_id=old, posting_date="2026-10-05", amount="4000.00"))
    await create_and_submit(
        finance,
        await receipt_body(party_id=abc, project_id=p, fee_amount="50.00", fee_paid_by="company"),
    )
    aws = await customer("AWS", kind="supplier")
    await create_and_submit(
        finance,
        {
            "posting_date": "2026-11-08",
            "direction": "pay",
            "party_id": aws,
            "amount": "1200.00",
            "method_category_id": await category_id("payment_method", "bank_transfer"),
            "purpose_category_id": await category_id("payment_purpose", "operating_expense"),
            "category_id": await category_id("expense_category", "cloud_infrastructure"),
            "paid_from_payment_account_id": await payment_account_id("Company Checking"),
        },
    )
    return {"finance": finance, "abc": abc, "old": old, "aws": aws, "project": p, "a": a}


async def test_monthly_summary_margin_fees_and_cash(books) -> None:  # type: ignore[no-untyped-def]
    m = (await books["finance"].get(f"{API}/reports/monthly-summary", params={"periods": 2})).json()
    oct_, nov = m["rows"]
    assert oct_["label"] == "Oct 2026" and not oct_["in_progress"] and nov["in_progress"]
    assert D(oct_["income"]) == 4000 and D(oct_["margin_pct"]) == 100
    assert D(nov["fees"]) == 50 and D(nov["expenses"]) == 1250
    # Cash: 4,000 in October; in November 10,000 in, 1,250 out (the 50 fee is money out, not less money in).
    assert D(oct_["cash_in"]) == 4000 and D(oct_["closing_cash"]) == 4000
    assert D(nov["cash_in"]) == 10000 and D(nov["cash_out"]) == 1250 and D(nov["closing_cash"]) == 12750
    assert D(m["totals"]["closing_cash"]) == 12750
    # periods=0: all time, from the first period on.
    everything = (await books["finance"].get(f"{API}/reports/monthly-summary", params={"periods": 0})).json()
    assert [r["label"] for r in everything["rows"]] == ["Oct 2026", "Nov 2026"]


async def test_monthly_summary_for_one_employee(books) -> None:  # type: ignore[no-untyped-def]
    finance = books["finance"]
    m = (await finance.get(f"{API}/reports/monthly-summary", params={"periods": 2, "employee_ids": books["a"]})).json()
    assert m["employee_ids"] == [books["a"]] and m["employee_names"] == ["Employee A"] and not m["unassigned"]
    oct_, nov = m["rows"]
    # Only the ABC receipt was on Employee A's project; the Old Co money in October is nobody's.
    assert D(oct_["income"]) == 0 and D(nov["income"]) > 0
    assert D(nov["profit"]) == D(nov["income"]) - D(nov["expenses"]) - D(nov["salary_calculated"])
    assert D(nov["cash_in"]) == 0 and D(nov["closing_cash"]) == 0
    perf = (await finance.get(f"{API}/reports/employee-performance")).json()
    row = next(r for r in perf["rows"] if r["employee_id"] == books["a"])
    assert D(m["totals"]["income"]) == D(row["gross_revenue"])
    assert D(m["totals"]["profit"]) == D(row["contribution"])


async def test_monthly_summary_employees_plus_unassigned_add_up(books) -> None:  # type: ignore[no-untyped-def]
    finance = books["finance"]
    url = f"{API}/reports/monthly-summary"
    company = (await finance.get(url, params={"periods": 2})).json()
    staff = [e["id"] for e in (await finance.get(f"{API}/employees", params={"limit": 200})).json()["items"]]
    both = (await finance.get(url, params={"periods": 2, "employee_ids": ",".join(staff), "unassigned": "true"})).json()
    for field in ("income", "expenses"):
        assert D(both["totals"][field]) == D(company["totals"][field]), field
    # Unassigned alone: the October receipt credited to nobody, the AWS bill and the fee.
    rest = (await finance.get(url, params={"periods": 2, "unassigned": "true"})).json()
    oct_, nov = rest["rows"]
    assert D(oct_["income"]) == 4000 and D(nov["expenses"]) == 1250 and D(nov["fees"]) == 50
    assert D(nov["salary_calculated"]) == 0 and D(nov["cash_in"]) == 0
    bad = await finance.get(url, params={"employee_ids": "not-an-id"})
    assert bad.status_code == 422


async def test_cash_flow_runway_and_fees(books) -> None:  # type: ignore[no-untyped-def]
    c = (await books["finance"].get(f"{API}/reports/cash-flow", params={"periods": 3})).json()
    # Periods exist from the first activity on: October.
    assert [p["label"] for p in c["periods"]] == ["Oct 2026", "Nov 2026"]
    nov = c["rows"][-1]
    assert D(nov["closing_market"]) == 12750 and D(nov["fees"]) == 50
    # 10,000 received less the 50 fee (an expense), 1,200 paid to AWS: income 10,000, expenses 1,250.
    assert D(nov["income"]) == 10000 and D(nov["expenses"]) == 1250 and D(nov["net"]) == 8750
    assert D(nov["owner_in"]) == 0 and D(nov["other"]) == 0
    usd = next(x for x in c["currencies"] if x["currency"] == "USD")
    assert D(usd["values"][-1]) == 12750 and D(usd["share_pct"]) == 100
    r = c["runway"]
    # The only completed period is October: 4,000 in, nothing out. Cash is growing, so there is no net runway.
    assert r["basis_periods"] == 1 and D(r["avg_in"]) == 4000 and D(r["avg_out"]) == 0
    assert r["months_net"] is None and r["months_if_no_income"] is None
    fee = c["fees_by_account"][0]
    assert fee["account_name"] == "Company Checking" and fee["paid_by"] == "company" and D(fee["amount"]) == 50

    # Owner capital is an owner flow, not income; a transfer between our own accounts is no flow at all.
    await create_and_submit(
        books["finance"],
        {
            "posting_date": "2026-11-09",
            "direction": "receive",
            "amount": "3000",
            "method_category_id": await category_id("payment_method", "bank_transfer"),
            "purpose_category_id": await category_id("payment_purpose", "owner_capital"),
            "paid_to_payment_account_id": await payment_account_id("Company Checking"),
        },
    )
    await create_and_submit(
        books["finance"],
        {
            "posting_date": "2026-11-09",
            "direction": "internal_transfer",
            "amount": "2000",
            "method_category_id": await category_id("payment_method", "bank_transfer"),
            "purpose_category_id": await category_id("payment_purpose", "internal_transfer"),
            "paid_from_payment_account_id": await payment_account_id("Company Checking"),
            "paid_to_payment_account_id": await payment_account_id("Company Savings"),
        },
    )
    nov = (await books["finance"].get(f"{API}/reports/cash-flow", params={"periods": 3})).json()["rows"][-1]
    assert D(nov["owner_in"]) == 3000 and D(nov["income"]) == 10000 and D(nov["expenses"]) == 1250
    assert D(nov["net"]) == 11750 and D(nov["closing_market"]) == 15750

    csv = await books["finance"].get(f"{API}/reports/cash-flow", params={"format": "csv"})
    assert csv.status_code == 200 and "closing (recorded)" in csv.text


async def test_customers_concentration_and_status(books) -> None:  # type: ignore[no-untyped-def]
    r = (await books["finance"].get(f"{API}/reports/customers", params={"periods": 3})).json()
    names = [x["party_name"] for x in r["rows"]]
    assert names == ["Customer ABC", "Old Co"]
    abc, old = r["rows"]
    assert abc["status"] == "new" and old["status"] == "active" and old["days_since_last"] == 36
    assert D(r["concentration"]["top1_pct"]) == D("71.4") and D(r["concentration"]["top3_pct"]) == 100
    assert [p["new_customers"] for p in r["by_period"]] == [1, 1]
    assert [p["paying_customers"] for p in r["by_period"]] == [1, 1]
    assert (await books["finance"].get(f"{API}/reports/customers", params={"format": "xlsx"})).content[:2] == b"PK"


async def test_expense_trends(books) -> None:  # type: ignore[no-untyped-def]
    t = (await books["finance"].get(f"{API}/reports/trends", params={"kind": "expense", "periods": 3})).json()
    assert t["compare"] == []  # needs two completed periods; November is still in progress
    assert {r["category_name"] for r in t["categories"]} == {"Hosting & Cloud", None}  # None: the fee
    assert D(t["totals"][-1]) == 1250
    assert t["parties"][0]["party_name"] == "AWS" and D(t["parties"][0]["total"]) == 1200
    income = (await books["finance"].get(f"{API}/reports/trends", params={"kind": "income", "periods": 3})).json()
    assert {r["party_name"] for r in income["parties"]} == {"Customer ABC", "Old Co"}


async def test_project_trend_and_hours(books, admin) -> None:  # type: ignore[no-untyped-def]
    p = books["project"]
    t = (await books["finance"].get(f"{API}/projects/{p}/financials/trend", params={"periods": 2})).json()
    assert D(t["rows"][-1]["revenue"]) == 10000 and D(t["rows"][-1]["cumulative_revenue"]) == 10000
    assert D(t["before"]["revenue"]) == 0
    fin = (await books["finance"].get(f"{API}/projects/{p}/financials")).json()
    assert fin["revenue_per_hour"] is None and fin["hours_used_pct"] is None


async def test_employee_performance(books, client_as: ClientFactory) -> None:  # type: ignore[no-untyped-def]
    perf = (await books["finance"].get(f"{API}/reports/employee-performance")).json()
    row = next(r for r in perf["rows"] if r["employee_id"] == books["a"])
    assert D(row["gross_revenue"]) > 0
    assert D(row["contribution"]) == D(row["net_revenue"]) - D(row["salary"])
    assert D(perf["totals"]["net_revenue"]) == sum(D(r["net_revenue"]) for r in perf["rows"])
    staff = await client_as("employee")
    assert (await staff.get(f"{API}/reports/cash-flow")).status_code == 403
