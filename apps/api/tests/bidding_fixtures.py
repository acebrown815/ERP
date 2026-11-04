"""Sheet rows shaped exactly like the two web apps return them, shared by the bidding tests."""

from typing import Any

from app.modules.bidding.sheets import BidTab, JobTab

BID_HEADER = ["Date", "Title", "Link", "Company", "Location", "Salary", "ResumeNo", "Score"]


def bid_row(
    row: int,
    link: str,
    *,
    date: str = "",
    title: str = "",
    company: str = "",
    score: Any = "",
    resume: str = "",
    location: str = "",
    salary: str = "",
    status: str | None = None,
) -> dict[str, Any]:
    r: dict[str, Any] = {
        "row": row,
        "Date": date,
        "Title": title,
        "Link": link,
        "Company": company,
        "Location": location,
        "Salary": salary,
        "ResumeNo": resume,
        "Score": score,
    }
    applied = bool(company or location or salary or resume)
    r["status"] = status or ("applied" if applied else "pending")
    return r


def job_row(key: str, title: str, company: str, first_seen: str, **extra: Any) -> dict[str, Any]:
    base = {
        "key": key,
        "title": title,
        "company": company,
        "location": "Remote",
        "country": "US",
        "remote": True,
        "skill_level": "Senior",
        "salary": "",
        "ats": "Greenhouse",
        "is_recruiter": False,
        "posted_at": first_seen,
        "first_seen": first_seen,
        "url": key,
    }
    return base | extra


def sample_bid_tabs() -> list[BidTab]:
    return [
        BidTab(
            "Alice Smith",
            BID_HEADER,
            [
                # matched by URL despite tracking params and a trailing /application
                bid_row(
                    2,
                    "https://boards.greenhouse.io/acme/jobs/1/application?utm_source=x",
                    date="2026-11-02",
                    title="Backend Engineer",
                    company="Acme",
                    score=87,
                    resume="2",
                ),
                # matched by company + title only
                bid_row(
                    3,
                    "https://acme.wd1.myworkdayjobs.com/en-US/acme/job/R1/apply",
                    date="2026-11-03",
                    title="Data Engineer (Remote)",
                    company="Beta Inc",
                    score="72%",
                    resume="1",
                ),
                bid_row(4, "https://jobs.example.com/pending-1"),  # pending: link only
                bid_row(
                    5,
                    "https://elsewhere.io/job/9",
                    date="2026-11-03",
                    title="Go Dev",
                    company="Gamma",
                    score=91,
                    resume="2",
                ),  # not in the job list
            ],
        ),
        BidTab(
            "bob  jones",
            BID_HEADER,
            [
                bid_row(
                    2,
                    "https://boards.greenhouse.io/acme/jobs/1",
                    date="2026-11-03",
                    title="Backend Engineer",
                    company="Acme",
                    score=60,
                    resume="1",
                ),  # same job as Alice -> duplicate
            ],
        ),
        BidTab(
            "Carol",
            BID_HEADER,
            [
                bid_row(
                    2,
                    "https://jobs.lever.co/zeta/7",
                    date="2026-10-01",
                    title="SRE",
                    company="Zeta",
                    score=80,
                    resume="3",
                ),
            ],
        ),
    ]


def sample_job_tabs() -> list[JobTab]:
    return [
        JobTab(
            "US - Software",
            [],
            [
                job_row("https://boards.greenhouse.io/acme/jobs/1", "Backend Engineer", "Acme", "2026-11-01"),
                job_row("https://jobs.lever.co/omega/3", "Frontend Engineer", "Omega", "2026-11-03", ats="Lever"),
            ],
        ),
        JobTab(
            "US - Data",
            [],
            [
                job_row(
                    "workday:Beta:R9",
                    "Data Engineer",
                    "Beta",
                    "2026-11-02",
                    url="https://beta.wd5.myworkdayjobs.com/beta/job/R9",
                    ats="Workday",
                ),
            ],
        ),
        JobTab(
            "EU - Software",
            [],
            [
                # same key as a US row: counted once
                job_row("https://boards.greenhouse.io/acme/jobs/1", "Backend Engineer", "Acme", "2026-11-01"),
            ],
        ),
    ]
