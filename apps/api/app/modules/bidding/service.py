"""Aggregations over a Snapshot. Pure functions: the router supplies the snapshot, the people and the scope."""

import re
import uuid
from collections import Counter
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal, get_args

from app.modules.bidding.normalize import name_key
from app.modules.bidding.schemas import (
    BiddingJobOut,
    BidOut,
    Count,
    DailyOut,
    DailyRow,
    DataState,
    DayPoint,
    EmployeeRow,
    Facets,
    JobBidOut,
    JobTabOut,
    PersonOut,
    SourceOut,
    SourcesOut,
    StatsOut,
    TabOut,
)
from app.modules.bidding.snapshot import Bid, JobStatus, ScrapedJob, Snapshot, SourceState

MAX_RANGE_DAYS = 366
TOP_RESUMES = 3  # how many the daily export lists; the pages show the same number
TAILORED_SUFFIX = re.compile(r"\s+—\s+tailored\s*$", re.IGNORECASE)
SCORE_BANDS = [("90–100", 90, 101), ("80–89", 80, 90), ("70–79", 70, 80), ("60–69", 60, 70), ("Under 60", 0, 60)]


@dataclass(frozen=True)
class Person:
    employee_id: uuid.UUID
    name: str
    profile_names: tuple[str, ...] = ()

    @property
    def keys(self) -> set[str]:
        return {name_key(n) for n in self.profile_names}

    @property
    def group(self) -> str:
        return f"employee:{self.employee_id}"


class People:
    """Employees by their bidding profile names (tab keys). A tab has one owner; an owner can have several tabs."""

    def __init__(self, people: Iterable[Person]) -> None:
        self.all = list(people)
        self.by_key = {key: p for p in self.all for key in p.keys}
        self.by_id = {p.employee_id: p for p in self.all}
        self.by_group = {p.group: p for p in self.all}

    def owner(self, tab_key: str) -> Person | None:
        return self.by_key.get(tab_key)

    def group_of(self, tab_key: str) -> str:
        """Rows in the reports: one per employee across their tabs, one per tab nobody has claimed."""
        owner = self.owner(tab_key)
        return owner.group if owner else f"tab:{tab_key}"

    def identity(self, group: str, tab_names: dict[str, str]) -> tuple[uuid.UUID | None, str, list[str]]:
        """(employee id, name to show, tabs) for a report row."""
        owner = self.by_group.get(group)
        if owner:
            return owner.employee_id, owner.name, list(owner.profile_names)
        tab = tab_names.get(group, group)
        return None, tab, [tab]


# ---- shared -----------------------------------------------------------------------------------------------


def _source(s: SourceState) -> SourceOut:
    return SourceOut(configured=s.configured, fetched_at=s.fetched_at, error=s.error)


def data_state(snap: Snapshot) -> DataState:
    seen = [j.first_seen for j in snap.jobs if j.first_seen]
    return DataState(
        built_at=snap.built_at,
        bids=_source(snap.bids_source),
        jobs=_source(snap.jobs_source),
        job_list_from=min(seen) if seen else None,
    )


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _days(date_from: date, date_to: date) -> list[date]:
    return [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]


def clamp_range(date_from: date | None, date_to: date | None, today: date, default_days: int = 30) -> tuple[date, date]:
    end = date_to or today
    start = date_from or end - timedelta(days=default_days - 1)
    if start > end:
        start, end = end, start
    if (end - start).days >= MAX_RANGE_DAYS:
        start = end - timedelta(days=MAX_RANGE_DAYS - 1)
    return start, end


def _q_match(q: str, *fields: str) -> bool:
    return any(q in f.lower() for f in fields if f)


def _sorted[T](rows: list[T], key: Callable[[T], Any], desc: bool) -> list[T]:
    """Blanks (key None) stay last in both directions; rows that tie keep their order, so paging is stable."""
    present = [r for r in rows if key(r) is not None]
    present.sort(key=key, reverse=desc)
    return present + [r for r in rows if key(r) is None]


def _text(value: str) -> str | None:
    return value.lower() or None


def bid_out(b: Bid, people: People) -> BidOut:
    owner = people.owner(b.tab_key)
    return BidOut(
        tab=b.tab,
        employee_id=owner.employee_id if owner else None,
        employee_name=owner.name if owner else None,
        row=b.row,
        date=b.date,
        title=b.title or (b.job.title if b.job else ""),
        link=b.link,
        company=b.company or (b.job.company if b.job else ""),
        location=b.location,
        salary=b.salary,
        resume=b.resume,
        score=b.score,
        duplicate=b.duplicate,
        in_job_list=b.job is not None,
        job_key=b.job.key if b.job else None,
        region=b.job.region if b.job else None,
        role=b.job.role if b.job else None,
        listings=b.job.listing_labels if b.job else [],
    )


# ---- bids -------------------------------------------------------------------------------------------------


def filter_bids(
    snap: Snapshot,
    *,
    tab_keys: set[str] | None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    duplicates_only: bool = False,
    outside_only: bool = False,
) -> list[Bid]:
    """tab_keys None = every tab."""
    needle = (q or "").strip().lower()
    out = []
    for b in snap.bids:
        if tab_keys is not None and b.tab_key not in tab_keys:
            continue
        if (date_from or date_to) and (
            b.date is None or (date_from and b.date < date_from) or (date_to and b.date > date_to)
        ):
            continue
        if min_score is not None and (b.score is None or b.score < min_score):
            continue
        if max_score is not None and (b.score is None or b.score > max_score):
            continue
        if duplicates_only and not b.duplicate:
            continue
        if outside_only and b.job is not None:
            continue
        if needle and not _q_match(needle, b.title, b.company, b.location, b.link, b.tab, b.resume):
            continue
        out.append(b)
    # Newest first; a bid with no date in the sheet goes last.
    out.sort(key=lambda b: (b.date is None, -(b.date.toordinal() if b.date else 0), b.tab.lower(), -b.row))
    return out


BidSort = Literal["date", "employee", "profile", "job", "score", "resume", "list"]


def sort_bids(rows: list[Bid], people: People, sort: BidSort | None, desc: bool = False) -> list[Bid]:
    """A whole result set by one table column. None keeps the default order."""

    def employee(b: Bid) -> str:
        owner = people.owner(b.tab_key)
        return (owner.name if owner else b.tab).lower()

    keys: dict[BidSort, Callable[[Bid], Any]] = {
        "date": lambda b: b.date,
        "employee": employee,
        "profile": lambda b: b.tab.lower(),
        "job": lambda b: (
            (b.company or (b.job.company if b.job else "")).lower(),
            (b.title or (b.job.title if b.job else "")).lower(),
        ),
        "score": lambda b: b.score,
        "resume": lambda b: _text(b.resume),
        "list": lambda b: (b.job.region.lower(), b.job.role.lower()) if b.job else None,
    }
    return _sorted(rows, keys[sort], desc) if sort else rows


# ---- stats ------------------------------------------------------------------------------------------------


def _by_group(bids: list[Bid], people: People) -> dict[str, list[Bid]]:
    groups: dict[str, list[Bid]] = {}
    for b in bids:
        groups.setdefault(people.group_of(b.tab_key), []).append(b)
    return groups


def _employee_rows(bids: list[Bid], people: People, days: list[date], include_idle: bool) -> list[EmployeeRow]:
    by_group = _by_group(bids, people)
    tab_names = {people.group_of(b.tab_key): b.tab for b in bids}
    groups = set(by_group)
    if include_idle:
        groups |= {p.group for p in people.all if p.keys}
    index = {d: i for i, d in enumerate(days)}
    rows = []
    for group in groups:
        group_bids = by_group.get(group, [])
        employee_id, name, tabs = people.identity(group, tab_names)
        scores = [b.score for b in group_bids if b.score is not None]
        by_day = [0] * len(days)
        for b in group_bids:
            if b.date in index:
                by_day[index[b.date]] += 1
        dates = [b.date for b in group_bids if b.date]
        rows.append(
            EmployeeRow(
                employee_id=employee_id,
                name=name,
                tabs=tabs,
                applied=len(group_bids),
                avg_score=_avg(scores),
                min_score=min(scores) if scores else None,
                max_score=max(scores) if scores else None,
                days_active=len(set(dates)),
                last_date=max(dates) if dates else None,
                resumes=_resumes(group_bids),
                by_day=by_day,
            )
        )
    rows.sort(key=lambda r: (-r.applied, r.employee_id is None, r.name.lower()))
    return rows


def _buckets(scores: list[float | None]) -> list[Count]:
    out = []
    for label, lo, hi in SCORE_BANDS:
        out.append(Count(name=label, count=sum(1 for s in scores if s is not None and lo <= s < hi)))
    out.append(Count(name="No score", count=sum(1 for s in scores if s is None)))
    return out


def base_resume(name: str) -> str:
    """The extension names a tailored copy "<resume> — Tailored" (BidExtension content.js)."""
    return TAILORED_SUFFIX.sub("", name)


def _resumes(bids: list[Bid]) -> list[Count]:
    """Every resume used, most used first. A tailored copy counts as its resume, and differences in capitals and
    spacing are the same resume."""
    names: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for b in bids:
        if b.resume:
            name = base_resume(b.resume)
            key = name_key(name)
            names.setdefault(key, name)
            counts[key] += 1
    return [Count(name=names[k], count=v) for k, v in counts.most_common()]


def _top(counter: Counter[str], n: int = 10) -> list[Count]:
    return [Count(name=k, count=v) for k, v in counter.most_common(n) if k]


def stats(
    snap: Snapshot,
    people: People,
    *,
    date_from: date,
    date_to: date,
    tab_keys: set[str] | None,
    person: Person | None = None,
    profile_missing: bool = False,
    with_employees: bool = False,
) -> StatsOut:
    """tab_keys None = whole company; a set = those tabs only (one employee, or nobody when empty)."""
    applied = filter_bids(snap, tab_keys=tab_keys, date_from=date_from, date_to=date_to)
    days = _days(date_from, date_to)

    per_day: dict[date, list[Bid]] = {}
    for b in applied:
        assert b.date is not None
        per_day.setdefault(b.date, []).append(b)
    scraped_in_range = [j for j in snap.jobs if j.first_seen and date_from <= j.first_seen <= date_to]
    scraped_per_day = Counter(j.first_seen for j in scraped_in_range)
    series = [
        DayPoint(
            date=d,
            applied=len(per_day.get(d, [])),
            scraped=scraped_per_day.get(d, 0),
            avg_score=_avg([b.score for b in per_day.get(d, []) if b.score is not None]),
        )
        for d in days
    ]

    # Jobs first seen in this period that got a bid in this period, from the tabs in scope.
    jobs_bid = {b.job.key for b in applied if b.job}
    scraped_bid = sum(1 for j in scraped_in_range if j.key in jobs_bid)
    roles: Counter[str] = Counter()
    for b in applied:
        if b.job:  # under each listing, as the job list filters do; so these can add up to more than `applied`
            roles.update(b.job.listing_labels)
        else:
            roles["Not in job list"] += 1

    per_tab = Counter(b.tab_key for b in applied)
    return StatsOut(
        date_from=date_from,
        date_to=date_to,
        employee_id=person.employee_id if person else None,
        employee_name=person.name if person else None,
        profile_names=list(person.profile_names) if person else [],
        profile_missing=profile_missing,
        applied=len(applied),
        avg_score=_avg([b.score for b in applied if b.score is not None]),
        active_bidders=len({people.group_of(b.tab_key) for b in applied}),
        scraped=len(scraped_in_range),
        scraped_bid=scraped_bid,
        coverage_pct=round(100 * scraped_bid / len(scraped_in_range), 1) if scraped_in_range else None,
        outside_job_list=sum(1 for b in applied if b.job is None),
        duplicates=sum(1 for b in applied if b.duplicate),
        series=series,
        score_buckets=_buckets([b.score for b in applied]),
        resumes=_resumes(applied),
        companies=_top(Counter((b.company or (b.job.company if b.job else "")) for b in applied)),
        roles=_top(roles, 20),
        profiles=[Count(name=n, count=per_tab[name_key(n)]) for n in person.profile_names] if person else [],
        employees=_employee_rows(applied, people, days, include_idle=True) if with_employees else [],
        data=data_state(snap),
    )


def daily(snap: Snapshot, people: People, *, date_from: date, date_to: date, tab_keys: set[str] | None) -> DailyOut:
    """Per person for a date range (one day when the two dates are equal)."""
    applied = filter_bids(snap, tab_keys=tab_keys, date_from=date_from, date_to=date_to)
    by_group = _by_group(applied, people)
    groups = set(by_group)
    groups |= {p.group for p in people.all if p.keys and (tab_keys is None or p.keys & tab_keys)}
    tab_names = {people.group_of(b.tab_key): b.tab for b in applied}
    rows = []
    for group in groups:
        bids = by_group.get(group, [])
        employee_id, name, tabs = people.identity(group, tab_names)
        scores = [b.score for b in bids if b.score is not None]
        rows.append(
            DailyRow(
                employee_id=employee_id,
                name=name,
                tabs=tabs,
                applied=len(bids),
                avg_score=_avg(scores),
                min_score=min(scores) if scores else None,
                max_score=max(scores) if scores else None,
                resumes=_resumes(bids),
                in_job_list=sum(1 for b in bids if b.job is not None),
            )
        )
    rows.sort(key=lambda r: (-r.applied, r.employee_id is None, r.name.lower()))
    return DailyOut(
        date_from=date_from,
        date_to=date_to,
        applied=len(applied),
        avg_score=_avg([b.score for b in applied if b.score is not None]),
        active_bidders=len(by_group),
        scraped=sum(1 for j in snap.jobs if j.first_seen and date_from <= j.first_seen <= date_to),
        rows=rows,
        data=data_state(snap),
    )


# ---- jobs -------------------------------------------------------------------------------------------------


def filter_jobs(
    snap: Snapshot,
    *,
    region: Collection[str] | None = None,
    role: Collection[str] | None = None,
    ats: Collection[str] | None = None,
    skill_level: Collection[str] | None = None,
    status: str | None = None,
    remote: bool | None = None,
    recruiter: bool | None = None,
    first_seen_from: date | None = None,
    first_seen_to: date | None = None,
    q: str | None = None,
    duplicates_only: bool = False,
    tab_keys: set[str] | None = None,
) -> list[ScrapedJob]:
    """tab_keys: only jobs bid on from those tabs (an employee's "my jobs"; empty = none).

    A job listed in several tabs matches through any of them, but region and role must match the same tab:
    a job in "US - Data" and "EU - Software" is not an EU Data job."""
    needle = (q or "").strip().lower()
    out = []
    for j in snap.jobs:
        if (region or role) and not any(
            (not region or listed_region in region) and (not role or listed_role in role)
            for listed_region, listed_role in j.listings
        ):
            continue
        if ats and j.ats not in ats:
            continue
        if skill_level and j.skill_level not in skill_level:
            continue
        if status and j.status != status:
            continue
        if remote is not None and j.remote != remote:
            continue
        if recruiter is not None and j.is_recruiter != recruiter:
            continue
        if first_seen_from and (j.first_seen is None or j.first_seen < first_seen_from):
            continue
        if first_seen_to and (j.first_seen is None or j.first_seen > first_seen_to):
            continue
        if duplicates_only and not j.duplicate:
            continue
        if tab_keys is not None and not any(b.tab_key in tab_keys for b in j.bids):
            continue
        if needle and not _q_match(needle, j.title, j.company, j.location, j.url):
            continue
        out.append(j)
    out.sort(key=lambda j: (-(j.first_seen.toordinal() if j.first_seen else 0), j.company.lower(), j.title.lower()))
    return out


JobSort = Literal["first_seen", "job", "type", "ats", "status"]
_JOB_STATUS_ORDER = get_args(JobStatus)
_JOB_SORT_KEYS: dict[JobSort, Callable[[ScrapedJob], Any]] = {
    "first_seen": lambda j: j.first_seen,
    "job": lambda j: (j.company.lower(), j.title.lower()),
    "type": lambda j: (j.region.lower(), j.role.lower()),
    "ats": lambda j: _text(j.ats),
    "status": lambda j: _JOB_STATUS_ORDER.index(j.status),
}


def sort_jobs(rows: list[ScrapedJob], sort: JobSort | None, desc: bool = False) -> list[ScrapedJob]:
    """A whole result set by one table column. None keeps the default order."""
    return _sorted(rows, _JOB_SORT_KEYS[sort], desc) if sort else rows


def job_out(j: ScrapedJob, people: People) -> BiddingJobOut:
    bids = []
    for b in sorted(j.bids, key=lambda b: b.tab.lower()):
        owner = people.owner(b.tab_key)
        bids.append(
            JobBidOut(
                tab=b.tab,
                employee_id=owner.employee_id if owner else None,
                employee_name=owner.name if owner else None,
                date=b.date,
                score=b.score,
            )
        )
    return BiddingJobOut(
        key=j.key,
        region=j.region,
        role=j.role,
        listings=j.listing_labels,
        title=j.title,
        company=j.company,
        location=j.location,
        country=j.country,
        remote=j.remote,
        skill_level=j.skill_level,
        salary=j.salary,
        ats=j.ats,
        is_recruiter=j.is_recruiter,
        posted_at=j.posted_at,
        first_seen=j.first_seen,
        url=j.url,
        status=j.status,
        duplicate=j.duplicate,
        bids=bids,
    )


def facets(snap: Snapshot) -> Facets:
    def values(attr: str) -> list[str]:
        return sorted({getattr(j, attr) for j in snap.jobs if getattr(j, attr)}, key=str.lower)

    def listed(index: int) -> list[str]:
        return sorted({listing[index] for j in snap.jobs for listing in j.listings if listing[index]}, key=str.lower)

    return Facets(regions=listed(0), roles=listed(1), ats=values("ats"), skill_levels=values("skill_level"))


# ---- sources ----------------------------------------------------------------------------------------------


def sources(snap: Snapshot, people: People, cache_seconds: int) -> SourcesOut:
    tabs = []
    for t in sorted(snap.tabs, key=lambda t: t.name.lower()):
        owner = people.owner(t.key)
        tabs.append(
            TabOut(
                name=t.name,
                rows=t.rows,
                applied=t.applied,
                last_date=t.last_date,
                employee_id=owner.employee_id if owner else None,
                employee_name=owner.name if owner else None,
            )
        )
    tab_keys = {t.key for t in snap.tabs}
    job_rows = Counter(tab for j in snap.jobs for tab in j.tabs)
    return SourcesOut(
        data=data_state(snap),
        tabs=tabs,
        unclaimed_tabs=[t.name for t in tabs if t.employee_id is None],
        employees=[
            PersonOut(employee_id=p.employee_id, name=p.name, profile_names=list(p.profile_names)) for p in people.all
        ],
        profiles_without_tab=[
            PersonOut(employee_id=p.employee_id, name=p.name, profile_names=missing)
            for p in people.all
            if (missing := [n for n in p.profile_names if name_key(n) not in tab_keys])
            and snap.bids_source.fetched_at is not None
        ],
        job_tabs=[JobTabOut(name=n, rows=job_rows.get(n, 0)) for n in snap.jobs_source.tabs_read],
        cache_seconds=cache_seconds,
    )


def available_tabs(snap: Snapshot, people: People, own_keys: set[str]) -> list[str]:
    """Tabs nobody has claimed (plus the employee's own), for the profile-name picker."""
    return sorted((t.name for t in snap.tabs if t.key in own_keys or people.owner(t.key) is None), key=str.lower)
