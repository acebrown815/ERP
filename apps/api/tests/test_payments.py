import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tests.conftest import ClientFactory
from tests.factories import account_id, category_id, customer, employee, payment_account_id, project, receipt_body

PE = "/api/v1/payment-entries"
D = Decimal


def idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


async def create_and_submit(c, body: dict) -> dict:  # type: ignore[no-untyped-def]
    created = await c.post(PE, json=body)
    assert created.status_code == 201, created.text
    submitted = await c.post(f"{PE}/{created.json()['id']}/submit", headers=idem())
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


async def balances(c) -> dict[str, D]:  # type: ignore[no-untyped-def]
    return {a["code"]: D(a["balance"]) for a in (await c.get("/api/v1/accounts")).json()}


@pytest.fixture
async def scenario() -> dict[str, str]:
    """Customer ABC, project P-0001 with Employee A 60% / Employee B 40% (docs/architecture.md, Section 16)."""
    abc = await customer("Customer ABC")
    a = await employee("Employee A")
    b = await employee("Employee B")
    p = await project("ABC Web Platform", abc, [(a, D(60)), (b, D(40))])
    return {"customer": abc, "a": a, "b": b, "project": p}


async def test_reference_scenario_receipt(admin, scenario) -> None:  # type: ignore[no-untyped-def]
    body = await receipt_body(party_id=scenario["customer"], project_id=scenario["project"], reference_no="WIRE-881")

    preview = (await admin.post(f"{PE}/preview", json=body)).json()
    assert preview["ok"] is True, preview
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in preview["lines"]] == [
        ("1110", "10000.00", "0.00"),
        ("4100", "0.00", "10000.00"),
    ]
    # No split sent: the preview uses the project's default (60/40), like a new draft does.
    assert {a["employee_name"]: a["amount"] for a in preview["allocations"]} == {
        "Employee A": "6000.00",
        "Employee B": "4000.00",
    }
    assert preview["eligible_amount_base"] == "10000.00"

    created = await admin.post(PE, json=body)
    assert created.status_code == 201
    draft = created.json()
    # The split is pre-filled from the project's default (60/40).
    assert sorted((a["employee_name"], a["percent"]) for a in draft["allocations"]) == [
        ("Employee A", "60.0000"),
        ("Employee B", "40.0000"),
    ]
    assert draft["status"] == "draft" and draft["number"].startswith("PE-2026-")

    saved_preview = (await admin.get(f"{PE}/{draft['id']}/preview")).json()
    assert saved_preview["ok"] and saved_preview["allocated_total"] == "10000.00"

    submitted = (await admin.post(f"{PE}/{draft['id']}/submit", headers=idem())).json()
    assert submitted["status"] == "submitted" and submitted["base_amount"] == "10000.0000"
    assert {a["employee_name"]: a["amount"] for a in submitted["allocations"]} == {
        "Employee A": "6000.0000",
        "Employee B": "4000.0000",
    }
    assert all(a["status"] == "active" for a in submitted["allocations"])

    b = await balances(admin)
    assert b["1110"] == D(10000) and b["4100"] == D(10000)
    pl = (await admin.get("/api/v1/reports/profit-and-loss", params={"from": "2026-11-01", "to": "2026-11-30"})).json()
    assert pl["net_profit"] == "10000.0000"
    project_pl = (
        await admin.get(
            "/api/v1/reports/profit-and-loss",
            params={"from": "2026-11-01", "to": "2026-11-30", "project_id": scenario["project"]},
        )
    ).json()
    assert project_pl["total_income"] == "10000.0000"
    bs = (await admin.get("/api/v1/reports/balance-sheet", params={"as_of": "2026-11-30"})).json()
    assert bs["balanced"] and bs["total_assets"] == "10000.0000"

    je = (await admin.get(f"/api/v1/journal-entries/{submitted['journal_entry_id']}")).json()
    assert je["source_number"] == submitted["number"]
    assert je["lines"][1]["party_name"] == "Customer ABC" and je["lines"][1]["project_name"] == "ABC Web Platform"

    summary = (await admin.get(f"{PE}/party-summary", params={"party_id": scenario["customer"]})).json()
    assert summary["received"] == "10000.0000"


async def test_split_must_cover_exactly_100_percent(admin, scenario) -> None:  # type: ignore[no-untyped-def]
    body = await receipt_body(
        party_id=scenario["customer"],
        allocations=[{"employee_id": scenario["a"], "percent": "50"}, {"employee_id": scenario["b"], "percent": "40"}],
    )
    pe = (await admin.post(PE, json=body)).json()
    res = await admin.post(f"{PE}/{pe['id']}/submit", headers=idem())
    assert res.status_code == 422 and res.json()["errors"][0]["code"] == "incomplete"

    # No split at all is allowed: the revenue simply counts toward nobody's salary.
    unsplit = await receipt_body(party_id=scenario["customer"])
    preview = (await admin.post(f"{PE}/preview", json=unsplit)).json()
    assert preview["ok"] is True and preview["allocations"] == []
    assert any("won't count toward anyone's salary" in w for w in preview["warnings"])
    none = (await admin.post(PE, json=unsplit)).json()
    res = await admin.post(f"{PE}/{none['id']}/submit", headers=idem())
    assert res.status_code == 200 and res.json()["allocations"] == []

    over = await admin.post(
        PE,
        json=await receipt_body(
            party_id=scenario["customer"],
            allocations=[
                {"employee_id": scenario["a"], "percent": "70"},
                {"employee_id": scenario["b"], "percent": "40"},
            ],
        ),
    )
    assert over.status_code == 422

    mixed = await admin.post(
        PE,
        json=await receipt_body(
            party_id=scenario["customer"],
            allocations=[
                {"employee_id": scenario["a"], "percent": "60"},
                {"employee_id": scenario["b"], "amount": "4000"},
            ],
        ),
    )
    assert mixed.status_code == 422

    amounts = await receipt_body(
        party_id=scenario["customer"],
        allocations=[
            {"employee_id": scenario["a"], "amount": "7000"},
            {"employee_id": scenario["b"], "amount": "3000"},
        ],
    )
    done = await create_and_submit(admin, amounts)
    assert {a["amount"] for a in done["allocations"]} == {"7000.0000", "3000.0000"}


async def test_three_way_split_rounds_exactly(admin, scenario) -> None:  # type: ignore[no-untyped-def]
    c = await employee("Employee C")
    body = await receipt_body(
        party_id=scenario["customer"],
        amount="100.00",
        allocations=[
            {"employee_id": scenario["a"], "percent": "33.3333"},
            {"employee_id": scenario["b"], "percent": "33.3333"},
            {"employee_id": c, "percent": "33.3334"},
        ],
    )
    done = await create_and_submit(admin, body)
    assert sum(D(a["amount"]) for a in done["allocations"]) == D("100.00")


@pytest.mark.parametrize(
    ("paid_by", "bank", "fees", "eligible"),
    [
        ("company", "9970.00", "30.00", "9970.0000"),
        ("client", "10000.00", None, "10000.0000"),
    ],
)
async def test_processor_fee(admin, scenario, paid_by, bank, fees, eligible) -> None:  # type: ignore[no-untyped-def]
    body = await receipt_body(
        party_id=scenario["customer"], project_id=scenario["project"], fee_amount="30.00", fee_paid_by=paid_by
    )
    preview = (await admin.post(f"{PE}/preview", json=body)).json()
    lines = {ln["account_code"]: ln for ln in preview["lines"]}
    assert lines["1110"]["debit"] == bank and lines["4100"]["credit"] == "10000.00"
    assert (lines.get("5600") or {}).get("debit") == fees
    done = await create_and_submit(admin, body)
    assert D(done["eligible_amount_base"]) == D(eligible)
    assert sum(D(a["amount"]) for a in done["allocations"]) == D(eligible)


async def test_operating_expense_and_category_default_account(admin) -> None:  # type: ignore[no-untyped-def]
    aws = await customer("AWS", kind="supplier")
    body = {
        "posting_date": "2026-11-12",
        "direction": "pay",
        "party_id": aws,
        "amount": "420.50",
        "method_category_id": await category_id("payment_method", "credit_card"),
        "purpose_category_id": await category_id("payment_purpose", "operating_expense"),
        "paid_from_payment_account_id": await payment_account_id("Corporate Credit Card"),
    }
    missing = (await admin.post(f"{PE}/preview", json=body)).json()
    assert missing["ok"] is False and missing["errors"][0]["field"] == "counter_account_id"

    body["category_id"] = await category_id("expense_category", "cloud_infrastructure")
    done = await create_and_submit(admin, body)
    assert done["status"] == "submitted"
    b = await balances(admin)
    assert b["5200"] == D("420.50") and b["2310"] == D("420.50")  # card liability grew


async def test_other_expense_requires_description_and_account(admin) -> None:  # type: ignore[no-untyped-def]
    body = {
        "posting_date": "2026-11-12",
        "direction": "pay",
        "amount": "80",
        "method_category_id": await category_id("payment_method", "other"),
        "purpose_category_id": await category_id("payment_purpose", "operating_expense"),
        "category_id": await category_id("expense_category", "other"),
        "paid_from_payment_account_id": await payment_account_id("Petty Cash"),
    }
    preview = (await admin.post(f"{PE}/preview", json=body)).json()
    fields = {e["field"] for e in preview["errors"]}
    assert {"method_other_text", "category_other_text"} <= fields

    body.update(method_other_text="Wise card", category_other_text="Business travel")
    method_cfg = (await admin.post(f"{PE}/preview", json=body)).json()
    assert method_cfg["ok"] is True, method_cfg  # "Other" expense defaults to 5990
    assert method_cfg["lines"][0]["account_code"] == "5990"


async def test_salary_payment_requires_employee(admin, scenario) -> None:  # type: ignore[no-untyped-def]
    body = {
        "posting_date": "2026-11-28",
        "direction": "pay",
        "amount": "626.67",
        "method_category_id": await category_id("payment_method", "bank_transfer"),
        "purpose_category_id": await category_id("payment_purpose", "employee_salary"),
        "paid_from_payment_account_id": await payment_account_id("Company Checking"),
        "party_id": scenario["customer"],
    }
    wrong = (await admin.post(f"{PE}/preview", json=body)).json()
    assert wrong["ok"] is False and wrong["errors"][0]["field"] == "party_id"

    emp = (await admin.get(f"/api/v1/employees/{scenario['a']}")).json()
    body["party_id"] = emp["party_id"]
    await create_and_submit(
        admin, {**await receipt_body(party_id=scenario["customer"], project_id=scenario["project"])}
    )
    done = await create_and_submit(admin, body)
    assert done["employee_id"] == scenario["a"]
    gl = (
        await admin.get(
            "/api/v1/reports/general-ledger",
            params={"from": "2026-11-01", "to": "2026-11-30", "employee_id": scenario["a"]},
        )
    ).json()
    assert [r["account_code"] for r in gl["rows"]] == ["5100", "1110"]


async def test_internal_transfer_has_no_pl_effect(admin) -> None:  # type: ignore[no-untyped-def]
    await create_and_submit(
        admin,
        {
            "posting_date": "2026-11-01",
            "direction": "receive",
            "amount": "5000",
            "method_category_id": await category_id("payment_method", "bank_transfer"),
            "purpose_category_id": await category_id("payment_purpose", "owner_capital"),
            "paid_to_payment_account_id": await payment_account_id("Company Checking"),
        },
    )
    transfer = {
        "posting_date": "2026-11-02",
        "direction": "internal_transfer",
        "amount": "1500",
        "method_category_id": await category_id("payment_method", "bank_transfer"),
        "purpose_category_id": await category_id("payment_purpose", "internal_transfer"),
        "paid_from_payment_account_id": await payment_account_id("Company Checking"),
        "paid_to_payment_account_id": await payment_account_id("Company Savings"),
    }
    await create_and_submit(admin, transfer)
    b = await balances(admin)
    assert b["1110"] == D(3500) and b["1120"] == D(1500) and b["3100"] == D(5000)
    pl = (await admin.get("/api/v1/reports/profit-and-loss", params={"from": "2026-11-01", "to": "2026-11-30"})).json()
    assert pl["net_profit"] == "0"

    bad = (
        await admin.post(
            f"{PE}/preview", json={**transfer, "paid_to_payment_account_id": transfer["paid_from_payment_account_id"]}
        )
    ).json()
    assert bad["ok"] is False
    wrong_purpose = (
        await admin.post(
            f"{PE}/preview",
            json={**transfer, "purpose_category_id": await category_id("payment_purpose", "operating_expense")},
        )
    ).json()
    assert wrong_purpose["ok"] is False


async def test_crypto_receipt_and_conversion_with_fx_gain(admin, scenario) -> None:  # type: ignore[no-untyped-def]
    usdt = await payment_account_id("USDT Wallet")
    receipt = await receipt_body(
        party_id=scenario["customer"],
        project_id=scenario["project"],
        amount="1000.000000",
        paid_to_payment_account_id=usdt,
        exchange_rate="0.999",
        method_category_id=await category_id("payment_method", "crypto_transfer"),
    )
    explicit_one = (await admin.post(f"{PE}/preview", json={**receipt, "exchange_rate": "1"})).json()
    assert explicit_one["ok"] is True  # 1 typed on the entry is an explicit rate; accepted
    done = await create_and_submit(admin, receipt)
    assert done["currency"] == "USDT" and done["base_amount"] == "999.0000"
    assert {a["amount"] for a in done["allocations"]} == {"599.4000", "399.6000"}

    bank_method = await admin.post(
        f"{PE}/preview", json={**receipt, "method_category_id": await category_id("payment_method", "bank_transfer")}
    )
    assert bank_method.json()["ok"] is False  # bank transfer can't land in a crypto wallet

    convert = {
        "posting_date": "2026-11-15",
        "direction": "internal_transfer",
        "amount": "1000",
        "exchange_rate": "1.001",
        "received_amount": "998.50",
        "method_category_id": await category_id("payment_method", "crypto_transfer"),
        "purpose_category_id": await category_id("payment_purpose", "internal_transfer"),
        "paid_from_payment_account_id": usdt,
        "paid_to_payment_account_id": await payment_account_id("Company Checking"),
    }
    preview = (await admin.post(f"{PE}/preview", json=convert)).json()
    lines = {ln["account_code"]: ln for ln in preview["lines"]}
    # The USDT leaves at its carrying cost (received at 0.999 -> $999), not today's 1.001; the gap to the
    # $998.50 that arrived is a realized loss of $0.50.
    assert lines["1320"]["credit"] == "999.00" and lines["1110"]["debit"] == "998.50"
    assert lines["4950"]["debit"] == "0.50"
    await create_and_submit(admin, convert)
    accounts = {a["code"]: a for a in (await admin.get("/api/v1/accounts")).json()}
    assert D(accounts["1320"]["balance"]) == 0  # no units left and no value left
    assert D(accounts["4950"]["balance"]) == D("-0.50")  # income account: a loss shows negative


async def test_category_required_fields_are_enforced(admin) -> None:  # type: ignore[no-untyped-def]
    travel = (
        await admin.post(
            "/api/v1/categories",
            json={
                "group_key": "expense_category",
                "name": "Travel",
                "config": {"required_fields": ["reference_no", "description"]},
            },
        )
    ).json()
    body = {
        "posting_date": "2026-11-12",
        "direction": "pay",
        "amount": "250",
        "method_category_id": await category_id("payment_method", "bank_transfer"),
        "purpose_category_id": await category_id("payment_purpose", "operating_expense"),
        "category_id": travel["id"],
        "counter_account_id": await account_id("5990"),
        "paid_from_payment_account_id": await payment_account_id("Company Checking"),
    }
    missing = (await admin.post(f"{PE}/preview", json=body)).json()
    assert missing["ok"] is False
    assert {e["field"] for e in missing["errors"]} == {"reference_no", "description"}
    done = (
        await admin.post(f"{PE}/preview", json={**body, "reference_no": "TRIP-7", "description": "Client visit"})
    ).json()
    assert done["ok"] is True, done


async def test_saved_rate_is_used_when_the_entry_has_none(admin, scenario) -> None:  # type: ignore[no-untyped-def]
    usdt = await payment_account_id("USDT Wallet")
    receipt = await receipt_body(
        party_id=scenario["customer"],
        project_id=scenario["project"],
        amount="1000",
        paid_to_payment_account_id=usdt,
        method_category_id=await category_id("payment_method", "crypto_transfer"),
    )
    # No rate typed and none saved: never silently 1.0.
    missing = (await admin.post(f"{PE}/preview", json=receipt)).json()
    assert missing["ok"] is False and missing["errors"][0]["field"] == "exchange_rate"
    assert "Currencies & Rates" in missing["errors"][0]["message"]

    saved = await admin.put(
        "/api/v1/exchange-rates",
        json={"from_currency": "USDT", "to_currency": "USD", "rate_date": "2026-11-01", "rate": "0.95"},
    )
    assert saved.status_code == 200
    preview = (await admin.post(f"{PE}/preview", json=receipt)).json()
    assert preview["ok"] is True and preview["base_amount"] == "950.00" and D(preview["exchange_rate"]) == D("0.95")
    assert any("saved USDT→USD rate 0.95" in w for w in preview["warnings"])

    draft = (await admin.post(PE, json=receipt)).json()
    assert draft["exchange_rate"] is None
    done = (await admin.post(f"{PE}/{draft['id']}/submit", headers=idem())).json()
    assert D(done["exchange_rate"]) == D("0.95") and done["base_amount"] == "950.0000"  # frozen on submit
    # A later rate doesn't change a submitted payment, but does change the market value.
    await admin.put(
        "/api/v1/exchange-rates",
        json={"from_currency": "USDT", "to_currency": "USD", "rate_date": "2026-11-20", "rate": "0.90"},
    )
    again = (await admin.get(f"{PE}/{done['id']}")).json()
    assert again["base_amount"] == "950.0000"
    # USDT is in the ledger now: its decimals can grow but not shrink.
    assert (await admin.patch("/api/v1/currencies/USDT", json={"precision": 2})).status_code == 422
    assert (await admin.patch("/api/v1/currencies/USDT", json={"precision": 8})).status_code == 200

    holdings = (await admin.get("/api/v1/reports/holdings", params={"as_of": "2026-11-25"})).json()
    usdt_row = next(c for c in holdings["currencies"] if c["currency"] == "USDT")
    assert D(usdt_row["units"]) == 1000 and D(usdt_row["book_value"]) == 950
    assert D(usdt_row["market_value"]) == 900 and D(usdt_row["rate"]) == D("0.90")
    assert holdings["currencies"][0]["currency"] == "USD"  # base currency first
    assert D(holdings["book_total"]) == 950 and D(holdings["market_total"]) == 900
    btc = next(c for c in holdings["currencies"] if c["currency"] == "BTC")
    assert btc["market_value"] is None  # no saved BTC rate
    assert holdings["missing_rates"] == []  # ...but no BTC held either
    csv = await admin.get("/api/v1/reports/holdings", params={"as_of": "2026-11-25", "format": "csv"})
    assert csv.status_code == 200 and "USDT" in csv.text

    # Chart of accounts: the wallet in USDT and at the saved rate; groups roll up the value at today's rates.
    accounts = {x["code"]: x for x in (await admin.get("/api/v1/accounts", params={"as_of": "2026-11-25"})).json()}
    wallet = accounts["1320"]
    assert D(wallet["balance"]) == 950 and D(wallet["balance_in_currency"]) == 1000
    assert D(wallet["rate"]) == D("0.90") and D(wallet["value_at_rate"]) == 900
    assert D(accounts["1300"]["balance"]) == 950 and D(accounts["1300"]["value_at_rate"]) == 900
    assert accounts["1110"]["balance_in_currency"] is None and accounts["1110"]["value_at_rate"] is None


async def test_cancel_and_amend(admin, scenario) -> None:  # type: ignore[no-untyped-def]
    body = await receipt_body(party_id=scenario["customer"], project_id=scenario["project"])
    done = await create_and_submit(admin, body)
    assert (
        await admin.patch(f"{PE}/{done['id']}", json={"version": done["version"], "amount": "1"})
    ).status_code == 409
    assert (await admin.post(f"{PE}/{done['id']}/cancel", json={"reason": "x"}, headers=idem())).status_code == 422

    cancelled = await admin.post(
        f"{PE}/{done['id']}/cancel", json={"reason": "Client paid the wrong amount"}, headers=idem()
    )
    assert cancelled.status_code == 200, cancelled.text
    c = cancelled.json()
    assert c["status"] == "cancelled" and all(a["status"] == "cancelled" for a in c["allocations"])
    reversal = (await admin.get(f"/api/v1/journal-entries/{c['reversal_journal_entry_id']}")).json()
    assert reversal["posting_date"] == done["posting_date"] and reversal["entry_type"] == "reversal"
    assert (await balances(admin))["1110"] == 0
    assert (await admin.post(f"{PE}/{done['id']}/cancel", json={"reason": "again"}, headers=idem())).status_code == 409

    amended = await admin.post(f"{PE}/{done['id']}/amend")
    assert amended.status_code == 201
    a = amended.json()
    assert a["status"] == "draft" and a["amended_from_id"] == done["id"] and a["number"] != done["number"]
    assert len(a["allocations"]) == 2 and all(x["status"] == "draft" for x in a["allocations"])
    upd = await admin.patch(f"{PE}/{a['id']}", json={"version": a["version"], "amount": "9500.00"})
    assert upd.status_code == 200
    final = (await admin.post(f"{PE}/{a['id']}/submit", headers=idem())).json()
    assert {x["amount"] for x in final["allocations"]} == {"5700.0000", "3800.0000"}
    assert (await admin.post(f"{PE}/{done['id']}/amend")).status_code == 409  # only one amendment


async def test_submit_is_idempotent(admin, scenario) -> None:  # type: ignore[no-untyped-def]
    pe = (
        await admin.post(PE, json=await receipt_body(party_id=scenario["customer"], project_id=scenario["project"]))
    ).json()
    key = {"Idempotency-Key": "submit-once"}
    first = await admin.post(f"{PE}/{pe['id']}/submit", headers=key)
    second = await admin.post(f"{PE}/{pe['id']}/submit", headers=key)
    assert first.status_code == second.status_code == 200
    assert second.headers.get("idempotent-replayed") == "true"
    assert first.json()["journal_entry_id"] == second.json()["journal_entry_id"]
    without = await admin.post(f"{PE}/{pe['id']}/submit")
    assert without.status_code == 422  # header required on submit
    entries = (await admin.get("/api/v1/journal-entries", params={"entry_type": "payment"})).json()
    assert entries["total"] == 1


async def test_duplicate_warning_and_closed_period(admin, scenario) -> None:  # type: ignore[no-untyped-def]
    past = (date.today().replace(day=1) - timedelta(days=40)).replace(day=10).isoformat()
    body = await receipt_body(party_id=scenario["customer"], project_id=scenario["project"], posting_date=past)
    done = await create_and_submit(admin, body)
    preview = (await admin.post(f"{PE}/preview", json=body)).json()
    assert any("duplicate" in w for w in preview["warnings"])

    periods = (await admin.get("/api/v1/accounting-periods")).json()
    period = next(p for p in periods if p["start_date"] <= past <= p["end_date"])
    await admin.post(f"/api/v1/accounting-periods/{period['id']}/close", json={})
    blocked = await admin.post(f"{PE}/{done['id']}/cancel", json={"reason": "late correction"}, headers=idem())
    assert blocked.status_code == 422
    draft = (await admin.post(PE, json=body)).json()
    assert (await admin.post(f"{PE}/{draft['id']}/submit", headers=idem())).status_code == 422


async def test_drafts_and_permissions(admin, client_as: ClientFactory, scenario) -> None:  # type: ignore[no-untyped-def]
    draft = (
        await admin.post(
            PE,
            json={
                "posting_date": "2026-11-10",
                "direction": "receive",
                "amount": "5",
                "paid_to_payment_account_id": await payment_account_id("Petty Cash"),
            },
        )
    ).json()
    assert draft["status"] == "draft" and draft["currency"] == "USD"
    incomplete = await admin.post(f"{PE}/{draft['id']}/submit", headers=idem())
    assert {"method_category_id", "purpose_category_id"} <= {e["field"] for e in incomplete.json()["errors"]}
    assert (await admin.delete(f"{PE}/{draft['id']}")).status_code == 204

    for role in ("project_manager", "employee"):
        c = await client_as(role)
        assert (await c.get(PE)).status_code == 403
        assert (await c.post(PE, json=await receipt_body())).status_code == 403
    fm = await client_as("finance_manager")
    done = await create_and_submit(
        fm, await receipt_body(party_id=scenario["customer"], project_id=scenario["project"])
    )
    listed = (await fm.get(PE, params={"party_id": scenario["customer"], "status": "submitted"})).json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == done["id"]
    csv = await fm.get(PE, params={"format": "csv"})
    assert done["number"] in csv.text


async def test_payment_accounts(admin, client_as: ClientFactory) -> None:  # type: ignore[no-untyped-def]
    res = await admin.post(
        "/api/v1/payment-accounts", json={"name": "Checking (dup)", "account_id": await account_id("1110")}
    )
    assert res.status_code == 422  # one payment account per ledger account
    res = await admin.post(
        "/api/v1/payment-accounts", json={"name": "Revenue?", "account_id": await account_id("4100")}
    )
    assert res.status_code == 422  # must be a money account
    checking = await payment_account_id("Company Checking")
    pa = next(p for p in (await admin.get("/api/v1/payment-accounts")).json() if p["id"] == checking)
    upd = await admin.patch(
        f"/api/v1/payment-accounts/{checking}",
        json={"version": pa["version"], "details": {"iban": "DE89370400440532013000"}},
    )
    assert upd.json()["details"]["iban"] == "DE89370400440532013000"
    fm = await client_as("project_manager")
    assert (await fm.get("/api/v1/payment-accounts")).status_code == 403
    finance = await client_as("finance_manager")
    shown = next(p for p in (await finance.get("/api/v1/payment-accounts")).json() if p["id"] == checking)
    assert shown["details"]["iban"] == "DE89370400440532013000"  # finance manages payment accounts
