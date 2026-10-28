import io

from app.core.config import get_settings
from tests.conftest import ClientFactory


async def test_company_settings_update_and_audit(admin) -> None:  # type: ignore[no-untyped-def]
    company = (await admin.get("/api/v1/settings/company")).json()
    assert company["base_currency"] == "USD" and company["salary_cycle_start_day"] == 1
    assert company["policies"]["eligible_revenue_basis"] == "net_of_company_fees"

    res = await admin.patch(
        "/api/v1/settings/company",
        json={
            "version": company["version"],
            "name": "Acme Software",
            "timezone": "America/Chicago",
        },
    )
    assert res.status_code == 200, res.text

    stale = await admin.patch("/api/v1/settings/company", json={"version": company["version"], "name": "X"})
    assert stale.status_code == 412

    logs = (await admin.get("/api/v1/audit-logs", params={"action": "company_settings.updated"})).json()
    assert logs["items"][0]["after"] == {
        "name": "Acme Software",
        "timezone": "America/Chicago",
    }


async def test_company_settings_validation(admin) -> None:  # type: ignore[no-untyped-def]
    v = (await admin.get("/api/v1/settings/company")).json()["version"]
    assert (
        await admin.patch("/api/v1/settings/company", json={"version": v, "timezone": "Mars/Base"})
    ).status_code == 422
    # The salary cycle is changed through /settings/salary-cycle, which previews the transition.
    assert (
        await admin.patch("/api/v1/settings/company", json={"version": v, "salary_cycle_start_day": 25})
    ).status_code == 422
    assert (
        await admin.patch("/api/v1/settings/company", json={"version": v, "base_currency": "BTC"})
    ).status_code == 422
    bad_policy = await admin.patch(
        "/api/v1/settings/company", json={"version": v, "policies": {"eligible_revenue_basis": "whatever"}}
    )
    assert bad_policy.status_code == 422


async def test_only_admin_edits_company_settings(client_as: ClientFactory) -> None:
    fm = await client_as("finance_manager")
    company = (await fm.get("/api/v1/settings/company")).json()
    assert (
        await fm.patch("/api/v1/settings/company", json={"version": company["version"], "name": "X"})
    ).status_code == 403


async def test_currencies(admin, client_as: ClientFactory) -> None:  # type: ignore[no-untyped-def]
    codes = {c["code"] for c in (await admin.get("/api/v1/currencies")).json()}
    assert {"USD", "EUR", "BTC", "USDT"} <= codes

    created = await admin.post(
        "/api/v1/currencies", json={"code": "sol", "name": "Solana", "precision": 9, "is_crypto": True}
    )
    assert created.status_code == 201 and created.json()["code"] == "SOL"
    assert (
        await admin.post("/api/v1/currencies", json={"code": "SOL", "name": "x", "precision": 2})
    ).status_code == 409
    assert (await admin.patch("/api/v1/currencies/USD", json={"is_active": False})).status_code == 422
    edited = await admin.patch("/api/v1/currencies/SOL", json={"name": "Solana (SOL)", "symbol": "◎", "precision": 6})
    assert edited.status_code == 200 and edited.json()["precision"] == 6  # unused: decimals may go down

    employee = await client_as("employee")
    assert (await employee.get("/api/v1/currencies")).status_code == 200
    assert (
        await employee.post("/api/v1/currencies", json={"code": "XYZ", "name": "x", "precision": 2})
    ).status_code == 403


async def test_exchange_rates_lookup(admin) -> None:  # type: ignore[no-untyped-def]
    put = await admin.put(
        "/api/v1/exchange-rates",
        json={"from_currency": "EUR", "to_currency": "USD", "rate_date": "2026-11-01", "rate": "1.0850"},
    )
    assert put.status_code == 200
    # Upsert on the same day replaces the rate.
    await admin.put(
        "/api/v1/exchange-rates",
        json={"from_currency": "EUR", "to_currency": "USD", "rate_date": "2026-11-01", "rate": "1.0900"},
    )
    rates = (await admin.get("/api/v1/exchange-rates", params={"currency": "EUR"})).json()
    assert rates["total"] == 1 and rates["items"][0]["rate"] == "1.090000000000"

    direct = (
        await admin.get("/api/v1/exchange-rates/lookup", params={"from": "EUR", "to": "USD", "on": "2026-11-10"})
    ).json()
    assert direct["method"] == "direct" and direct["rate"] == "1.090000000000"

    inverse = (
        await admin.get("/api/v1/exchange-rates/lookup", params={"from": "USD", "to": "EUR", "on": "2026-11-10"})
    ).json()
    assert inverse["method"] == "inverse" and inverse["rate"] == "0.917431192661"

    missing = await admin.get("/api/v1/exchange-rates/lookup", params={"from": "EUR", "to": "USD", "on": "2026-10-31"})
    assert missing.status_code == 404

    same = await admin.get("/api/v1/exchange-rates/lookup", params={"from": "USD", "to": "USD", "on": "2026-01-01"})
    assert same.json()["rate"] == "1"

    assert (
        await admin.put(
            "/api/v1/exchange-rates",
            json={"from_currency": "EUR", "to_currency": "USD", "rate_date": "2026-11-01", "rate": "0"},
        )
    ).status_code == 422


async def test_attachments(admin, client_as: ClientFactory) -> None:  # type: ignore[no-untyped-def]
    company = (await admin.get("/api/v1/settings/company")).json()
    form = {"entity_type": "company_settings", "entity_id": company["id"]}

    up = await admin.post(
        "/api/v1/attachments",
        data=form,
        files={"file": ("../../evil name.pdf", io.BytesIO(b"%PDF-1.4 hello"), "application/pdf")},
    )
    assert up.status_code == 201, up.text
    att = up.json()
    assert att["filename"] == "evil name.pdf" and att["size"] == 14 and len(att["sha256"]) == 64

    dl = await admin.get(f"/api/v1/attachments/{att['id']}/download")
    assert dl.status_code == 200 and dl.content == b"%PDF-1.4 hello"

    exe = await admin.post(
        "/api/v1/attachments", data=form, files={"file": ("run.exe", io.BytesIO(b"MZ"), "application/octet-stream")}
    )
    assert exe.status_code == 422

    settings = get_settings()
    original = settings.attachments_max_bytes
    settings.attachments_max_bytes = 10
    try:
        big = await admin.post(
            "/api/v1/attachments", data=form, files={"file": ("big.txt", io.BytesIO(b"x" * 11), "text/plain")}
        )
        assert big.status_code == 422
    finally:
        settings.attachments_max_bytes = original

    employee = await client_as("employee")
    assert (await employee.get("/api/v1/attachments", params=form)).status_code == 200
    denied = await employee.post(
        "/api/v1/attachments", data=form, files={"file": ("a.txt", io.BytesIO(b"hi"), "text/plain")}
    )
    assert denied.status_code == 403
    assert (await employee.delete(f"/api/v1/attachments/{att['id']}")).status_code == 403

    assert (await admin.delete(f"/api/v1/attachments/{att['id']}")).status_code == 204
    assert (await admin.get(f"/api/v1/attachments/{att['id']}/download")).status_code == 404
    unknown = await admin.post(
        "/api/v1/attachments",
        data={"entity_type": "nope", "entity_id": "1"},
        files={"file": ("a.txt", io.BytesIO(b"hi"), "text/plain")},
    )
    assert unknown.status_code == 422
