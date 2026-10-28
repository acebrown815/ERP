from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ERP_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://erp:erp@127.0.0.1:54329/erp"
    db_pool_size: int = 10
    # Tests use NullPool so connections never outlive their event loop.
    db_null_pool: bool = False

    session_cookie_name: str = "erp_session"
    csrf_cookie_name: str = "erp_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    cookie_secure: bool = False
    session_idle_minutes: int = 12 * 60
    session_absolute_hours: int = 7 * 24

    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    password_min_length: int = 10
    # Test-only: cheap Argon2 parameters. Never enable in production.
    fast_password_hashing: bool = False

    attachments_dir: str = "./var/attachments"
    attachments_max_bytes: int = 25 * 1024 * 1024

    log_json: bool = False
    log_level: str = "INFO"

    worker_poll_seconds: float = 1.0
    worker_batch_size: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()
