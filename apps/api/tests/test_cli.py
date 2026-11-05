"""The seed that runs on every deploy (`migrate --seed`, see infra/docker-compose.yml)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli


async def _purposes(db: AsyncSession) -> int:
    sql = "SELECT count(*) FROM categories WHERE system_key = 'hire_payment'"
    return (await db.execute(text(sql))).scalar_one()


async def _remove_purpose(db: AsyncSession) -> None:
    await db.execute(text("DELETE FROM categories WHERE system_key = 'hire_payment'"))


async def test_a_deploy_adds_what_a_release_introduced_and_keeps_the_rest(db: AsyncSession) -> None:
    await _remove_purpose(db)
    await db.execute(text("UPDATE company_settings SET name = 'ChonRyong Inc'"))
    await db.execute(
        text("UPDATE categories SET name = 'Renamed', is_active = false WHERE system_key = 'employee_salary'")
    )
    await db.commit()

    await cli.seed_existing()

    assert await _purposes(db) == 1
    assert (await db.execute(text("SELECT name FROM company_settings"))).scalars().all() == ["ChonRyong Inc"]
    salary = await db.execute(text("SELECT name, is_active FROM categories WHERE system_key = 'employee_salary'"))
    assert salary.one() == ("Renamed", False)


async def test_a_deploy_leaves_a_first_install_for_the_named_seed(db: AsyncSession) -> None:
    await _remove_purpose(db)
    await db.execute(text("DELETE FROM company_settings"))
    await db.commit()

    await cli.seed_existing()

    assert (await db.execute(text("SELECT count(*) FROM company_settings"))).scalar_one() == 0
    assert await _purposes(db) == 0
