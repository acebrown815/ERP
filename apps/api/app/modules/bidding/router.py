"""Bidding analytics, read live from the bids and job-list Google Sheets (see docs/bidding-analytics-plan.md).

Scopes: bidding.read OWN sees their own bids and numbers; ALL sees everyone's. The job list is visible to
everyone with bidding.read, including who bid on each job. bidding.manage covers the Sources page and setting
other people's bidding profile names.
"""

import asyncio
import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NotFound
from app.core.exports import ExportFormat, export_response
from app.core.pagination import PageParams, page_params
from app.modules.auth.api import CurrentUser, require
from app.modules.bidding import config, service, store
from app.modules.bidding.cache import SnapshotCache
from app.modules.bidding.deps import get_cache
from app.modules.bidding.normalize import name_key
from app.modules.bidding.schemas import (
    BidsPage,
    ConnectionTestIn,
    ConnectionTestOut,
    DailyOut,
    DataState,
    JobsPage,
    ProfileIn,
    ProfileOut,
    ProfileTab,
    SettingsIn,
    SettingsOut,
    SourcesOut,
    StatsOut,
    TabCount,
)
from app.modules.bidding.sheets import SheetsError, WebApp, test_bids, test_jobs
from app.modules.employees import api as employees
from app.modules.rbac.api import Scope
from app.modules.settings import api as settings

router = APIRouter(prefix="/bidding", tags=["bidding"])

Reader = Depends(require("bidding.read"))
Manager = Depends(require("bidding.manage"))
Score = Annotated[float | None, Query(ge=0, le=100)]
Text = Annotated[str | None, Query(max_length=200)]
Choices = Annotated[list[str] | None, Query(max_length=100)]


async def _people(session: AsyncSession) -> service.People:
    return service.People(
        service.Person(employee_id=e.id, name=e.full_name, profile_names=tuple(names))
        for e, names in await employees.bidding_profiles(session)
    )


async def _own(session: AsyncSession, user: CurrentUser) -> Any:
    me = await employees.for_user(session, user.id)
    if me is None:
        raise NotFound("Your user is not linked to an employee record; ask an administrator to link it")
    return me


async def _mine_keys(session: AsyncSession, user: CurrentUser, mine: bool) -> set[str] | None:
    """The job list's "Mine": the user's own tabs. Without an employee record that is simply no jobs."""
    if not mine:
        return None
    me = await employees.for_user(session, user.id)
    return {name_key(n) for n in await employees.profile_names(session, me.id)} if me else set()


def _sees_all(user: CurrentUser) -> bool:
    return user.scope_for("bidding.read") == Scope.ALL


async def _scope(
    session: AsyncSession, user: CurrentUser, people: service.People, employee_id: uuid.UUID | None
) -> tuple[set[str] | None, service.Person | None, bool]:
    """(tab keys to include or None for everyone, the person shown, they have no profile name)."""
    if employee_id is None and _sees_all(user):
        return None, None, False
    if employee_id is None or not _sees_all(user):
        me = await _own(session, user)
        if employee_id is not None and employee_id != me.id:
            raise NotFound("Employee not found")
        employee_id = me.id
    person = people.by_id.get(employee_id)
    if person is None:
        e = await employees.get(session, employee_id)
        person = service.Person(employee_id=e.id, name=e.full_name)
    return person.keys, person, not person.keys


def _tab_scope(user: CurrentUser, tab: str | None, tab_keys: set[str] | None) -> set[str] | None:
    """Narrow to one sheet tab: one of an employee's profiles, or for managers any tab (e.g. an unclaimed one)."""
    if not tab:
        return tab_keys
    wanted = {name_key(tab)}
    if tab_keys is None:
        return wanted if _sees_all(user) else tab_keys
    return tab_keys & wanted


@router.get("/stats", response_model=StatsOut)
async def stats(
    date_from: date | None = None,
    date_to: date | None = None,
    employee_id: uuid.UUID | None = None,
    tab: Text = None,
    refresh: bool = False,
    user: CurrentUser = Reader,
    session: AsyncSession = Depends(get_session),
    cache: SnapshotCache = Depends(get_cache),
) -> StatsOut:
    """Company-wide (ALL, no employee_id) or one employee's numbers for a date range (default: last 30 days)."""
    people = await _people(session)
    tab_keys, person, missing = await _scope(session, user, people, employee_id)
    tab_keys = _tab_scope(user, tab, tab_keys)
    start, end = service.clamp_range(date_from, date_to, await settings.today(session))
    snap = await cache.get(force=refresh)
    return service.stats(
        snap,
        people,
        date_from=start,
        date_to=end,
        tab_keys=tab_keys,
        person=person,
        profile_missing=missing,
        with_employees=tab_keys is None,
    )


@router.get("/daily", response_model=DailyOut)
async def daily(
    date_from: date | None = None,
    date_to: date | None = None,
    user: CurrentUser = Reader,
    session: AsyncSession = Depends(get_session),
    cache: SnapshotCache = Depends(get_cache),
) -> DailyOut:
    people = await _people(session)
    tab_keys, _, _ = await _scope(session, user, people, None)
    start, end = service.clamp_range(date_from, date_to, await settings.today(session), default_days=1)
    snap = await cache.get()
    return service.daily(snap, people, date_from=start, date_to=end, tab_keys=tab_keys)


async def _bids(
    session: AsyncSession,
    user: CurrentUser,
    cache: SnapshotCache,
    *,
    employee_id: uuid.UUID | None,
    tab: str | None,
    date_from: date | None,
    date_to: date | None,
    q: str | None,
    min_score: float | None,
    max_score: float | None,
    duplicates: bool,
    outside: bool,
    sort: service.BidSort | None,
    desc: bool,
) -> tuple[list[Any], service.People, Any]:
    people = await _people(session)
    tab_keys, _, _ = await _scope(session, user, people, employee_id)
    tab_keys = _tab_scope(user, tab, tab_keys)
    snap = await cache.get()
    rows = service.filter_bids(
        snap,
        tab_keys=tab_keys,
        date_from=date_from,
        date_to=date_to,
        q=q,
        min_score=min_score,
        max_score=max_score,
        duplicates_only=duplicates,
        outside_only=outside,
    )
    return service.sort_bids(rows, people, sort, desc), people, snap


@router.get("/bids", response_model=BidsPage)
async def list_bids(
    params: PageParams = Depends(page_params),
    employee_id: uuid.UUID | None = None,
    tab: Text = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: Text = None,
    min_score: Score = None,
    max_score: Score = None,
    duplicates: bool = False,
    outside: bool = False,
    sort: service.BidSort | None = None,
    desc: bool = False,
    user: CurrentUser = Reader,
    session: AsyncSession = Depends(get_session),
    cache: SnapshotCache = Depends(get_cache),
) -> BidsPage:
    rows, people, snap = await _bids(
        session,
        user,
        cache,
        employee_id=employee_id,
        tab=tab,
        date_from=date_from,
        date_to=date_to,
        q=q,
        min_score=min_score,
        max_score=max_score,
        duplicates=duplicates,
        outside=outside,
        sort=sort,
        desc=desc,
    )
    page = rows[params.offset : params.offset + params.page_size]
    return BidsPage(
        items=[service.bid_out(b, people) for b in page],
        total=len(rows),
        page=params.page,
        page_size=params.page_size,
        data=service.data_state(snap),
    )


@router.get("/bids/export")
async def export_bids(
    format: Literal["csv", "xlsx"] = "csv",  # no PDF: thousands of rows with long links don't fit a page
    employee_id: uuid.UUID | None = None,
    tab: Text = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: Text = None,
    min_score: Score = None,
    max_score: Score = None,
    duplicates: bool = False,
    outside: bool = False,
    sort: service.BidSort | None = None,
    desc: bool = False,
    user: CurrentUser = Reader,
    session: AsyncSession = Depends(get_session),
    cache: SnapshotCache = Depends(get_cache),
) -> Any:
    rows, people, _ = await _bids(
        session,
        user,
        cache,
        employee_id=employee_id,
        tab=tab,
        date_from=date_from,
        date_to=date_to,
        q=q,
        min_score=min_score,
        max_score=max_score,
        duplicates=duplicates,
        outside=outside,
        sort=sort,
        desc=desc,
    )
    header = ["Date", "Employee", "Tab", "Title", "Company", "Location", "Salary", "Resume", "Score"]
    header += ["In job list", "Listed under", "Duplicate", "Link"]
    out = []
    for b in rows:
        o = service.bid_out(b, people)
        out.append(
            [
                *(o.date, o.employee_name or "", o.tab, o.title, o.company, o.location, o.salary),
                *(o.resume, o.score, "yes" if o.in_job_list else "no", ", ".join(o.listings)),
                *("yes" if o.duplicate else "", o.link),
            ]
        )
    return export_response(format, "bids", header, out, title="Bids")


@router.get("/jobs", response_model=JobsPage)
async def list_jobs(
    params: PageParams = Depends(page_params),
    region: Choices = None,
    role: Choices = None,
    ats: Choices = None,
    skill_level: Choices = None,
    status: Literal["not_bid", "applied"] | None = None,
    remote: bool | None = None,
    recruiter: bool | None = None,
    first_seen_from: date | None = None,
    first_seen_to: date | None = None,
    q: Text = None,
    duplicates: bool = False,
    mine: bool = False,
    sort: service.JobSort | None = None,
    desc: bool = False,
    user: CurrentUser = Reader,
    session: AsyncSession = Depends(get_session),
    cache: SnapshotCache = Depends(get_cache),
) -> JobsPage:
    """Every scraped job with who bid on it. Visible to everyone with bidding.read."""
    people = await _people(session)
    tab_keys = await _mine_keys(session, user, mine)
    snap = await cache.get()
    common: dict[str, Any] = {
        "region": region,
        "role": role,
        "ats": ats,
        "skill_level": skill_level,
        "remote": remote,
        "recruiter": recruiter,
        "first_seen_from": first_seen_from,
        "first_seen_to": first_seen_to,
        "q": q,
        "duplicates_only": duplicates,
        "tab_keys": tab_keys,
    }
    unfiltered = service.filter_jobs(snap, **common)
    rows = [j for j in unfiltered if j.status == status] if status else unfiltered
    rows = service.sort_jobs(rows, sort, desc)
    page = rows[params.offset : params.offset + params.page_size]
    return JobsPage(
        items=[service.job_out(j, people) for j in page],
        total=len(rows),
        page=params.page,
        page_size=params.page_size,
        not_bid=sum(1 for j in unfiltered if j.status == "not_bid"),
        applied=sum(1 for j in unfiltered if j.status == "applied"),
        facets=service.facets(snap),
        data=service.data_state(snap),
    )


@router.get("/daily/export")
async def export_daily(
    format: ExportFormat = "csv",
    date_from: date | None = None,
    date_to: date | None = None,
    user: CurrentUser = Reader,
    session: AsyncSession = Depends(get_session),
    cache: SnapshotCache = Depends(get_cache),
) -> Any:
    report = await daily(date_from, date_to, user, session, cache)
    header = ["Employee", "Profiles", "Applied", "Avg score", "Min", "Max", "In job list", "Top resumes"]
    rows = [
        [
            r.name,
            ", ".join(r.tabs),
            r.applied,
            r.avg_score,
            r.min_score,
            r.max_score,
            r.in_job_list,
            ", ".join(f"{c.name} ({c.count})" for c in r.resumes[: service.TOP_RESUMES]),
        ]
        for r in report.rows
    ]
    start, end = report.date_from.isoformat(), report.date_to.isoformat()
    label = start if start == end else f"{start} to {end}"
    return export_response(format, f"bids-{start}-{end}", header, rows, title=f"Bids, {label}")


# ---- profile name -----------------------------------------------------------------------------------------


async def _profile(session: AsyncSession, cache: SnapshotCache, employee: Any) -> ProfileOut:
    people = await _people(session)
    snap = await cache.get()
    names = await employees.profile_names(session, employee.id)
    by_key = {t.key: t for t in snap.tabs}
    tabs = []
    for name in names:
        tab = by_key.get(name_key(name))
        tabs.append(
            ProfileTab(
                name=name,
                found=tab is not None,
                rows=tab.rows if tab else 0,
                applied=tab.applied if tab else 0,
            )
        )
    return ProfileOut(
        employee_id=employee.id,
        employee_name=employee.full_name,
        profile_names=names,
        tabs=tabs,
        rows=sum(t.rows for t in tabs),
        applied=sum(t.applied for t in tabs),
        available_tabs=service.available_tabs(snap, people, {name_key(n) for n in names}),
        data=service.data_state(snap),
    )


@router.get("/me/profile", response_model=ProfileOut)
async def my_profile(
    user: CurrentUser = Reader,
    session: AsyncSession = Depends(get_session),
    cache: SnapshotCache = Depends(get_cache),
) -> ProfileOut:
    return await _profile(session, cache, await _own(session, user))


@router.put("/me/profile", response_model=ProfileOut)
async def set_my_profile(
    body: ProfileIn,
    user: CurrentUser = Reader,
    session: AsyncSession = Depends(get_session),
    cache: SnapshotCache = Depends(get_cache),
) -> ProfileOut:
    """Employees set their own bidding profile names: the tabs their extension writes to."""
    me = await _own(session, user)
    employee = await employees.set_bidding_profile_names(
        session, actor_id=user.id, employee_id=me.id, names=body.profile_names
    )
    await session.commit()
    return await _profile(session, cache, employee)


@router.put("/employees/{employee_id}/profile", response_model=ProfileOut)
async def set_employee_profile(
    employee_id: uuid.UUID,
    body: ProfileIn,
    user: CurrentUser = Manager,
    session: AsyncSession = Depends(get_session),
    cache: SnapshotCache = Depends(get_cache),
) -> ProfileOut:
    employee = await employees.set_bidding_profile_names(
        session, actor_id=user.id, employee_id=employee_id, names=body.profile_names
    )
    await session.commit()
    return await _profile(session, cache, employee)


# ---- sources ----------------------------------------------------------------------------------------------


@router.get("/sources", response_model=SourcesOut)
async def sources(
    refresh: bool = False,
    _: CurrentUser = Manager,
    session: AsyncSession = Depends(get_session),
    cache: SnapshotCache = Depends(get_cache),
) -> SourcesOut:
    snap = await cache.get(force=refresh)
    return service.sources(snap, await _people(session), cache.ttl)


@router.post("/refresh", response_model=DataState)
async def refresh(_: CurrentUser = Reader, cache: SnapshotCache = Depends(get_cache)) -> DataState:
    """Pull both sheets again now (ignored if the data is under 15 seconds old)."""
    return service.data_state(await cache.get(force=True))


# ---- connection settings (Settings → Bidding Sheets) --------------------------------------------------------


async def _settings_out(session: AsyncSession) -> SettingsOut:
    cfg = await store.load(session)
    return SettingsOut(
        bids_webapp_url=cfg.bids_url,
        bids_secret_set=bool(cfg.bids_secret),
        bids_secret_hint=config.hint(cfg.bids_secret),
        jobs_webapp_url=cfg.jobs_url,
        jobs_token_set=bool(cfg.jobs_token),
        jobs_token_hint=config.hint(cfg.jobs_token),
        jobs_tabs=list(cfg.jobs_tabs),
        cache_seconds=cfg.cache_seconds,
        version=await store.current_version(session),
    )


@router.get("/settings", response_model=SettingsOut)
async def get_bidding_settings(_: CurrentUser = Manager, session: AsyncSession = Depends(get_session)) -> SettingsOut:
    return await _settings_out(session)


@router.put("/settings", response_model=SettingsOut)
async def update_bidding_settings(
    body: SettingsIn, user: CurrentUser = Manager, session: AsyncSession = Depends(get_session)
) -> SettingsOut:
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    if "jobs_tabs" in changes:
        changes["jobs_tabs"] = ", ".join(changes["jobs_tabs"] or [])
    await store.update(session, actor_id=user.id, version=body.version, changes=changes)
    await session.commit()
    return await _settings_out(session)


@router.post("/settings/test", response_model=ConnectionTestOut)
async def test_connection(
    body: ConnectionTestIn, _: CurrentUser = Manager, session: AsyncSession = Depends(get_session)
) -> ConnectionTestOut:
    """Try a web app with the values typed in the form (blank = the saved ones). Reads only.

    The saved secret only ever goes to the saved URL: testing another URL needs its secret typed in."""
    cfg = await store.load(session)
    saved_url, saved_secret = (
        (cfg.bids_url, cfg.bids_secret) if body.target == "bids" else (cfg.jobs_url, cfg.jobs_token)
    )
    url = (body.url or "").strip() or saved_url
    typed_secret = (body.secret or "").strip()
    secret = typed_secret or saved_secret
    tabs = [t.strip() for t in (body.tabs if body.tabs is not None else cfg.jobs_tabs) if t.strip()]
    if not url or not secret:
        return ConnectionTestOut(ok=False, message="Enter the web app URL and the secret first.", tabs=[])
    bad_url = config.check_url(url, "url")
    if bad_url:
        return ConnectionTestOut(ok=False, message=bad_url["message"], tabs=[])
    if not typed_secret and url != saved_url:
        return ConnectionTestOut(
            ok=False, message="This URL isn't the saved one: enter its secret to test it.", tabs=[]
        )
    app = WebApp(url, timeout=60, retries=1)
    try:
        if body.target == "bids":
            found = await asyncio.to_thread(test_bids, app, secret)
            message = f"Connected. {len(found)} tab{'s' if len(found) != 1 else ''} in the bids sheet."
        else:
            if not tabs:
                return ConnectionTestOut(ok=False, message="List the job-list tab names first.", tabs=[])
            found = await asyncio.to_thread(test_jobs, app, secret, tabs)
            empty = [n for n, rows in found if rows == 0]
            message = "Connected." + (f" Empty tabs (check the names): {', '.join(empty)}." if empty else "")
    except SheetsError as e:
        return ConnectionTestOut(ok=False, message=str(e), tabs=[])
    return ConnectionTestOut(ok=True, message=message, tabs=[TabCount(name=n, rows=r) for n, r in found])
