import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import SessionLocal
from tests.conftest import ClientFactory
from tests.factories import account_id

J = "/api/v1/journal-entries"


def idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


async def post_je(c, lines: list[tuple[str, str, str]], on: str = "2026-11-05", memo: str = "test"):  # type: ignore[no-untyped-def]
    body = {
        "posting_date": on,
        "memo": memo,
        "lines": [
            {"account_id": await account_id(code), "debit": d or "0", "credit": cr or "0"} for code, d, cr in lines
        ],
    }
    return await c.post(J, json=body, headers=idem())


async def test_default_chart_is_seeded(admin) -> None:  # type: ignore[no-untyped-def]
    accounts = (await admin.get("/api/v1/accounts")).json()
    codes = [a["code"] for a in accounts]
    assert codes[:3] == ["1000", "1100", "1110"]  # tree order: group, sub-group, leaf
    by_code = {a["code"]: a for a in accounts}
    assert by_code["1110"]["system_key"] == "default_bank" and by_code["1110"]["depth"] == 2
    assert by_code["1310"]["currency"] == "BTC"
    assert {a["root_type"] for a in accounts} == {"asset", "liability", "equity", "income", "expense"}
    pas = (await admin.get("/api/v1/payment-accounts")).json()
    assert {p["name"] for p in pas} >= {"Company Checking", "Petty Cash", "USDT Wallet", "Corporate Credit Card"}


async def test_account_rules(admin) -> None:  # type: ignore[no-untyped-def]
    bank_group, checking = await account_id("1100"), await account_id("1110")
    ok = await admin.post(
        "/api/v1/accounts", json={"code": "1130", "name": "Wise USD", "parent_id": bank_group, "account_type": "bank"}
    )
    assert ok.status_code == 201 and ok.json()["root_type"] == "asset"
    assert (
        await admin.post("/api/v1/accounts", json={"code": "1130", "name": "Dup", "parent_id": bank_group})
    ).status_code == 422
    under_leaf = await admin.post("/api/v1/accounts", json={"code": "1111", "name": "x", "parent_id": checking})
    assert under_leaf.status_code == 422
    wrong_type = await admin.post(
        "/api/v1/accounts", json={"code": "1140", "name": "x", "parent_id": bank_group, "account_type": "income"}
    )
    assert wrong_type.status_code == 422

    acc = ok.json()
    income_group = await account_id("4000")
    move = await admin.patch(
        f"/api/v1/accounts/{acc['id']}", json={"version": acc["version"], "parent_id": income_group}
    )
    assert move.status_code == 422  # can't move an asset under income
    cash_group = await account_id("1200")
    moved = await admin.patch(
        f"/api/v1/accounts/{acc['id']}", json={"version": acc["version"], "parent_id": cash_group}
    )
    assert moved.status_code == 200 and moved.json()["parent_id"] == cash_group

    system = await admin.post(f"/api/v1/accounts/{checking}/deactivate")
    assert system.status_code == 403
    pa = await admin.post("/api/v1/payment-accounts", json={"name": "Wise", "account_id": acc["id"]})
    assert pa.status_code == 201, pa.text
    assert (await admin.delete(f"/api/v1/accounts/{acc['id']}")).status_code == 409  # referenced by the payment account
    unused = (
        await admin.post(
            "/api/v1/accounts", json={"code": "1150", "name": "Unused", "parent_id": bank_group, "account_type": "bank"}
        )
    ).json()
    assert (await admin.delete(f"/api/v1/accounts/{unused['id']}")).status_code == 204


async def test_manual_journal_and_validation(admin) -> None:  # type: ignore[no-untyped-def]
    res = await post_je(admin, [("1110", "500.00", ""), ("3100", "", "500.00")])
    assert res.status_code == 201, res.text
    je = res.json()
    assert je["number"].startswith("JE-2026-") and je["total"] == "500.0000"
    assert [ln["account_code"] for ln in je["lines"]] == ["1110", "3100"]

    unbalanced = await post_je(admin, [("1110", "500.00", ""), ("3100", "", "400.00")])
    assert unbalanced.status_code == 422 and unbalanced.json()["errors"][0]["code"] == "unbalanced"
    group = await post_je(admin, [("1100", "1", ""), ("3100", "", "1")])
    assert group.status_code == 422
    both = await post_je(admin, [("1110", "1", "1"), ("3100", "", "0")])
    assert both.status_code == 422
    btc_no_amount = await post_je(admin, [("1310", "100", ""), ("3100", "", "100")])
    assert btc_no_amount.status_code == 422  # BTC account needs amount_in_currency + rate

    no_key = await admin.post(J, json={"posting_date": "2026-11-05", "lines": []})
    assert no_key.status_code == 422


async def test_crypto_line_and_base_currency_lock(admin) -> None:  # type: ignore[no-untyped-def]
    body = {
        "posting_date": "2026-11-05",
        "lines": [
            {
                "account_id": await account_id("1310"),
                "debit": "6500.00",
                "amount_in_currency": "0.1",
                "exchange_rate": "65000",
            },
            {"account_id": await account_id("3100"), "credit": "6500.00"},
        ],
    }
    res = await admin.post(J, json=body, headers=idem())
    assert res.status_code == 201, res.text
    assert res.json()["lines"][0]["amount_in_currency"] == "0.100000000000000000"

    company = (await admin.get("/api/v1/settings/company")).json()
    assert company["base_currency_locked"] is True
    change = await admin.patch("/api/v1/settings/company", json={"version": company["version"], "base_currency": "EUR"})
    assert change.status_code == 422


async def test_ledger_is_immutable_at_database_level(admin) -> None:  # type: ignore[no-untyped-def]
    je = (await post_je(admin, [("1110", "100", ""), ("3100", "", "100")])).json()
    async with SessionLocal() as s:
        with pytest.raises(DBAPIError, match="append-only"):
            await s.execute(text("UPDATE journal_lines SET debit_base = 1"))
        await s.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await s.execute(text("DELETE FROM journal_entries"))
        await s.rollback()
        with pytest.raises(DBAPIError, match="immutable"):
            await s.execute(text("UPDATE journal_entries SET memo = 'edited' WHERE id = :id"), {"id": je["id"]})
        await s.rollback()


async def test_unbalanced_entry_rejected_by_database(admin) -> None:  # type: ignore[no-untyped-def]
    await post_je(admin, [("1110", "1", ""), ("3100", "", "1")])  # makes sure a period exists
    async with SessionLocal() as s:
        period = (await s.execute(text("SELECT id FROM accounting_periods LIMIT 1"))).scalar_one()
        acc = uuid.UUID(await account_id("1110"))
        entry = uuid.uuid4()
        await s.execute(
            text(
                "INSERT INTO journal_entries (id, number, posting_date, period_id, entry_type, status, "
                "posted_at) VALUES (:id, 'JE-X', '2026-11-05', :p, 'manual', 'posted', now())"
            ),
            {"id": entry, "p": period},
        )
        await s.execute(
            text(
                "INSERT INTO journal_lines (id, journal_entry_id, line_no, account_id, debit_base, "
                "credit_base, currency, amount_in_currency, exchange_rate) VALUES "
                "(:id, :e, 1, :a, 10, 0, 'USD', 10, 1)"
            ),
            {"id": uuid.uuid4(), "e": entry, "a": acc},
        )
        with pytest.raises(DBAPIError, match="unbalanced"):
            await s.commit()


async def test_reversal(admin) -> None:  # type: ignore[no-untyped-def]
    je = (await post_je(admin, [("1110", "250", ""), ("3100", "", "250")])).json()
    rev = await admin.post(f"{J}/{je['id']}/reverse", json={"reason": "entered twice"}, headers=idem())
    assert rev.status_code == 200, rev.text
    r = rev.json()
    assert r["entry_type"] == "reversal" and r["reversal_of_id"] == je["id"] and r["posting_date"] == je["posting_date"]
    assert r["lines"][0]["credit"] == "250.0000"
    original = (await admin.get(f"{J}/{je['id']}")).json()
    assert original["status"] == "reversed" and original["reversed_by_id"] == r["id"]
    again = await admin.post(f"{J}/{je['id']}/reverse", json={"reason": "again"}, headers=idem())
    assert again.status_code == 409

    accounts = {a["code"]: a for a in (await admin.get("/api/v1/accounts")).json()}
    assert Decimal(accounts["1110"]["balance"]) == 0
    gl = (await admin.get("/api/v1/reports/general-ledger", params={"from": "2026-11-01", "to": "2026-11-30"})).json()
    assert gl["rows"] == []  # cancelled pairs hidden by default
    gl_all = (
        await admin.get(
            "/api/v1/reports/general-ledger",
            params={"from": "2026-11-01", "to": "2026-11-30", "include_reversed": True},
        )
    ).json()
    assert len(gl_all["rows"]) == 4


async def test_closed_period_blocks_posting(admin) -> None:  # type: ignore[no-untyped-def]
    past = (date.today().replace(day=1) - timedelta(days=40)).replace(day=10).isoformat()
    assert (await post_je(admin, [("1110", "1", ""), ("3100", "", "1")], on=past)).status_code == 201
    periods = (await admin.get("/api/v1/accounting-periods")).json()
    period = next(p for p in periods if p["start_date"] <= past <= p["end_date"])
    current = next(p for p in periods if p["start_date"] <= date.today().isoformat() <= p["end_date"])
    assert (await admin.post(f"/api/v1/accounting-periods/{current['id']}/close", json={})).status_code == 422
    closed = await admin.post(f"/api/v1/accounting-periods/{period['id']}/close", json={})
    assert closed.status_code == 200 and closed.json()["status"] == "closed"

    blocked = await post_je(admin, [("1110", "1", ""), ("3100", "", "1")], on=past)
    assert blocked.status_code == 422 and blocked.json()["errors"][0]["field"] == "posting_date"
    assert (await admin.post(f"/api/v1/accounting-periods/{period['id']}/reopen", json={})).status_code == 422
    reopened = await admin.post(f"/api/v1/accounting-periods/{period['id']}/reopen", json={"reason": "late bill"})
    assert reopened.json()["status"] == "open"


async def test_opening_balances_and_statements(admin) -> None:  # type: ignore[no-untyped-def]
    body = {
        "posting_date": "2026-10-31",
        "lines": [
            {"account_id": await account_id("1110"), "debit": "5000"},
            {"account_id": await account_id("1210"), "debit": "200"},
            {"account_id": await account_id("2310"), "credit": "700"},
        ],
    }
    res = await admin.post("/api/v1/opening-balances", json=body, headers=idem())
    assert res.status_code == 201, res.text
    lines = res.json()["lines"]
    assert lines[-1]["account_code"] == "3400" and lines[-1]["credit"] == "4500.0000"

    await post_je(admin, [("5200", "300", ""), ("1110", "", "300")], on="2026-11-03")
    await post_je(admin, [("1110", "1000", ""), ("4300", "", "1000")], on="2026-11-04")

    bs = (await admin.get("/api/v1/reports/balance-sheet", params={"as_of": "2026-11-30"})).json()
    assert bs["balanced"] is True
    assert bs["total_assets"] == "5900.0000"  # 5000 + 200 - 300 + 1000
    assert bs["total_liabilities"] == "700.0000"
    assert bs["unclosed_earnings"] == "700.0000" and bs["total_equity"] == "5200.0000"

    pl = (await admin.get("/api/v1/reports/profit-and-loss", params={"from": "2026-11-01", "to": "2026-11-30"})).json()
    assert pl["total_income"] == "1000.0000" and pl["total_expenses"] == "300.0000" and pl["net_profit"] == "700.0000"
    assert [r["code"] for r in pl["income"]] == ["4000", "4300"]

    tb = (await admin.get("/api/v1/reports/trial-balance", params={"from": "2026-11-01", "to": "2026-11-30"})).json()
    t = tb["totals"]
    assert t["debit"] == t["credit"] and t["opening_debit"] == t["opening_credit"]
    assert t["closing_debit"] == t["closing_credit"]
    checking = next(r for r in tb["rows"] if r["code"] == "1110")
    assert checking["opening_debit"] == "5000.0000" and checking["closing_debit"] == "5700.0000"

    gl = (
        await admin.get(
            "/api/v1/reports/general-ledger",
            params={"from": "2026-11-01", "to": "2026-11-30", "account_id": await account_id("1110")},
        )
    ).json()
    assert gl["opening_balance"] == "5000.0000" and gl["closing_balance"] == "5700.0000"
    assert [r["balance"] for r in gl["rows"]] == ["4700.0000", "5700.0000"]

    csv = await admin.get(
        "/api/v1/reports/trial-balance", params={"from": "2026-11-01", "to": "2026-11-30", "format": "csv"}
    )
    assert csv.headers["content-type"].startswith("text/csv") and "1110" in csv.text


async def test_deactivate_needs_zero_balance(admin) -> None:  # type: ignore[no-untyped-def]
    await post_je(admin, [("1120", "10", ""), ("3100", "", "10")])
    assert (await admin.post(f"/api/v1/accounts/{await account_id('1120')}/deactivate")).status_code == 409
    marketing = await account_id("5400")
    assert (await admin.post(f"/api/v1/accounts/{marketing}/deactivate")).status_code == 200
    assert (await post_je(admin, [("5400", "1", ""), ("1110", "", "1")])).status_code == 422


@pytest.mark.parametrize("role", ["project_manager", "employee"])
async def test_accounting_permissions(client_as: ClientFactory, role: str) -> None:
    c = await client_as(role)
    assert (await c.get("/api/v1/accounts")).status_code == 403
    assert (
        await c.get("/api/v1/reports/trial-balance", params={"from": "2026-01-01", "to": "2026-12-31"})
    ).status_code == 403
    fm = await client_as("finance_manager")
    assert (await fm.get("/api/v1/accounts")).status_code == 200
    assert (await post_je(fm, [("1110", "1", ""), ("3100", "", "1")])).status_code == 201
