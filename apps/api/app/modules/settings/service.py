import uuid
from datetime import date
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.errors import Conflict, NotFound, PreconditionFailed, ValidationFailed, field_error
from app.modules.audit import api as audit
from app.modules.settings.models import CompanySettings, Currency, ExchangeRate

DEFAULT_CURRENCIES: list[tuple[str, str, str | None, int, bool]] = [
    # code, name, symbol, precision, is_crypto
    ("USD", "US Dollar", "$", 2, False),
    ("EUR", "Euro", "€", 2, False),
    ("GBP", "British Pound", "£", 2, False),
    ("CAD", "Canadian Dollar", "CA$", 2, False),
    ("AUD", "Australian Dollar", "A$", 2, False),
    ("JPY", "Japanese Yen", "¥", 0, False),
    ("CNY", "Chinese Yuan", "CN¥", 2, False),
    ("INR", "Indian Rupee", "₹", 2, False),
    ("BTC", "Bitcoin", "₿", 8, True),
    ("ETH", "Ether", "Ξ", 18, True),
    ("USDT", "Tether USD", None, 6, True),
    ("USDC", "USD Coin", None, 6, True),
]

DEFAULT_POLICIES: dict[str, Any] = {
    # F4 in docs/architecture.md: company-paid processor fees reduce attributable revenue.
    "eligible_revenue_basis": "net_of_company_fees",
}

POLICY_VALUES: dict[str, set[str]] = {
    "eligible_revenue_basis": {"gross", "net_of_company_fees"},
}

RATE_PLACES = Decimal("0.000000000001")


def _company_snapshot(c: CompanySettings) -> dict[str, Any]:
    return {
        "name": c.name,
        "legal_name": c.legal_name,
        "email": c.email,
        "phone": c.phone,
        "website": c.website,
        "address": c.address,
        "base_currency": c.base_currency,
        "timezone": c.timezone,
        "fiscal_year_start_month": c.fiscal_year_start_month,
        "salary_cycle_start_day": c.salary_cycle_start_day,
        "policies": c.policies,
    }


async def get_company(session: AsyncSession) -> CompanySettings:
    company = (await session.execute(select(CompanySettings))).scalar_one_or_none()
    if company is None:
        raise NotFound("Company settings are not initialized; run the seed command")
    return company


async def update_company(
    session: AsyncSession, *, actor_id: uuid.UUID, version: int, changes: dict[str, Any]
) -> CompanySettings:
    company = await get_company(session)
    if company.version != version:
        raise PreconditionFailed()
    before = _company_snapshot(company)
    errors = []

    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            errors.append(field_error("timezone", "Unknown IANA time zone", "invalid_timezone"))

    if "base_currency" in changes and changes["base_currency"] != company.base_currency:
        if company.base_currency_locked:
            errors.append(
                field_error("base_currency", "Base currency cannot change after transactions exist", "locked")
            )
        else:
            cur = await session.get(Currency, changes["base_currency"])
            if cur is None or not cur.is_active or cur.is_crypto:
                errors.append(field_error("base_currency", "Must be an active fiat currency", "invalid_currency"))

    if "policies" in changes:
        for key, value in changes["policies"].items():
            allowed = POLICY_VALUES.get(key)
            if allowed is None:
                errors.append(field_error(f"policies.{key}", "Unknown policy", "unknown_policy"))
            elif value not in allowed:
                errors.append(field_error(f"policies.{key}", f"Must be one of: {', '.join(sorted(allowed))}"))
        changes["policies"] = {**company.policies, **changes["policies"]}

    if errors:
        raise ValidationFailed("Invalid company settings", errors=errors)

    for key, value in changes.items():
        setattr(company, key, value)
    company.updated_by = actor_id
    company.version += 1
    await session.flush()
    b, a = audit.diff(before, _company_snapshot(company))
    if a:
        await audit.record(
            session,
            actor_id=actor_id,
            action="company_settings.updated",
            entity_type="company_settings",
            entity_id=company.id,
            before=b,
            after=a,
        )
    return company


# ---- currencies ------------------------------------------------------------------------------------


async def list_currencies(session: AsyncSession, *, include_inactive: bool) -> list[Currency]:
    stmt = select(Currency).order_by(Currency.is_crypto, Currency.code)
    if not include_inactive:
        stmt = stmt.where(Currency.is_active.is_(True))
    return list((await session.execute(stmt)).scalars())


async def get_currency(session: AsyncSession, code: str) -> Currency:
    cur = await session.get(Currency, code.upper())
    if cur is None:
        raise NotFound(f"Currency {code} not found")
    return cur


async def create_currency(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    code: str,
    name: str,
    symbol: str | None,
    precision: int,
    is_crypto: bool,
) -> Currency:
    code = code.upper()
    if await session.get(Currency, code):
        raise Conflict(f"Currency {code} already exists")
    cur = Currency(code=code, name=name, symbol=symbol, precision=precision, is_crypto=is_crypto)
    session.add(cur)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="currency.created",
        entity_type="currency",
        entity_id=code,
        after={"name": name, "precision": precision, "is_crypto": is_crypto},
    )
    return cur


async def update_currency(
    session: AsyncSession, *, actor_id: uuid.UUID, code: str, changes: dict[str, Any]
) -> Currency:
    cur = await get_currency(session, code)
    before = {"name": cur.name, "symbol": cur.symbol, "precision": cur.precision, "is_active": cur.is_active}
    if changes.get("is_active") is False:
        company = await get_company(session)
        if company.base_currency == cur.code:
            raise ValidationFailed(
                "The base currency cannot be deactivated",
                errors=[field_error("is_active", "Base currency must stay active", "base_currency")],
            )
    if changes.get("precision") is not None and changes["precision"] < cur.precision:
        # Recorded amounts may use the extra places. Plain SQL: settings sits below accounting.
        used = (
            await session.execute(text("SELECT 1 FROM journal_lines WHERE currency = :c LIMIT 1"), {"c": cur.code})
        ).first()
        if used:
            raise ValidationFailed(
                "Precision in use",
                errors=[
                    field_error("precision", f"{cur.code} is already used in the ledger; decimals can only increase")
                ],
            )
    for key, value in changes.items():
        setattr(cur, key, value)
    await session.flush()
    b, a = audit.diff(
        before, {"name": cur.name, "symbol": cur.symbol, "precision": cur.precision, "is_active": cur.is_active}
    )
    if a:
        await audit.record(
            session,
            actor_id=actor_id,
            action="currency.updated",
            entity_type="currency",
            entity_id=cur.code,
            before=b,
            after=a,
        )
    return cur


# ---- exchange rates --------------------------------------------------------------------------------


async def upsert_rate(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    from_currency: str,
    to_currency: str,
    rate_date: date,
    rate: Decimal,
    source: str = "manual",
) -> ExchangeRate:
    from_currency, to_currency = from_currency.upper(), to_currency.upper()
    if from_currency == to_currency:
        raise ValidationFailed(
            "Currencies must differ", errors=[field_error("to_currency", "Must differ from from_currency")]
        )
    if rate <= 0:
        raise ValidationFailed("Rate must be positive", errors=[field_error("rate", "Must be greater than 0")])
    for field, code in (("from_currency", from_currency), ("to_currency", to_currency)):
        cur = await session.get(Currency, code)
        if cur is None:
            raise ValidationFailed("Unknown currency", errors=[field_error(field, f"Unknown currency {code}")])

    existing = (
        await session.execute(
            select(ExchangeRate).where(
                ExchangeRate.from_currency == from_currency,
                ExchangeRate.to_currency == to_currency,
                ExchangeRate.rate_date == rate_date,
            )
        )
    ).scalar_one_or_none()
    before = {"rate": existing.rate} if existing else None
    if existing:
        existing.rate, existing.source, existing.updated_by = rate, source, actor_id
        row = existing
    else:
        row = ExchangeRate(
            from_currency=from_currency,
            to_currency=to_currency,
            rate_date=rate_date,
            rate=rate,
            source=source,
            created_by=actor_id,
            updated_by=actor_id,
        )
        session.add(row)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="exchange_rate.saved",
        entity_type="exchange_rate",
        entity_id=row.id,
        before=before,
        after={"pair": f"{from_currency}/{to_currency}", "date": rate_date, "rate": rate},
    )
    return row


async def delete_rate(session: AsyncSession, *, actor_id: uuid.UUID, rate_id: uuid.UUID) -> None:
    row = await session.get(ExchangeRate, rate_id)
    if row is None:
        raise NotFound("Exchange rate not found")
    await session.delete(row)
    await audit.record(
        session,
        actor_id=actor_id,
        action="exchange_rate.deleted",
        entity_type="exchange_rate",
        entity_id=rate_id,
        before={"pair": f"{row.from_currency}/{row.to_currency}", "date": row.rate_date, "rate": row.rate},
    )


async def lookup_rate(
    session: AsyncSession, from_currency: str, to_currency: str, on: date
) -> tuple[Decimal, date | None, str]:
    """Most recent rate on or before `on`. Falls back to the inverse of the reverse pair.

    Returns (rate, rate_date, how) where how is 'identity', 'direct' or 'inverse'.
    """
    from_currency, to_currency = from_currency.upper(), to_currency.upper()
    if from_currency == to_currency:
        return Decimal(1), None, "identity"

    async def latest(f: str, t: str) -> ExchangeRate | None:
        return (
            await session.execute(
                select(ExchangeRate)
                .where(ExchangeRate.from_currency == f, ExchangeRate.to_currency == t, ExchangeRate.rate_date <= on)
                .order_by(ExchangeRate.rate_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    direct = await latest(from_currency, to_currency)
    inverse = await latest(to_currency, from_currency)
    if direct and (not inverse or direct.rate_date >= inverse.rate_date):
        return direct.rate, direct.rate_date, "direct"
    if inverse:
        return (Decimal(1) / inverse.rate).quantize(RATE_PLACES), inverse.rate_date, "inverse"
    raise NotFound(f"No exchange rate for {from_currency}/{to_currency} on or before {on.isoformat()}")


# ---- seed ------------------------------------------------------------------------------------------


async def seed(session: AsyncSession, *, company_name: str = "My Company", base_currency: str = "USD") -> None:
    existing = set((await session.execute(select(Currency.code))).scalars())
    for code, name, symbol, precision, is_crypto in DEFAULT_CURRENCIES:
        if code not in existing:
            session.add(Currency(code=code, name=name, symbol=symbol, precision=precision, is_crypto=is_crypto))
    await session.flush()
    if (await session.execute(select(CompanySettings.id))).first() is None:
        session.add(
            CompanySettings(
                name=company_name, base_currency=base_currency, timezone="UTC", policies=dict(DEFAULT_POLICIES)
            )
        )
        await session.flush()


# ---- helpers for other modules ---------------------------------------------------------------------


async def base_currency(session: AsyncSession) -> Currency:
    company = await get_company(session)
    return await get_currency(session, company.base_currency)


async def lock_base_currency(session: AsyncSession) -> None:
    """Called when the first journal entry is posted; the base currency is frozen afterwards."""
    company = await get_company(session)
    if not company.base_currency_locked:
        company.base_currency_locked = True
        await session.flush()


async def policy(session: AsyncSession, key: str) -> Any:
    company = await get_company(session)
    return company.policies.get(key, DEFAULT_POLICIES.get(key))


async def today(session: AsyncSession) -> date:
    """Today in the company's time zone."""
    return clock.today((await get_company(session)).timezone)


async def set_salary_cycle_start_day(session: AsyncSession, *, actor_id: uuid.UUID, day: int) -> CompanySettings:
    """Owned by the salary module, which first checks what the change does to existing periods."""
    company = await get_company(session)
    if company.salary_cycle_start_day == day:
        return company
    before = company.salary_cycle_start_day
    company.salary_cycle_start_day = day
    company.updated_by = actor_id
    company.version += 1
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="company_settings.updated",
        entity_type="company_settings",
        entity_id=company.id,
        before={"salary_cycle_start_day": before},
        after={"salary_cycle_start_day": day},
    )
    return company
