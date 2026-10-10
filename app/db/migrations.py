import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from db.database import make_engine

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

# The first migration; it matches the schema that Base.metadata.create_all() used to build
BASELINE_REVISION = "0001"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    # ConfigParser treats "%" as interpolation, so escape it (e.g. in URL-encoded passwords)
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _get_table_names(database_url: str) -> set[str]:
    engine = make_engine(database_url)
    try:
        async with engine.connect() as connection:
            return set(await connection.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names()))
    finally:
        await engine.dispose()


def run_migrations(database_url: Optional[str] = None) -> None:
    """Upgrades the database schema to the latest migration.

    Databases created before Alembic was introduced (tables exist, no alembic_version)
    are first stamped with the baseline revision, so their existing tables are not recreated.
    Blocking: call it via asyncio.to_thread() from async code.
    """
    database_url = database_url or os.environ["DATABASE_URL"]
    config = _alembic_config(database_url)

    tables = asyncio.run(_get_table_names(database_url))
    if "receipts" in tables and "alembic_version" not in tables:
        logging.info(f"Existing schema without Alembic history found; stamping baseline {BASELINE_REVISION}")
        command.stamp(config, BASELINE_REVISION)

    command.upgrade(config, "head")
    logging.info("Database schema is up to date")
