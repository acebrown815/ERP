"""Where the two web apps are, as plain values (pure: no database). store.py loads and saves them;
Settings → Bidding Sheets edits them."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

SECRET_FIELDS = ("bids_secret", "jobs_token")
TEXT_FIELDS = ("bids_webapp_url", "bids_secret", "jobs_webapp_url", "jobs_token", "jobs_tabs")
# Each web app URL and the secret that may be sent to it.
URL_SECRET_FIELDS = (("bids_webapp_url", "bids_secret"), ("jobs_webapp_url", "jobs_token"))
# Job-list tabs are named "<region> - <role>". Used until other names are saved.
DEFAULT_JOB_TABS = (
    "US - Software",
    "US - ML/AI",
    "US - Data",
    "US - DevOps/SRE",
    "EU - Software",
    "EU - ML/AI",
    "EU - Data",
    "EU - DevOps/SRE",
)


def tab_names(raw: str | None) -> list[str]:
    return [n.strip() for n in (raw or "").split(",") if n.strip()]


@dataclass(frozen=True)
class SourceConfig:
    bids_url: str = ""
    bids_secret: str = ""
    jobs_url: str = ""
    jobs_token: str = ""
    jobs_tabs: tuple[str, ...] = ()
    cache_seconds: int = 300
    timeout_seconds: int = 120

    @property
    def bids_configured(self) -> bool:
        return bool(self.bids_url and self.bids_secret)

    @property
    def jobs_configured(self) -> bool:
        return bool(self.jobs_url and self.jobs_token)


def hint(secret: str) -> str | None:
    """Last four characters, enough to tell which secret is saved."""
    return f"…{secret[-4:]}" if len(secret) >= 8 else ("set" if secret else None)


def check_url(value: str, field_name: str) -> dict[str, Any] | None:
    """Only Apps Script web app URLs: the server fetches this address, so it must not point anywhere else."""
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.hostname != "script.google.com" or not parts.path.rstrip("/").endswith("/exec"):
        # Same shape as app.core.errors.field_error (kept import-free so this module stays pure).
        return {
            "field": field_name,
            "code": "invalid_url",
            "message": "Paste the web app URL: https://script.google.com/macros/s/…/exec",
        }
    return None
