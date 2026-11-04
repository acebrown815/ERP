"""Bidding analytics logic that needs no database: URL/identity matching, the Apps Script clients, joining the
two sheets, the in-memory cache and the numbers on the pages."""

import asyncio
import http.client
import json
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.modules.bidding import service, sheets, snapshot
from app.modules.bidding.cache import SnapshotCache, job_tab_names
from app.modules.bidding.normalize import job_identity, name_key, parse_date, parse_score, url_key
from app.modules.bidding.sheets import BidsClient, JobsClient, SheetsError, WebApp
from tests.bidding_fixtures import BID_HEADER, bid_row, sample_bid_tabs, sample_job_tabs

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
ALICE, BOB = uuid.uuid4(), uuid.uuid4()


def build() -> snapshot.Snapshot:
    return snapshot.build(
        sample_bid_tabs(),
        sample_job_tabs(),
        now=NOW,
        bids_source=snapshot.SourceState(True, NOW),
        jobs_source=snapshot.SourceState(True, NOW, tabs_read=["US - Software", "US - Data", "EU - Software"]),
    )


def people() -> service.People:
    return service.People(
        [
            service.Person(ALICE, "Alice Smith", ("alice smith",)),
            service.Person(BOB, "Bob Jones", ("Bob Jones",)),
            service.Person(uuid.uuid4(), "Dan Idle"),
        ]
    )


# ---- normalize ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (
            "https://boards.greenhouse.io/acme/jobs/1?utm_source=li&gh_src=x",
            "https://boards.greenhouse.io/acme/jobs/1?gh_src=x",
        ),
        ("http://www.Example.com/jobs/1/", "https://example.com/jobs/1"),
        ("https://jobs.ashbyhq.com/acme/abc/application", "https://jobs.ashbyhq.com/acme/abc"),
        (
            "https://ngc.wd1.myworkdayjobs.com/en-US/ngc/job/R1/apply/applyManually",
            "https://ngc.wd1.myworkdayjobs.com/ngc/job/R1",
        ),
        ("https://x.com/j?b=2&a=1#top", "https://x.com/j?a=1&b=2"),
    ],
)
def test_url_key_treats_these_as_the_same_job(a: str, b: str) -> None:
    assert url_key(a) == url_key(b) != ""


def test_url_key_keeps_job_id_params_and_rejects_non_urls() -> None:
    assert url_key("https://x.com/view?jk=1") != url_key("https://x.com/view?jk=2")
    assert url_key("not a url") == "" and url_key(None) == "" and url_key("mailto:a@b.c") == ""


def test_job_identity_and_name_key() -> None:
    assert job_identity("Agile-Defense, Inc.", "Senior Engineer (Remote)") == job_identity(
        "agiledefense", "senior engineer"
    )
    assert job_identity("", "Engineer") == "" and job_identity("Acme", "") == ""
    assert name_key("  Bob   JONES ") == name_key("bob jones")


def test_cell_parsing() -> None:
    assert parse_date("2026-11-03") == date(2026, 11, 3)
    assert parse_date("11/3/2026") == date(2026, 11, 3)
    assert parse_date("2026-11-03T05:00:00.000Z") == date(2026, 11, 3)
    assert parse_date(46329) == date(2026, 11, 3)  # Sheets serial number
    assert parse_date("soon") is None and parse_date("") is None
    assert parse_score("87%") == 87 and parse_score(91) == 91 and parse_score("") is None and parse_score(250) is None


# ---- Apps Script clients ------------------------------------------------------------------------------------


class FakeGoogle:
    """POST /exec -> 302 to an echo URL (like Apps Script); the echo URL returns the queued JSON."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.posts: list[dict[str, Any]] = []
        self.calls = 0

    def __call__(self, url: str, body: bytes | None, timeout: float) -> tuple[int, dict[str, str], bytes]:
        self.calls += 1
        if body is not None:
            self.posts.append(json.loads(body))
            return 302, {"location": "https://script.googleusercontent.com/macros/echo?x=1"}, b""
        nxt = self.responses.pop(0)
        if isinstance(nxt, int):
            return nxt, {}, b""
        return 200, {"content-type": "application/json"}, json.dumps(nxt).encode()


def app(fake: FakeGoogle) -> WebApp:
    return WebApp("https://script.google.com/macros/s/x/exec", transport=fake, sleep=lambda _: None)


def test_bids_client_reads_all_tabs_through_the_redirect() -> None:
    fake = FakeGoogle(
        {"success": True, "tabs": [{"name": "Alice", "header": BID_HEADER, "rows": [bid_row(2, "https://a/1")]}]}
    )
    tabs = BidsClient(app(fake), "s3cret").read_all()
    assert fake.posts == [{"secret": "s3cret", "readTabs": True}]
    assert tabs[0].name == "Alice" and tabs[0].rows[0]["Link"] == "https://a/1"


def test_bids_client_retries_when_google_loses_the_result_and_explains_old_deployments() -> None:
    fake = FakeGoogle(404, {"success": True, "tabs": []})
    assert BidsClient(app(fake), "s").read_all() == []
    assert len(fake.posts) == 2

    old = FakeGoogle({"success": False, "error": "Request had neither test, job, nor listPending."})
    with pytest.raises(SheetsError, match="re-deploy"):
        BidsClient(app(old), "s").read_all()
    bad = FakeGoogle({"success": False, "error": "Invalid secret."})
    with pytest.raises(SheetsError, match="Invalid secret"):
        BidsClient(app(bad), "wrong").read_all()


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/macros/echo?x=1",
        "https://evil.example/exec",
        "http://script.google.com/macros/s/x/exec",
        "https://script.google.com.evil.example/exec",
        "https://script.googleusercontent.com.evil.example/macros/echo",
        "/relative",
    ],
)
def test_redirects_off_google_are_never_followed(location: str) -> None:
    """The POST body holds the secret, and a fake echo URL could feed in made-up data."""
    urls: list[str] = []

    def transport(url: str, body: bytes | None, timeout: float) -> tuple[int, dict[str, str], bytes]:
        urls.append(url)
        return 302, {"location": location}, b""

    web_app = WebApp("https://script.google.com/macros/s/x/exec", transport=transport, sleep=lambda _: None, retries=1)
    with pytest.raises(SheetsError, match="redirected away"):
        web_app.post({"secret": "s3cret"})
    assert set(urls) == {web_app.url}


def test_redirects_within_google_are_followed() -> None:
    echo = "https://script.googleusercontent.com/a/macros/acme.com/echo?user_content_key=1"
    calls: list[tuple[str, bool]] = []

    def transport(url: str, body: bytes | None, timeout: float) -> tuple[int, dict[str, str], bytes]:
        calls.append((url, body is not None))
        if url.endswith("/s/x/exec"):
            return 302, {"location": "https://script.google.com/macros/s/y/exec"}, b""
        if url.endswith("/s/y/exec"):
            return 302, {"location": echo}, b""
        return 200, {}, b'{"success": true}'

    web_app = WebApp("https://script.google.com/macros/s/x/exec", transport=transport, sleep=lambda _: None)
    assert web_app.post({"secret": "s3cret"}) == {"success": True}
    assert calls[1:] == [("https://script.google.com/macros/s/y/exec", True), (echo, False)]


def test_get_reaching_doget_is_retried_then_reported() -> None:
    fake = FakeGoogle(*[{"status": "ok", "message": "running"}] * 5)
    with pytest.raises(SheetsError, match="doGet"):
        BidsClient(app(fake), "s").read_all()


def test_jobs_client_pages_through_read_columns() -> None:
    def page(keys: list[str], total: int) -> dict[str, Any]:
        return {
            "ok": True,
            "header": ["key", "title"],
            "total_rows": total,
            "columns": {"key": keys, "title": ["T"] * len(keys)},
        }

    fake = FakeGoogle(page(["a", "b"], 3), page(["c"], 3))
    tab = JobsClient(app(fake), "tok", chunk=2).read_tab("US - Software")
    assert [r["key"] for r in tab.rows] == ["a", "b", "c"]
    assert [r["company"] for r in tab.rows] == ["", "", ""]  # missing columns are padded
    assert fake.posts[0]["action"] == "read_columns" and fake.posts[1]["offset"] == 2
    assert fake.posts[0]["sheet"] == "US - Software" and fake.posts[0]["token"] == "tok"
    assert job_tab_names(" US - Software , ,EU - Data") == ["US - Software", "EU - Data"]


# ---- joining ------------------------------------------------------------------------------------------------


def test_build_joins_bids_to_jobs() -> None:
    snap = build()
    assert len(snap.jobs) == 3  # the EU copy of the same key is counted once
    jobs = {j.key: j for j in snap.jobs}
    acme = jobs["https://boards.greenhouse.io/acme/jobs/1"]
    assert acme.status == "applied" and acme.duplicate and {b.tab for b in acme.bids} == {"Alice Smith", "bob  jones"}
    beta = jobs["workday:Beta:R9"]
    assert beta.status == "applied" and [b.tab for b in beta.bids] == ["Alice Smith"]  # by company + title
    assert jobs["https://jobs.lever.co/omega/3"].status == "not_bid"

    alice = [b for b in snap.bids if b.tab == "Alice Smith"]
    assert len(alice) == 3 and alice[1].score == 72  # the row with only a Link is left out
    assert alice[2].job is None and not alice[2].duplicate
    assert {t.name: t.applied for t in snap.tabs}["Alice Smith"] == 3
    assert acme.region == "US" and acme.role == "Software"
    assert acme.tabs == ["US - Software", "EU - Software"]  # the same key in a second tab adds a listing


# ---- cache --------------------------------------------------------------------------------------------------


def test_cache_shares_one_fetch_keeps_old_data_on_failure_and_respects_ttl() -> None:
    clock = [0.0]
    calls = {"bids": 0, "jobs": 0}
    fail = {"jobs": False}

    def bids() -> list[Any]:
        calls["bids"] += 1
        return sample_bid_tabs()

    def jobs() -> list[Any]:
        calls["jobs"] += 1
        if fail["jobs"]:
            raise SheetsError("web app returned HTTP 500")
        return sample_job_tabs()

    cache = SnapshotCache(
        bids_reader=bids, jobs_reader=jobs, ttl_seconds=300, monotonic=lambda: clock[0], now=lambda: NOW
    )

    async def run() -> None:
        a, b = await asyncio.gather(cache.get(), cache.get())
        assert a is b and calls == {"bids": 1, "jobs": 1}
        clock[0] = 100
        await cache.get()
        assert calls["bids"] == 1  # still fresh
        await cache.get(force=True)
        assert calls["bids"] == 2  # forced
        clock[0] = 105
        await cache.get(force=True)
        assert calls["bids"] == 2  # under 15 seconds: ignored
        fail["jobs"] = True
        clock[0] = 500
        await cache.refresh()
        snap = await cache.get()
        assert snap.jobs_source.error == "web app returned HTTP 500"
        assert len(snap.jobs) == 3  # previous job list kept
        assert snap.bids_source.error is None

    asyncio.run(run())


def test_old_data_is_returned_at_once_while_one_read_runs_in_the_background() -> None:
    clock = [0.0]
    calls = [0]

    def bids() -> list[Any]:
        calls[0] += 1
        return sample_bid_tabs()

    cache = SnapshotCache(
        bids_reader=bids, jobs_reader=None, ttl_seconds=300, monotonic=lambda: clock[0], now=lambda: NOW
    )

    async def run() -> None:
        first = await cache.get()  # nothing to show yet: this one waits
        assert calls[0] == 1
        await cache.refresh()
        assert calls[0] == 1  # still fresh: the refresher leaves it alone

        clock[0] = 301
        a, b = await asyncio.gather(cache.get(), cache.get())
        assert a is first and b is first and calls[0] == 1  # answered from memory, before any read
        assert cache._refreshing is not None
        await cache._refreshing
        assert calls[0] == 2  # both requests started the same single read
        newer = await cache.get()
        assert newer is not first and calls[0] == 2

        clock[0] = 700
        await cache.refresh()
        assert calls[0] == 3 and (await cache.get()) is not newer

    asyncio.run(run())


def test_a_response_cut_off_by_google_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 200
        headers: dict[str, str] = {}

        def __init__(self, body: bytes | None) -> None:
            self.body = body

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            if self.body is None:
                raise http.client.IncompleteRead(b"partial")
            return self.body

    replies = [Response(None), Response(b'{"ok": true}')]
    monkeypatch.setattr(sheets._opener, "open", lambda req, timeout: replies.pop(0))
    app = WebApp("https://script.google.com/macros/s/x/exec", sleep=lambda _s: None)
    assert app.post({"a": 1}) == {"ok": True}
    assert replies == []

    monkeypatch.setattr(sheets._opener, "open", lambda req, timeout: Response(None))
    with pytest.raises(SheetsError, match="cut off"):
        WebApp("https://script.google.com/macros/s/x/exec", retries=1, sleep=lambda _s: None).post({"a": 1})


def test_cache_without_configuration_is_empty_not_an_error() -> None:
    cache = SnapshotCache(bids_reader=None, jobs_reader=None, ttl_seconds=300)
    snap = asyncio.run(cache.get())
    assert snap.bids == [] and not snap.bids_source.configured and snap.bids_source.error is None


# ---- page numbers -------------------------------------------------------------------------------------------


def test_company_stats() -> None:
    s = service.stats(
        build(), people(), date_from=date(2026, 11, 1), date_to=date(2026, 11, 3), tab_keys=None, with_employees=True
    )
    assert s.applied == 4  # Carol's October bid is out of range
    assert s.scraped == 3 and s.scraped_bid == 2 and s.coverage_pct == 66.7
    assert s.outside_job_list == 1 and s.duplicates == 2 and s.active_bidders == 2
    assert [p.applied for p in s.series] == [0, 1, 3] and [p.scraped for p in s.series] == [1, 1, 1]
    assert s.avg_score == round((87 + 72 + 91 + 60) / 4, 1)
    assert {c.name: c.count for c in s.score_buckets}["90–100"] == 1
    rows = {r.name: r for r in s.employees}
    assert rows["Alice Smith"].applied == 3 and rows["Alice Smith"].by_day == [0, 1, 2]
    assert rows["Bob Jones"].employee_id == BOB  # tab "bob  jones" matches profile "Bob Jones"
    assert "Dan Idle" not in rows  # no profile name, no tab
    assert {c.name for c in s.roles} == {"US · Software", "EU · Software", "US · Data", "Not in job list"}


def test_one_employee_and_missing_profile() -> None:
    p = people()
    alice = p.by_id[ALICE]
    s = service.stats(
        build(), p, date_from=date(2026, 11, 1), date_to=date(2026, 11, 3), tab_keys=alice.keys, person=alice
    )
    assert s.applied == 3 and s.employees == [] and s.scraped_bid == 2
    assert [(c.name, c.count) for c in s.profiles] == [("alice smith", 3)]
    nobody = service.stats(
        build(), p, date_from=date(2026, 11, 1), date_to=date(2026, 11, 3), tab_keys=set(), profile_missing=True
    )
    assert nobody.applied == 0 and nobody.profile_missing


def test_links_queued_for_auto_bid_are_left_out_everywhere() -> None:
    omega = "https://jobs.lever.co/omega/3"
    rows = [
        bid_row(2, omega),  # only a Link: queued, on a job in the list
        bid_row(3, "https://a/1", status="pending", company="Filled in"),  # the web app says pending
        bid_row(4, "https://a/2", company="Acme", title="Dev"),  # no status from the sheet, and filled in
    ]
    rows[2].pop("status")
    snap = snapshot.build(
        [sheets.BidTab("Dana", BID_HEADER, rows)],
        sample_job_tabs(),
        now=NOW,
        bids_source=snapshot.SourceState(True, NOW),
        jobs_source=snapshot.SourceState(True, NOW),
    )
    assert [b.row for b in snap.bids] == [4] and snap.tabs[0].rows == snap.tabs[0].applied == 1
    job = next(j for j in snap.jobs if j.url == omega)
    assert job.status == "not_bid" and job.bids == []
    s = service.stats(snap, people(), date_from=date(2026, 11, 1), date_to=date(2026, 11, 3), tab_keys=None)
    assert s.scraped_bid == 0


def test_job_list_numbers_only_count_bids_in_the_period() -> None:
    # Acme is first seen Nov 1, but its bids are on Nov 2 and 3.
    nov1 = date(2026, 11, 1)
    s = service.stats(build(), people(), date_from=nov1, date_to=nov1, tab_keys=None)
    assert s.scraped == 1 and s.scraped_bid == 0 and s.coverage_pct == 0


def test_every_resume_is_listed_and_spacing_or_capitals_do_not_split_one() -> None:
    rows = [bid_row(i + 2, f"https://a/{i}", company="Acme", date="2026-11-03", resume=f"R{i}") for i in range(25)]
    rows += [
        bid_row(30, "https://a/30", company="Acme", date="2026-11-03", resume="Go  Dev"),
        bid_row(31, "https://a/31", company="Acme", date="2026-11-03", resume="go dev"),
    ]
    snap = snapshot.build(
        [sheets.BidTab("Dana", BID_HEADER, rows)],
        [],
        now=NOW,
        bids_source=snapshot.SourceState(True, NOW),
        jobs_source=snapshot.SourceState(True, NOW),
    )
    nov3 = date(2026, 11, 3)
    s = service.stats(snap, people(), date_from=nov3, date_to=nov3, tab_keys=None)
    assert len(s.resumes) == 26 and sum(c.count for c in s.resumes) == s.applied == 27
    assert name_key(s.resumes[0].name) == "go dev" and s.resumes[0].count == 2


def test_a_bid_with_no_date_sorts_after_dated_bids() -> None:
    rows = [
        bid_row(2, "https://a/1", company="Acme"),
        bid_row(3, "https://a/2", company="Beta", date="2026-11-03"),
    ]
    snap = snapshot.build(
        [sheets.BidTab("Dana", BID_HEADER, rows)],
        [],
        now=NOW,
        bids_source=snapshot.SourceState(True, NOW),
        jobs_source=snapshot.SourceState(True, NOW),
    )
    assert [b.company for b in service.filter_bids(snap, tab_keys=None)] == ["Beta", "Acme"]


def test_daily_lists_everyone_with_a_profile_and_unclaimed_tabs() -> None:
    nov3 = date(2026, 11, 3)
    d = service.daily(build(), people(), date_from=nov3, date_to=nov3, tab_keys=None)
    rows = {r.name: r for r in d.rows}
    assert d.applied == 3 and d.active_bidders == 2 and d.scraped == 1
    assert (
        rows["Alice Smith"].applied == 2
        and rows["Alice Smith"].in_job_list == 1
        and rows["Alice Smith"].max_score == 91
    )
    assert "Carol" not in rows  # an unclaimed tab only shows on days it has bids
    day = date(2026, 10, 1)
    oct1 = {r.name: r for r in service.daily(build(), people(), date_from=day, date_to=day, tab_keys=None).rows}
    assert oct1["Carol"].employee_id is None and oct1["Carol"].applied == 1
    assert oct1["Bob Jones"].applied == 0  # everyone with a profile name is listed


def test_daily_over_a_range_with_top_resumes() -> None:
    d = service.daily(build(), people(), date_from=date(2026, 11, 1), date_to=date(2026, 11, 3), tab_keys=None)
    rows = {r.name: r for r in d.rows}
    assert d.applied == 4 and d.scraped == 3 and d.active_bidders == 2
    assert rows["Alice Smith"].applied == 3 and rows["Bob Jones"].applied == 1

    # Every resume is returned, most used first, so the pages can show the top three and count the rest.
    snap = build()
    alice_bids = [b for b in snap.bids if b.tab_key == name_key("Alice Smith")]
    template = alice_bids[0]
    extra = [("R1", 3), ("R2", 2), ("R3", 1), ("R4", 1)]
    snap.bids = [b for b in snap.bids if b.tab_key != template.tab_key] + [
        replace(template, resume=name, row=100 + i) for name, n in extra for i in range(n)
    ]
    row = next(
        r
        for r in service.daily(snap, people(), date_from=template.date, date_to=template.date, tab_keys=None).rows
        if r.name == "Alice Smith"
    )
    assert [(c.name, c.count) for c in row.resumes][:2] == [("R1", 3), ("R2", 2)]
    assert len(row.resumes) == 4


def test_an_employee_with_several_profiles_is_one_person() -> None:
    # Alice also owns the tab "Carol"; "bob  jones" stays unclaimed.
    p = service.People([service.Person(ALICE, "Alice Smith", ("Alice Smith", "Carol"))])
    snap = build()
    s = service.stats(
        snap, p, date_from=date(2026, 10, 1), date_to=date(2026, 11, 3), tab_keys=None, with_employees=True
    )
    rows = {r.name: r for r in s.employees}
    assert set(rows) == {"Alice Smith", "bob  jones"} and s.active_bidders == 2
    assert rows["Alice Smith"].applied == 4 and rows["Alice Smith"].tabs == ["Alice Smith", "Carol"]
    assert rows["bob  jones"].employee_id is None and rows["bob  jones"].tabs == ["bob  jones"]

    alice = p.by_id[ALICE]
    one = service.stats(
        snap, p, date_from=date(2026, 10, 1), date_to=date(2026, 11, 3), tab_keys=alice.keys, person=alice
    )
    assert one.applied == 4 and {c.name: c.count for c in one.profiles} == {"Alice Smith": 3, "Carol": 1}
    assert one.profile_names == ["Alice Smith", "Carol"]

    day = date(2026, 10, 1)
    d = service.daily(snap, p, date_from=day, date_to=day, tab_keys=None)
    assert {r.name: r.applied for r in d.rows}["Alice Smith"] == 1 and d.active_bidders == 1

    assert service.bid_out(next(b for b in snap.bids if b.tab == "Carol"), p).employee_id == ALICE
    assert len(service.filter_jobs(snap, tab_keys=alice.keys)) == 2 and service.filter_jobs(snap, tab_keys=set()) == []
    assert service.sources(snap, p, 300).unclaimed_tabs == ["bob  jones"]
    assert service.available_tabs(snap, p, alice.keys) == ["Alice Smith", "bob  jones", "Carol"]

    gone = service.People([service.Person(ALICE, "Alice Smith", ("Alice Smith", "No Such Tab"))])
    assert [x.profile_names for x in service.sources(snap, gone, 300).profiles_without_tab] == [["No Such Tab"]]


def test_filters_and_rows() -> None:
    snap, p = build(), people()
    ranged = service.filter_bids(snap, tab_keys=None, date_from=date(2026, 11, 3), date_to=date(2026, 11, 3))
    assert len(ranged) == 3
    assert len(service.filter_bids(snap, tab_keys=None, min_score=85)) == 2
    assert len(service.filter_bids(snap, tab_keys=None, q="backend")) == 2
    assert [
        service.bid_out(b, p).employee_name for b in service.filter_bids(snap, tab_keys=None, duplicates_only=True)
    ] == ["Bob Jones", "Alice Smith"]
    outside = service.filter_bids(snap, tab_keys=None, outside_only=True)
    assert sorted(b.company for b in outside) == ["Gamma", "Zeta"]

    assert [j.status for j in service.filter_jobs(snap)] == ["not_bid", "applied", "applied"]  # newest first
    assert len(service.filter_jobs(snap, status="not_bid")) == 1
    assert len(service.filter_jobs(snap, region=["US"], role=["Data"])) == 1
    software = service.filter_jobs(snap, role=["Software"])
    assert len(service.filter_jobs(snap, role=["Software", "Data"])) == len(software) + 1
    assert service.filter_jobs(snap, ats=["No Such ATS"]) == []
    assert len(service.filter_jobs(snap, tab_keys={name_key("Bob Jones")})) == 1
    out = service.job_out(next(j for j in snap.jobs if j.duplicate), p)
    assert [b.employee_name for b in out.bids] == ["Alice Smith", "Bob Jones"]
    assert service.facets(snap).regions == ["EU", "US"]  # EU only lists a job that US lists first


def test_sources_report_claims() -> None:
    src = service.sources(build(), people(), 300)
    assert src.unclaimed_tabs == ["Carol"]
    assert {t.name: t.employee_name for t in src.tabs}["bob  jones"] == "Bob Jones"
    assert [j.name for j in src.job_tabs] == ["US - Software", "US - Data", "EU - Software"]
    assert service.available_tabs(build(), people(), {name_key("alice smith")}) == ["Alice Smith", "Carol"]


def test_clamp_range() -> None:
    today = date(2026, 11, 3)
    assert service.clamp_range(None, None, today) == (date(2026, 10, 5), today)
    assert service.clamp_range(date(2026, 11, 3), date(2026, 11, 1), today) == (date(2026, 11, 1), date(2026, 11, 3))
    start, end = service.clamp_range(date(2020, 1, 1), today, today)
    assert (end - start).days == service.MAX_RANGE_DAYS - 1


def test_settings_url_must_be_an_apps_script_web_app() -> None:
    from app.modules.bidding.config import check_url, hint

    assert check_url("https://script.google.com/macros/s/AKfy/exec", "u") is None
    assert check_url("https://script.google.com/a/macros/acme.com/s/AKfy/exec", "u") is None
    assert check_url("", "u") is None
    for bad in (
        "http://script.google.com/macros/s/x/exec",
        "https://evil.com/exec",
        "https://script.google.com/macros/s/x/dev",
    ):
        assert check_url(bad, "u") is not None, bad
    assert hint("abcdefgh1234") == "…1234" and hint("") is None and hint("short") == "set"
