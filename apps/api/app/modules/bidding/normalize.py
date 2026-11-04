"""Matching keys shared by the two sheets. Pure functions, no I/O.

url_key   ports BidExtension lib/urlKey.mjs (normalizeUrlForCache) so the ERP and the extension agree on
          "same job". It is a little more lenient for cross-source matching: http/https and a leading "www."
          are treated as the same site.
job_identity  ports job-scraper scrape.job_identity (company + title), the fallback when URLs differ.
name_key  how a sheet tab name is compared with an employee's bidding profile name.
"""

import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = frozenset(
    {
        "gclid",
        "fbclid",
        "msclkid",
        "dclid",
        "twclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "_ga",
        "_gl",
        "ref",
        "referrer",
        "referer",
        "source",
        "src",
        "from",
        "utm",
        "jr_id",
    }
)
_WORKDAY_HOST = re.compile(r"(^|\.)myworkday(jobs|site)\.com$")
_WORKDAY_LANG = re.compile(r"^/[a-z]{2}-[A-Z]{2}(?=/)")
_WORKDAY_APPLY = re.compile(r"/apply(/[^/]*)?$")


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k in TRACKING_PARAMS or k.startswith("utm_")


def url_key(raw: object) -> str:
    """Stable "same posting" key for a job URL; "" for anything that isn't an http(s) URL."""
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        return ""
    host = parts.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"

    params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)]
    params.sort(key=lambda kv: kv[0])  # stable, like the extension's sort by key

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    if _WORKDAY_HOST.search(host):
        path = _WORKDAY_APPLY.sub("", _WORKDAY_LANG.sub("", path))
    for suffix in ("/application", "/apply"):
        if path.endswith(suffix):
            path = path[: -len(suffix)] or "/"
            break
    return urlunsplit(("https", host, path, urlencode(params), ""))


_COMPANY_SUFFIXES = re.compile(r"\b(inc|llc|ltd|limited|corp|corporation|co|gmbh|hq|careers|jobs)\b")


def job_identity(company: object, title: object) -> str:
    """Company + title, normalized ("Agile-Defense" == "agiledefense", "Senior Engineer (Remote)" ==
    "senior engineer"). "" when either part is missing, so blank rows never match each other."""
    c = str(company or "").lower()
    c = _COMPANY_SUFFIXES.sub(" ", re.sub(r"[-_.]", " ", c))
    c = re.sub(r"[^a-z0-9]", "", c)
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", str(title or "").lower())
    t = re.sub(r"\b(remote|hybrid)\b", " ", t)
    t = " ".join(re.sub(r"[^a-z0-9+#]+", " ", t).split())
    if not c or not t:
        return ""
    return f"{c}|{t}"


def name_key(name: object) -> str:
    """Tab name / profile name comparison: case-insensitive, surrounding and repeated spaces ignored."""
    return " ".join(str(name or "").split()).casefold()


_SHEETS_EPOCH = date(1899, 12, 30)


def parse_date(value: object) -> date | None:
    """Sheet dates arrive as "yyyy-MM-dd" (the web apps format date cells), but hand-typed cells may be
    "M/D/YYYY", ISO timestamps or a Sheets serial number."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int | float):
        return _SHEETS_EPOCH + timedelta(days=int(value)) if 20000 < value < 80000 else None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text.split(" ")[0], fmt).date()
        except ValueError:
            continue
    return None


def parse_score(value: object) -> float | None:
    """Match score: a number, or text like "87" / "87%". Out-of-range values are ignored."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        score = float(str(value).strip().rstrip("%").strip())
    except ValueError:
        return None
    return score if 0 <= score <= 100 else None


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("true", "yes", "1", "y")


def cell_text(value: object) -> str:
    """Cell value as trimmed text; job-scraper writes strings with a leading ' to keep them literal."""
    s = "" if value is None else str(value).strip()
    return s[1:] if s.startswith("'") else s
