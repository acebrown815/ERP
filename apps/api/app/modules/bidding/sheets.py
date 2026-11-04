"""Clients for the two Google Apps Script web apps. Read-only; nothing here writes to a sheet.

Bids  (BidExtension docs/sheets-sync/Code.gs): {secret, listTabs} / {secret, readTabs}
Jobs  (job-scraper apps_script/Code.gs):       {token, sheet, action: "read_columns", columns, offset, limit}

Apps Script answers a POST with a 302 to a script.googleusercontent.com .../echo URL that holds the result. That
URL is fetched with GET. A redirect within script.google.com gets the POST again (a POST turned into a GET would
reach doGet and lose the request). The POST body holds the secret, so no other host is ever contacted. Google
sometimes loses the result (404 on the echo URL, or a redirect elsewhere), so calls are retried; every call is a
read, so retrying is always safe. Ported from job-scraper sheets.py.

Uses the standard library only (urllib), run in a worker thread so the event loop never blocks.
"""

import asyncio
import http.client
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

# (url, body or None for GET, timeout) -> (status, headers lower-cased, body bytes)
Transport = Callable[[str, bytes | None, float], tuple[int, dict[str, str], bytes]]

JOB_COLUMNS = [
    "key",
    "title",
    "company",
    "location",
    "country",
    "remote",
    "skill_level",
    "salary",
    "ats",
    "is_recruiter",
    "posted_at",
    "first_seen",
    "url",
]
READ_CHUNK_ROWS = 5_000


class SheetsError(Exception):
    """A web app could not be reached or answered with an error. The message is shown to admins."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def urllib_transport(url: str, body: bytes | None, timeout: float) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
    if body is not None:
        # text/plain avoids nothing server-side but matches what the extension sends.
        req.add_header("Content-Type", "text/plain;charset=utf-8")
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as e:  # 3xx (not followed), 4xx, 5xx
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b""
    except http.client.HTTPException as e:  # e.g. IncompleteRead: Google cut the response off partway
        raise _Retry(f"the response was cut off ({type(e).__name__})") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SheetsError(f"could not reach the web app ({getattr(e, 'reason', e)})") from e


class _Retry(Exception):
    pass


def _is_echo_url(url: str) -> bool:
    """Where Apps Script leaves the result: /macros/echo, or /a/macros/<domain>/echo for a Workspace account."""
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == "script.googleusercontent.com" and parts.path.endswith("/echo")


def _may_receive_post(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == "script.google.com"


@dataclass
class WebApp:
    url: str
    transport: Transport = urllib_transport
    timeout: float = 120.0
    retries: int = 4
    sleep: Callable[[float], None] = time.sleep

    def _post_once(self, body: bytes) -> dict[str, Any]:
        status, headers, content = self.transport(self.url, body, self.timeout)
        for _ in range(5):
            if status not in (301, 302, 303, 307, 308):
                break
            location = headers.get("location", "")
            if not location:
                raise _Retry("redirect without a location")
            if _is_echo_url(location):
                status, headers, content = self.transport(location, None, self.timeout)
                if status == 404 or status in (301, 302, 303, 307, 308):
                    raise _Retry(f"Google lost the result (HTTP {status})")
                break
            if not _may_receive_post(location):
                raise _Retry(f"redirected away from the web app, to {urlsplit(location).hostname or 'an unknown host'}")
            status, headers, content = self.transport(location, body, self.timeout)
        else:
            raise _Retry("too many redirects")
        if status in (429, 500, 502, 503, 504):
            raise _Retry(f"HTTP {status}")
        if status != 200:
            raise SheetsError(f"web app returned HTTP {status}; check the URL ends in /exec and access is 'Anyone'")
        try:
            data = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise SheetsError(
                "web app did not return JSON; check the URL ends in /exec and the deployment's access is 'Anyone'"
            ) from e
        if not isinstance(data, dict):
            raise SheetsError("web app returned an unexpected response")
        if "service" in data or (data.get("status") == "ok" and "message" in data):
            raise _Retry("request reached doGet instead of doPost")
        return data

    def post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        last = ""
        for attempt in range(self.retries + 1):
            try:
                return self._post_once(body)
            except _Retry as e:
                last = str(e)
                if attempt < self.retries:
                    self.sleep(min(2 * 2**attempt, 15))
        raise SheetsError(f"web app kept failing: {last}")


@dataclass
class BidTab:
    name: str
    header: list[str]
    rows: list[dict[str, Any]]


class BidsClient:
    """BidExtension web app: one tab per employee."""

    def __init__(self, app: WebApp, secret: str) -> None:
        self.app, self.secret = app, secret

    def _call(self, **params: Any) -> dict[str, Any]:
        data = self.app.post({"secret": self.secret, **params})
        if not data.get("success"):
            error = str(data.get("error") or "unknown error")
            if "neither" in error:
                error += " (the web app is an older version: re-deploy docs/sheets-sync/Code.gs as a new version)"
            raise SheetsError(error)
        return data

    def read_all(self) -> list[BidTab]:
        data = self._call(readTabs=True)
        tabs = []
        for t in data.get("tabs") or []:
            rows = [r for r in (t.get("rows") or []) if isinstance(r, dict)]
            tabs.append(BidTab(name=str(t.get("name") or ""), header=list(t.get("header") or []), rows=rows))
        return tabs


@dataclass
class JobTab:
    name: str
    header: list[str]
    rows: list[dict[str, Any]]


class JobsClient:
    """job-scraper web app. Only the configured tab names are read: its getSheet_ creates a missing tab."""

    def __init__(self, app: WebApp, token: str, chunk: int = READ_CHUNK_ROWS) -> None:
        self.app, self.token, self.chunk = app, token, chunk

    def _call(self, sheet: str, **params: Any) -> dict[str, Any]:
        data = self.app.post({"token": self.token, "sheet": sheet, **params})
        if not data.get("ok"):
            raise SheetsError(f"{sheet}: {data.get('error') or 'unknown error'}")
        return data

    def read_tab(self, sheet: str) -> JobTab:
        header: list[str] = []
        columns: dict[str, list[Any]] = {c: [] for c in JOB_COLUMNS}
        offset = 0
        while True:
            data = self._call(sheet, action="read_columns", columns=JOB_COLUMNS, offset=offset, limit=self.chunk)
            if "columns" not in data or "total_rows" not in data:
                raise SheetsError(f"{sheet}: unexpected response from the job-list web app")
            header = [str(h) for h in data.get("header") or []]
            got = max((len(v) for v in data["columns"].values()), default=0)
            for c in JOB_COLUMNS:
                values = list(data["columns"].get(c) or [])
                columns[c].extend(values + [""] * (got - len(values)))
            offset += got
            if not got or offset >= int(data["total_rows"]):
                break
        n = len(columns["key"])
        rows = [{c: columns[c][i] for c in JOB_COLUMNS} for i in range(n)]
        return JobTab(name=sheet, header=header, rows=rows)

    def read_tabs(self, names: list[str]) -> list[JobTab]:
        return [self.read_tab(n) for n in names]


async def in_thread[T](fn: Callable[[], T]) -> T:
    return await asyncio.to_thread(fn)


def test_bids(app: WebApp, secret: str) -> list[tuple[str, int]]:
    """The tabs the bids web app sees, or SheetsError. Needs the listTabs action (current Code.gs)."""
    data = BidsClient(app, secret)._call(listTabs=True)
    return [(str(t.get("name") or ""), int(t.get("rows") or 0)) for t in data.get("tabs") or []]


def test_jobs(app: WebApp, token: str, tabs: list[str]) -> list[tuple[str, int]]:
    """Row count per job-list tab, reading one row of each. Note: that script creates a tab it doesn't have."""
    client = JobsClient(app, token)
    out = []
    for name in tabs:
        data = client._call(name, action="read_columns", columns=["key"], offset=0, limit=1)
        out.append((name, int(data.get("total_rows") or 0)))
    return out
