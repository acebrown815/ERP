import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.pagination import Page, PageParams, page_params, paginate
from app.modules.auth.api import CurrentUser, current_user, require
from app.modules.settings import service
from app.modules.settings.models import ExchangeRate

router = APIRouter(tags=["settings"])


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    legal_name: str | None
    email: str | None
    phone: str | None
    website: str | None
    address: dict[str, Any]
    base_currency: str
    base_currency_locked: bool
    timezone: str
    fiscal_year_start_month: int
    salary_cycle_start_day: int
    policies: dict[str, Any]
    version: int


class CompanyUpdateIn(BaseModel):
    # Unknown fields are errors, not silently ignored (the salary cycle has its own endpoint).
    model_config = ConfigDict(extra="forbid")

    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    legal_name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    website: str | None = Field(default=None, max_length=200)
    address: dict[str, str] | None = None
    base_currency: str | None = Field(default=None, min_length=3, max_length=10)
    timezone: str | None = Field(default=None, max_length=64)
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)
    policies: dict[str, str] | None = None


class CurrencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    symbol: str | None
    precision: int
    is_crypto: bool
    is_active: bool


class CurrencyCreateIn(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9]{2,10}$")
    name: str = Field(min_length=1, max_length=100)
    symbol: str | None = Field(default=None, max_length=10)
    precision: int = Field(ge=0, le=18)
    is_crypto: bool = False


class CurrencyUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    symbol: str | None = Field(default=None, max_length=10)
    precision: int | None = Field(default=None, ge=0, le=18)
    is_active: bool | None = None


class RateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_currency: str
    to_currency: str
    rate_date: date
    rate: Decimal
    source: str


class RateIn(BaseModel):
    from_currency: str
    to_currency: str
    rate_date: date
    rate: Decimal = Field(gt=0, max_digits=30, decimal_places=12)


class RateLookupOut(BaseModel):
    from_currency: str
    to_currency: str
    on: date
    rate: Decimal
    rate_date: date | None
    method: str


@router.get("/settings/company", response_model=CompanyOut)
async def get_company(_: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)) -> Any:
    return await service.get_company(session)


@router.patch("/settings/company", response_model=CompanyOut)
async def update_company(
    body: CompanyUpdateIn,
    actor: CurrentUser = Depends(require("settings.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    if changes.get("base_currency"):
        changes["base_currency"] = changes["base_currency"].upper()
    company = await service.update_company(session, actor_id=actor.id, version=body.version, changes=changes)
    await session.commit()
    return company


@router.get("/currencies", response_model=list[CurrencyOut])
async def list_currencies(
    include_inactive: bool = False, _: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> Any:
    return await service.list_currencies(session, include_inactive=include_inactive)


@router.post("/currencies", response_model=CurrencyOut, status_code=201)
async def create_currency(
    body: CurrencyCreateIn,
    actor: CurrentUser = Depends(require("currencies.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    cur = await service.create_currency(session, actor_id=actor.id, **body.model_dump())
    await session.commit()
    return cur


@router.patch("/currencies/{code}", response_model=CurrencyOut)
async def update_currency(
    code: str,
    body: CurrencyUpdateIn,
    actor: CurrentUser = Depends(require("currencies.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    cur = await service.update_currency(
        session, actor_id=actor.id, code=code, changes=body.model_dump(exclude_unset=True)
    )
    await session.commit()
    return cur


@router.get("/exchange-rates", response_model=Page[RateOut])
async def list_rates(
    params: PageParams = Depends(page_params),
    currency: str | None = Query(default=None, description="Matches either side of the pair"),
    _: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    stmt = select(ExchangeRate).order_by(ExchangeRate.rate_date.desc(), ExchangeRate.from_currency)
    if currency:
        c = currency.upper()
        stmt = stmt.where((ExchangeRate.from_currency == c) | (ExchangeRate.to_currency == c))
    rows, total = await paginate(session, stmt, params)
    return Page(
        items=[RateOut.model_validate(r) for r in rows], total=total, page=params.page, page_size=params.page_size
    )


@router.get("/exchange-rates/lookup", response_model=RateLookupOut)
async def lookup_rate(
    from_currency: str = Query(alias="from"),
    to_currency: str = Query(alias="to"),
    on: date = Query(),
    _: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> RateLookupOut:
    rate, rate_date, method = await service.lookup_rate(session, from_currency, to_currency, on)
    return RateLookupOut(
        from_currency=from_currency.upper(),
        to_currency=to_currency.upper(),
        on=on,
        rate=rate,
        rate_date=rate_date,
        method=method,
    )


@router.put("/exchange-rates", response_model=RateOut)
async def upsert_rate(
    body: RateIn,
    actor: CurrentUser = Depends(require("currencies.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    row = await service.upsert_rate(session, actor_id=actor.id, **body.model_dump())
    await session.commit()
    return row


@router.delete("/exchange-rates/{rate_id}", status_code=204)
async def delete_rate(
    rate_id: uuid.UUID,
    actor: CurrentUser = Depends(require("currencies.manage")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await service.delete_rate(session, actor_id=actor.id, rate_id=rate_id)
    await session.commit()
    return Response(status_code=204)
