"""Failed passwords are counted so that guessing stops, but someone else's guessing can't lock a user out."""

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.main import app
from app.modules.auth.models import User
from tests.conftest import PASSWORD, ClientFactory, create_user, login

BAD = "bad-password-x"


def client_from(ip: str) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(ip, 1234))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def attempts(ip: str, email: str, times: int, password: str = BAD) -> list[int]:
    async with client_from(ip) as c:
        return [(await login(c, email, password)).status_code for _ in range(times)]


async def test_guessing_from_one_address_does_not_lock_out_the_real_user() -> None:
    await create_user("boss@example.com", "admin")
    assert await attempts("203.0.113.9", "boss@example.com", 6) == [401] * 5 + [429]

    assert await attempts("198.51.100.7", "boss@example.com", 1, PASSWORD) == [200]


async def test_the_guessing_address_is_refused_even_with_the_right_password() -> None:
    await create_user("boss@example.com", "admin")
    await attempts("203.0.113.9", "boss@example.com", 5)

    assert await attempts("203.0.113.9", "boss@example.com", 1, PASSWORD) == [429]


async def test_one_address_trying_many_accounts_is_stopped() -> None:
    limit = get_settings().login_ip_max_failures
    results = [(await attempts("203.0.113.9", f"nobody{n}@example.com", 1))[0] for n in range(limit + 1)]

    assert results == [401] * limit + [429]


async def test_guessing_one_account_from_many_addresses_locks_it() -> None:
    await create_user("boss@example.com", "admin")
    settings = get_settings()
    per_address = settings.login_max_failures
    addresses = settings.login_account_max_failures // per_address
    for n in range(addresses):
        assert await attempts(f"203.0.113.{n + 1}", "boss@example.com", per_address) == [401] * per_address

    assert await attempts("198.51.100.7", "boss@example.com", 1, PASSWORD) == [429]
    async with SessionLocal() as s:
        user = (await s.execute(select(User).where(User.email == "boss@example.com"))).scalar_one()
    assert user.locked_until is not None


async def test_signing_in_does_not_reset_the_count_of_guesses_from_that_address() -> None:
    await create_user("me@example.com", "employee")
    limit = get_settings().login_ip_max_failures
    for n in range(limit - 1):
        await attempts("203.0.113.9", f"victim{n}@example.com", 1)

    assert await attempts("203.0.113.9", "me@example.com", 1, PASSWORD) == [200]
    assert await attempts("203.0.113.9", "victim@example.com", 2) == [401, 429]


async def test_a_successful_sign_in_clears_that_users_own_mistakes() -> None:
    await create_user("me@example.com", "employee")
    await attempts("203.0.113.9", "me@example.com", 4)
    assert await attempts("203.0.113.9", "me@example.com", 1, PASSWORD) == [200]

    assert await attempts("203.0.113.9", "me@example.com", 4) == [401] * 4


async def test_guessing_the_current_password_with_a_stolen_session_is_stopped(client_as: ClientFactory) -> None:
    c = await client_as("employee")
    body = {"current_password": BAD, "new_password": "A-New-Password-1"}
    limit = get_settings().login_max_failures
    results = [(await c.post("/api/v1/auth/change-password", json=body)).status_code for _ in range(limit + 1)]

    assert results[-1] == 429
    assert all(code != 429 for code in results[:-1])
    right = {"current_password": PASSWORD, "new_password": "A-New-Password-1"}
    assert (await c.post("/api/v1/auth/change-password", json=right)).status_code == 429
