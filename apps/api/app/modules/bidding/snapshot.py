"""One in-memory picture of both sheets, joined. Pure: build() takes raw tabs and returns a Snapshot.

A bid is a row in an employee's tab with a Link and something else filled in by "Mark as Applied". A row with
only a Link is queued for Auto-Bid, not applied to yet, and is left out (same rule as the web app's listPending).
Status of a scraped job: applied if it has a bid, otherwise not_bid.
Bids are matched to scraped jobs by url_key, then by company + title.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from app.modules.bidding.normalize import (
    cell_text,
    job_identity,
    name_key,
    parse_bool,
    parse_date,
    parse_score,
    url_key,
)
from app.modules.bidding.sheets import BidTab, JobTab

JobStatus = Literal["not_bid", "applied"]


@dataclass
class ScrapedJob:
    key: str
    tab: str
    region: str
    role: str
    title: str
    company: str
    location: str
    country: str
    remote: bool
    skill_level: str
    salary: str
    ats: str
    is_recruiter: bool
    posted_at: date | None
    first_seen: date | None
    url: str
    url_key: str
    identity: str
    bids: list["Bid"] = field(default_factory=list)
    tabs: list[str] = field(default_factory=list)  # every tab listing this job; tab, region and role are the first

    @property
    def listings(self) -> list[tuple[str, str]]:
        """(region, role) for each tab listing this job."""
        return [split_tab_name(t) for t in self.tabs]

    @property
    def listing_labels(self) -> list[str]:
        return [" · ".join(part for part in listing if part) for listing in self.listings]

    @property
    def status(self) -> JobStatus:
        return "applied" if self.bids else "not_bid"

    @property
    def duplicate(self) -> bool:
        return len({b.tab_key for b in self.bids}) > 1


@dataclass
class Bid:
    tab: str
    tab_key: str
    row: int
    date: date | None
    title: str
    link: str
    url_key: str
    identity: str
    company: str
    location: str
    salary: str
    resume: str
    score: float | None
    job: ScrapedJob | None = None
    duplicate: bool = False  # another tab has the same job


@dataclass
class TabInfo:
    name: str
    key: str
    rows: int
    applied: int
    last_date: date | None


@dataclass
class SourceState:
    configured: bool
    fetched_at: datetime | None = None
    error: str | None = None
    tabs_read: list[str] = field(default_factory=list)


@dataclass
class Snapshot:
    jobs: list[ScrapedJob]
    bids: list[Bid]
    tabs: list[TabInfo]
    bids_source: SourceState
    jobs_source: SourceState
    built_at: datetime

    @staticmethod
    def empty(now: datetime, bids_configured: bool = False, jobs_configured: bool = False) -> "Snapshot":
        return Snapshot([], [], [], SourceState(bids_configured), SourceState(jobs_configured), now)


def split_tab_name(name: str) -> tuple[str, str]:
    """ "US - Software" -> ("US", "Software"); a name without " - " is all role."""
    region, sep, role = name.partition(" - ")
    return (region.strip(), role.strip()) if sep else ("", name.strip())


def _get(row: dict[str, Any], *names: str) -> Any:
    """A column by header text, ignoring case and spaces ("ResumeNo", "resume no")."""
    for n in names:
        if n in row:
            return row[n]
    wanted = {n.replace(" ", "").lower() for n in names}
    for k, v in row.items():
        if str(k).replace(" ", "").lower() in wanted:
            return v
    return None


def parse_bid(tab: str, row: dict[str, Any]) -> Bid | None:
    link = cell_text(_get(row, "Link", "URL"))
    if not link:
        return None
    company = cell_text(_get(row, "Company"))
    location = cell_text(_get(row, "Location"))
    salary = cell_text(_get(row, "Salary"))
    resume = cell_text(_get(row, "ResumeNo", "Resume"))
    status = row.get("status")
    if status == "pending" or (status != "applied" and not (company or location or salary or resume)):
        return None
    title = cell_text(_get(row, "Title"))
    return Bid(
        tab=tab,
        tab_key=name_key(tab),
        row=int(row.get("row") or 0),
        date=parse_date(_get(row, "Date")),
        title=title,
        link=link,
        url_key=url_key(link),
        identity=job_identity(company, title),
        company=company,
        location=location,
        salary=salary,
        resume=resume,
        score=parse_score(_get(row, "Score")),
    )


def parse_job(tab: str, row: dict[str, Any]) -> ScrapedJob | None:
    key = cell_text(row.get("key"))
    url = cell_text(row.get("url"))
    if not key and not url:
        return None
    region, role = split_tab_name(tab)
    title, company = cell_text(row.get("title")), cell_text(row.get("company"))
    return ScrapedJob(
        key=key or url,
        tab=tab,
        region=region,
        role=role,
        title=title,
        company=company,
        location=cell_text(row.get("location")),
        country=cell_text(row.get("country")),
        remote=parse_bool(row.get("remote")),
        skill_level=cell_text(row.get("skill_level")),
        salary=cell_text(row.get("salary")),
        ats=cell_text(row.get("ats")),
        is_recruiter=parse_bool(row.get("is_recruiter")),
        posted_at=parse_date(row.get("posted_at")),
        first_seen=parse_date(row.get("first_seen")),
        url=url,
        url_key=url_key(url) or url_key(key),
        identity=job_identity(company, title),
        tabs=[tab],
    )


def build(
    bid_tabs: list[BidTab],
    job_tabs: list[JobTab],
    *,
    now: datetime,
    bids_source: SourceState,
    jobs_source: SourceState,
) -> Snapshot:
    jobs: list[ScrapedJob] = []
    by_key: dict[str, ScrapedJob] = {}
    by_url: dict[str, ScrapedJob] = {}
    by_ident: dict[str, ScrapedJob] = {}
    for jt in job_tabs:
        for row in jt.rows:
            job = parse_job(jt.name, row)
            if job is None:
                continue
            seen = by_key.get(job.key)
            if seen is not None:  # one job, listed in another tab too
                if jt.name not in seen.tabs:
                    seen.tabs.append(jt.name)
                continue
            by_key[job.key] = job
            jobs.append(job)
            if job.url_key:
                by_url.setdefault(job.url_key, job)
            if job.identity:
                by_ident.setdefault(job.identity, job)

    bids: list[Bid] = []
    tabs: list[TabInfo] = []
    for bt in bid_tabs:
        tab_bids = [b for b in (parse_bid(bt.name, r) for r in bt.rows) if b is not None]
        dates = [b.date for b in tab_bids if b.date]
        tabs.append(
            TabInfo(
                name=bt.name,
                key=name_key(bt.name),
                rows=len(tab_bids),
                applied=len(tab_bids),
                last_date=max(dates) if dates else None,
            )
        )
        bids.extend(tab_bids)

    # Join, and flag the same job bid from more than one tab.
    tabs_by_key: dict[str, set[str]] = {}
    for b in bids:
        job = by_url.get(b.url_key) if b.url_key else None
        if job is None and b.identity:
            job = by_ident.get(b.identity)
        if job is not None:
            b.job = job
            job.bids.append(b)
        match = f"job:{job.key}" if job else f"url:{b.url_key or b.link}"
        tabs_by_key.setdefault(match, set()).add(b.tab_key)
    for b in bids:
        match = f"job:{b.job.key}" if b.job else f"url:{b.url_key or b.link}"
        b.duplicate = len(tabs_by_key[match]) > 1

    return Snapshot(jobs=jobs, bids=bids, tabs=tabs, bids_source=bids_source, jobs_source=jobs_source, built_at=now)
