import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

JobStatus = Literal["not_bid", "applied"]


class SourceOut(BaseModel):
    configured: bool
    fetched_at: dt.datetime | None
    error: str | None


class DataState(BaseModel):
    """How fresh the numbers are; every response carries it so pages can show "Data as of …"."""

    built_at: dt.datetime
    bids: SourceOut
    jobs: SourceOut
    job_list_from: dt.date | None  # oldest first_seen still in the job list (the scraper prunes old rows)


class BidOut(BaseModel):
    tab: str
    employee_id: uuid.UUID | None
    employee_name: str | None
    row: int
    date: dt.date | None
    title: str
    link: str
    company: str
    location: str
    salary: str
    resume: str
    score: float | None
    duplicate: bool
    in_job_list: bool
    job_key: str | None
    region: str | None  # the job's first listing
    role: str | None
    listings: list[str]  # every "region · role" the job is listed under


class BidsPage(BaseModel):
    items: list[BidOut]
    total: int
    page: int
    page_size: int
    data: DataState


class JobBidOut(BaseModel):
    tab: str
    employee_id: uuid.UUID | None
    employee_name: str | None
    date: dt.date | None
    score: float | None


class BiddingJobOut(BaseModel):
    key: str
    region: str  # the first listing
    role: str
    listings: list[str]  # every "region · role" this job is listed under
    title: str
    company: str
    location: str
    country: str
    remote: bool
    skill_level: str
    salary: str
    ats: str
    is_recruiter: bool
    posted_at: dt.date | None
    first_seen: dt.date | None
    url: str
    status: JobStatus
    duplicate: bool
    bids: list[JobBidOut]


class Facets(BaseModel):
    regions: list[str]
    roles: list[str]
    ats: list[str]
    skill_levels: list[str]


class JobsPage(BaseModel):
    items: list[BiddingJobOut]
    total: int
    page: int
    page_size: int
    not_bid: int
    applied: int
    facets: Facets
    data: DataState


class DayPoint(BaseModel):
    date: dt.date
    applied: int
    scraped: int
    avg_score: float | None


class Count(BaseModel):
    name: str
    count: int


class EmployeeRow(BaseModel):
    employee_id: uuid.UUID | None  # None for a tab nobody has claimed
    name: str
    tabs: list[str]  # the employee's profile names, or the one unclaimed tab
    applied: int
    avg_score: float | None
    min_score: float | None
    max_score: float | None
    days_active: int
    last_date: dt.date | None
    resumes: list[Count]  # most used first
    by_day: list[int]  # aligned with StatsOut.series


class StatsOut(BaseModel):
    date_from: dt.date
    date_to: dt.date
    employee_id: uuid.UUID | None
    employee_name: str | None
    profile_names: list[str]
    profile_missing: bool  # the employee has no bidding profile name yet
    applied: int
    avg_score: float | None
    active_bidders: int
    scraped: int
    scraped_bid: int
    coverage_pct: float | None
    outside_job_list: int
    duplicates: int
    series: list[DayPoint]
    score_buckets: list[Count]
    resumes: list[Count]
    companies: list[Count]
    roles: list[Count]
    profiles: list[Count]  # one employee: applied bids per profile name
    employees: list[EmployeeRow]
    data: DataState


class DailyRow(BaseModel):
    employee_id: uuid.UUID | None
    name: str
    tabs: list[str]
    applied: int
    avg_score: float | None
    min_score: float | None
    max_score: float | None
    resumes: list[Count]  # most used first
    in_job_list: int


class DailyOut(BaseModel):
    date_from: dt.date
    date_to: dt.date
    applied: int
    avg_score: float | None
    active_bidders: int
    scraped: int
    rows: list[DailyRow]
    data: DataState


class ProfileIn(BaseModel):
    """The full list: names left out are removed."""

    profile_names: list[Annotated[str, StringConstraints(max_length=100)]] = Field(max_length=50)


class ProfileTab(BaseModel):
    name: str
    found: bool
    rows: int
    applied: int


class ProfileOut(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    profile_names: list[str]
    tabs: list[ProfileTab]
    rows: int
    applied: int
    available_tabs: list[str]
    data: DataState


class TabOut(BaseModel):
    name: str
    rows: int
    applied: int
    last_date: dt.date | None
    employee_id: uuid.UUID | None
    employee_name: str | None


class PersonOut(BaseModel):
    employee_id: uuid.UUID
    name: str
    profile_names: list[str]


class JobTabOut(BaseModel):
    name: str
    rows: int


class SourcesOut(BaseModel):
    data: DataState
    tabs: list[TabOut]
    unclaimed_tabs: list[str]
    employees: list[PersonOut]  # everyone who can have profile names, with their names
    profiles_without_tab: list[PersonOut]  # only the names that have no tab in the sheet
    job_tabs: list[JobTabOut]
    cache_seconds: int


class SettingsOut(BaseModel):
    """Secrets are never returned: only whether they are set and their last four characters."""

    bids_webapp_url: str
    bids_secret_set: bool
    bids_secret_hint: str | None
    jobs_webapp_url: str
    jobs_token_set: bool
    jobs_token_hint: str | None
    jobs_tabs: list[str]
    cache_seconds: int
    version: int


class SettingsIn(BaseModel):
    """Send only what changes. A secret sent as "" is removed; leaving it out keeps the saved one."""

    version: int
    bids_webapp_url: str | None = Field(default=None, max_length=500)
    bids_secret: str | None = Field(default=None, max_length=500)
    jobs_webapp_url: str | None = Field(default=None, max_length=500)
    jobs_token: str | None = Field(default=None, max_length=500)
    jobs_tabs: list[str] | None = None
    cache_seconds: int | None = Field(default=None, ge=30, le=3600)


class ConnectionTestIn(BaseModel):
    """Try a web app before saving. Blank values use what is saved."""

    target: Literal["bids", "jobs"]
    url: str | None = Field(default=None, max_length=500)
    secret: str | None = Field(default=None, max_length=500)
    tabs: list[str] | None = None


class TabCount(BaseModel):
    name: str
    rows: int


class ConnectionTestOut(BaseModel):
    ok: bool
    message: str
    tabs: list[TabCount]
